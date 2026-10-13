"""
Generates test cases directly from OpenAPI endpoint definitions, rather
than from prose requirements. Template-based by default (works with no API
key, and — unlike prose generation — there's no ambiguity to resolve since
the spec already states exact paths, methods, and parameters); the LLM path
is used only to write friendlier titles/step wording when a key is present,
never to invent the endpoint facts themselves.
"""
from __future__ import annotations

from typing import List, Optional

from backend.models.schemas import TestCase
from backend.rag.openapi_parser import EndpointSpec

PLACEHOLDER_VALUES = {
    "string": "sample-value",
    "integer": "1",
    "number": "1.0",
    "boolean": "true",
}


def generate_api_test_cases(endpoints: List[EndpointSpec], spec_filename: str) -> List[TestCase]:
    test_cases: List[TestCase] = []
    counter = 1

    for ep in endpoints:
        citation = f"OpenAPI: {ep.endpoint_id} ({spec_filename})"

        test_cases.append(_positive_case(ep, counter, citation))
        counter += 1

        if any(p.required and p.location != "path" for p in ep.parameters) or ep.request_body_required:
            test_cases.append(_negative_missing_required_case(ep, counter, citation))
            counter += 1

        bounded_values = _bounded_values(ep)
        if bounded_values:
            test_cases.append(_boundary_case(ep, bounded_values, counter, citation))
            counter += 1

        invalid_values = _invalid_schema_values(ep)
        if invalid_values:
            test_cases.append(_negative_constraint_case(ep, invalid_values, counter, citation))
            counter += 1

        if ep.requires_auth:
            test_cases.append(_auth_negative_case(ep, counter, citation))
            counter += 1

    return test_cases


def _example_for(param) -> str:
    if param.enum:
        return str(param.enum[0])
    return PLACEHOLDER_VALUES.get(param.schema_type or "string", "sample-value")


def _positive_case(ep: EndpointSpec, n: int, citation: str) -> TestCase:
    param_desc = ", ".join(f"{p.name}={_example_for(p)}" for p in ep.parameters) or "no parameters"
    steps = [f"Send a {ep.method} request to {ep.path} with valid values ({param_desc})"]
    if ep.request_body_required:
        steps.append(f"Include a valid request body ({ep.request_body_content_type or 'application/json'})")
    steps.append("Inspect the HTTP status code and response body")

    expected = (
        f"Returns {ep.success_status_codes[0] if ep.success_status_codes else '2xx'} with a response "
        "matching the documented schema."
    )

    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — valid request returns success",
        type="api",
        priority="high",
        preconditions=(["Valid API credentials are available"] if ep.requires_auth else ["API is reachable"]),
        steps=steps,
        expected_result=expected,
        requirement_reference=citation,
        source_chunk=(ep.summary or f"{ep.method} {ep.path}"),
    )


def _negative_missing_required_case(ep: EndpointSpec, n: int, citation: str) -> TestCase:
    required_names = [p.name for p in ep.parameters if p.required and p.location != "path"]
    required_body_names = [p.name for p in ep.request_body_properties if p.required]
    subjects = []
    if required_names:
        subjects.append("required non-path parameter(s): " + ", ".join(required_names))
    if required_body_names:
        subjects.append("required body field(s): " + ", ".join(required_body_names))
    if ep.request_body_required and not required_body_names:
        subjects.append("the required request body")
    subject = "; ".join(subjects)

    steps = [
        f"Send a {ep.method} request to {ep.path} omitting {subject}",
        "Inspect the HTTP status code and error response body",
    ]
    status_expectation = _validation_status_expectation(ep)

    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — missing required field is rejected",
        type="negative",
        priority="high",
        preconditions=(["Valid API credentials are available"] if ep.requires_auth else ["API is reachable"]),
        steps=steps,
        expected_result=f"Rejects the request with {status_expectation} and identifies the missing required input.",
        requirement_reference=citation,
        source_chunk=(ep.summary or f"{ep.method} {ep.path}"),
    )


def _validation_status_expectation(ep: EndpointSpec) -> str:
    declared = [code for code in ("400", "422") if code in ep.error_status_codes]
    if declared:
        return "HTTP " + " or ".join(declared)
    return "a client error (the exact validation status is not documented for this operation)"


def _describe_bounds(item) -> Optional[str]:
    constraints = []
    if item.minimum is not None:
        constraints.append(f"minimum={item.minimum}")
    if item.maximum is not None:
        constraints.append(f"maximum={item.maximum}")
    elif item.minimum is not None:
        constraints.append("no documented maximum")
    if item.min_length is not None:
        constraints.append(f"minLength={item.min_length}")
    elif item.max_length is not None:
        constraints.append("no documented minLength")
    if item.max_length is not None:
        constraints.append(f"maxLength={item.max_length}")
    elif item.min_length is not None:
        constraints.append("no documented maxLength")
    return ", ".join(constraints) if constraints else None


def _bounded_values(ep: EndpointSpec) -> List[str]:
    values = []
    for param in ep.parameters:
        bounds = _describe_bounds(param)
        if bounds:
            values.append(f"{param.location} parameter {param.name} ({bounds})")
    for prop in ep.request_body_properties:
        bounds = _describe_bounds(prop)
        if bounds:
            values.append(f"request body field {prop.name} ({bounds})")
    return values


def _boundary_case(ep: EndpointSpec, bounded_values: List[str], n: int, citation: str) -> TestCase:
    boundary_desc = "; ".join(bounded_values)

    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — boundary values for constrained inputs",
        type="boundary",
        priority="medium",
        preconditions=(["Valid API credentials are available"] if ep.requires_auth else ["API is reachable"]),
        steps=[
            f"Send requests to {ep.method} {ep.path} with values at each documented boundary and one unit outside: {boundary_desc}",
            "Inspect the HTTP status code and response for each value",
        ],
        expected_result=f"Values within documented constraints are accepted; values outside are rejected with {_validation_status_expectation(ep)}.",
        requirement_reference=citation,
        source_chunk=(ep.summary or f"{ep.method} {ep.path}"),
    )


def _format_invalid_value(schema_format: Optional[str]) -> Optional[str]:
    examples = {
        "uuid": "not-a-uuid",
        "email": "not-an-email",
        "date": "not-a-date",
        "date-time": "not-a-date-time",
        "uri": "not a uri",
        "ipv4": "999.999.999.999",
        "ipv6": "not-an-ipv6-address",
    }
    return examples.get(schema_format or "")


def _enum_invalid_value(values) -> str:
    candidates = ("__invalid_enum_value__", -999999, "", False)
    return str(next((candidate for candidate in candidates if candidate not in values), "__invalid_enum_value__"))


def _invalid_schema_values(ep: EndpointSpec) -> List[str]:
    invalid_values = []
    for param in ep.parameters:
        if param.enum:
            invalid_values.append(f"{param.location} parameter {param.name}={_enum_invalid_value(param.enum)} (outside enum)")
        invalid = _format_invalid_value(param.schema_format)
        if invalid:
            invalid_values.append(f"{param.location} parameter {param.name}={invalid} (invalid {param.schema_format})")
    for prop in ep.request_body_properties:
        if prop.enum:
            invalid_values.append(f"request body field {prop.name}={_enum_invalid_value(prop.enum)} (outside enum)")
        invalid = _format_invalid_value(prop.schema_format)
        if invalid:
            invalid_values.append(f"request body field {prop.name}={invalid} (invalid {prop.schema_format})")
    return invalid_values


def _negative_constraint_case(ep: EndpointSpec, invalid_values: List[str], n: int, citation: str) -> TestCase:
    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — invalid enum and format values are rejected",
        type="negative",
        priority="medium",
        preconditions=(
            ["Valid API credentials are available"] if ep.requires_auth else ["API is reachable"]
        ),
        steps=[
            f"Send requests to {ep.method} {ep.path} using invalid constrained values: "
            + "; ".join(invalid_values),
            "Inspect the HTTP status code and error response body",
        ],
        expected_result=f"Rejects values outside the documented enum or format with {_validation_status_expectation(ep)}.",
        requirement_reference=citation,
        source_chunk=(ep.summary or f"{ep.method} {ep.path}"),
    )


def _auth_negative_case(ep: EndpointSpec, n: int, citation: str) -> TestCase:
    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — request without credentials is rejected",
        type="negative",
        priority="high",
        preconditions=["No authentication token is provided"],
        steps=[
            f"Send a {ep.method} request to {ep.path} with no Authorization header (or an expired/invalid token)",
            "Inspect the HTTP status code",
        ],
        expected_result="Returns 401 Unauthorized (or 403 Forbidden if the token is valid but insufficiently privileged).",
        requirement_reference=citation,
        source_chunk=(ep.summary or f"{ep.method} {ep.path}"),
    )
