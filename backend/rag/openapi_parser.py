"""
Parses an OpenAPI 3.x (or Swagger 2.0) spec into a flat, generator-friendly
list of endpoints. Deliberately minimal — no $ref resolution beyond one
level, no full JSON Schema validation. Good enough to drive test-case
generation off path/method/parameters/request body/responses, which is all
the generator actually needs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}


class OpenApiParseError(ValueError):
    pass


@dataclass
class ParameterSpec:
    name: str
    location: str  # "path" | "query" | "header" | "cookie"
    required: bool
    schema_type: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    enum: Optional[List[Any]] = None


@dataclass
class EndpointSpec:
    path: str
    method: str  # upper-case, e.g. "GET"
    operation_id: Optional[str]
    summary: Optional[str]
    parameters: List[ParameterSpec] = field(default_factory=list)
    request_body_required: bool = False
    request_body_content_type: Optional[str] = None
    success_status_codes: List[str] = field(default_factory=list)
    error_status_codes: List[str] = field(default_factory=list)
    requires_auth: bool = False

    @property
    def endpoint_id(self) -> str:
        return f"{self.method} {self.path}"


def parse_spec(filename: str, content: bytes) -> List[EndpointSpec]:
    spec = _load_spec(filename, content)
    if not isinstance(spec, dict) or "paths" not in spec:
        raise OpenApiParseError("This doesn't look like an OpenAPI/Swagger spec (no top-level 'paths').")

    global_security = bool(spec.get("security"))
    endpoints: List[EndpointSpec] = []

    for path, path_item in spec.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        path_level_params = _parse_parameters(path_item.get("parameters", []))

        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue

            op_params = path_level_params + _parse_parameters(operation.get("parameters", []))
            request_body = operation.get("requestBody", {})
            content_types = list(request_body.get("content", {}).keys()) if isinstance(request_body, dict) else []

            responses = operation.get("responses", {})
            success_codes = [c for c in responses if str(c).startswith(("2",))]
            error_codes = [c for c in responses if str(c).startswith(("4", "5"))]

            endpoints.append(
                EndpointSpec(
                    path=path,
                    method=method.upper(),
                    operation_id=operation.get("operationId"),
                    summary=operation.get("summary") or operation.get("description"),
                    parameters=op_params,
                    request_body_required=bool(request_body.get("required")) if isinstance(request_body, dict) else False,
                    request_body_content_type=content_types[0] if content_types else None,
                    success_status_codes=sorted(success_codes),
                    error_status_codes=sorted(error_codes),
                    requires_auth=bool(operation.get("security")) or global_security,
                )
            )

    if not endpoints:
        raise OpenApiParseError("No HTTP operations found under 'paths' in this spec.")

    return endpoints


def _load_spec(filename: str, content: bytes) -> Dict:
    text = content.decode("utf-8")
    lower = filename.lower()
    try:
        if lower.endswith((".yaml", ".yml")):
            return yaml.safe_load(text)
        if lower.endswith(".json"):
            return json.loads(text)
        # Unknown extension: try JSON first, fall back to YAML (which is a
        # superset of JSON syntax anyway).
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OpenApiParseError(f"Could not parse '{filename}' as JSON or YAML: {exc}") from exc


def _parse_parameters(raw_params: List[Dict]) -> List[ParameterSpec]:
    parsed = []
    for p in raw_params:
        if not isinstance(p, dict) or "name" not in p:
            continue
        schema = p.get("schema", {}) if isinstance(p.get("schema"), dict) else {}
        parsed.append(
            ParameterSpec(
                name=p["name"],
                location=p.get("in", "query"),
                required=bool(p.get("required", False)),
                schema_type=schema.get("type"),
                minimum=schema.get("minimum"),
                maximum=schema.get("maximum"),
                enum=schema.get("enum"),
            )
        )
    return parsed
