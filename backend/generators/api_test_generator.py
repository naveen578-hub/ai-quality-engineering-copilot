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

        if ep.parameters or ep.request_body_required:
            test_cases.append(_negative_missing_required_case(ep, counter, citation))
            counter += 1

        bounded_params = [p for p in ep.parameters if p.minimum is not None or p.maximum is not None]
        if bounded_params:
            test_cases.append(_boundary_case(ep, bounded_params, counter, citation))
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
    required_names = [p.name for p in ep.parameters if p.required]
    subject = ", ".join(required_names) if required_names else "the request body"

    steps = [
        f"Send a {ep.method} request to {ep.path} omitting a required field ({subject})",
        "Inspect the HTTP status code and error response body",
    ]
    expected_code = ep.error_status_codes[0] if ep.error_status_codes else "400"

    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — missing required field is rejected",
        type="negative",
        priority="high",
        preconditions=(["Valid API credentials are available"] if ep.requires_auth else ["API is reachable"]),
        steps=steps,
        expected_result=f"Returns {expected_code} with a clear validation error identifying the missing field.",
        requirement_reference=citation,
        source_chunk=(ep.summary or f"{ep.method} {ep.path}"),
    )


def _boundary_case(ep: EndpointSpec, bounded_params, n: int, citation: str) -> TestCase:
    boundary_desc = "; ".join(
        f"{p.name} at {p.minimum if p.minimum is not None else '?'}/{p.maximum if p.maximum is not None else '?'} "
        "(min/max) and one unit outside each"
        for p in bounded_params
    )

    return TestCase(
        id=f"TC-API-{n:03d}",
        title=f"{ep.method} {ep.path} — boundary values for constrained parameters",
        type="boundary",
        priority="medium",
        preconditions=(["Valid API credentials are available"] if ep.requires_auth else ["API is reachable"]),
        steps=[
            f"Send requests to {ep.method} {ep.path} with: {boundary_desc}",
            "Inspect the HTTP status code and response for each value",
        ],
        expected_result="Values within the documented min/max are accepted; values outside are rejected with a validation error.",
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
