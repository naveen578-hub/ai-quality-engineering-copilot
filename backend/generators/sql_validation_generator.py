"""
Generates SQL queries that check whether stored data complies with a
requirement's stated constraint (e.g. "member ID must be 8-12 characters"
-> a query that finds rows violating that length).

Mock mode is pattern-based, not a language model: it looks for a handful of
common requirement phrasings (length ranges, required/non-null fields,
uniqueness, enumerated values, numeric thresholds) and only emits SQL when
it's confident it matched one. It deliberately does NOT try to guess at
SQL for phrasing it doesn't recognize — an incorrect validation query is
worse than no query, since someone might actually run it. LLM mode can
handle a wider range of phrasing, but is still asked to flag anything it's
not confident about rather than fabricate a plausible-looking query.
"""
from __future__ import annotations

import json
import re
from typing import List

from pydantic import ValidationError

from backend.generators.llm_client import call_llm_for_json, is_configured
from backend.models.schemas import SqlValidation, SqlValidationRequest, SqlValidationResponse
from backend.observability.usage import track_mock_call

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")

SYSTEM_PROMPT = """You are a QA engineer writing SQL data-validation queries: queries that find
rows in a database which VIOLATE a stated requirement (so a non-empty result means a bug).

Return ONLY a JSON object, no prose, no markdown fences:

{
  "validations": [
    {"description": "string", "sql": "string", "rule_detected": "string"}
  ]
}

Rules:
- Only include a validation if you are reasonably confident the requirement states a concrete,
  checkable data constraint (length, required/non-null, uniqueness, allowed values, numeric
  range or threshold, format).
- If the requirement doesn't state a concrete checkable constraint, return {"validations": []}.
- Use standard ANSI SQL and the given table name. Never invent a placeholder table name.
- Every query must be a SELECT that finds VIOLATING rows, never a query that finds compliant rows.
- Never invent column names you weren't given or couldn't reasonably infer from the requirement text.
"""


class SqlGenerationError(RuntimeError):
    pass


def generate_sql_validations(request: SqlValidationRequest) -> SqlValidationResponse:
    if not request.table_name:
        return SqlValidationResponse(
            validations=[],
            unmatched_note="Enter the actual database table name before generating SQL; no placeholder table is used.",
        )
    if is_configured():
        return _generate_with_llm(request)
    with track_mock_call("sql-validations/generate"):
        return _generate_with_patterns(request)


def _generate_with_llm(request: SqlValidationRequest) -> SqlValidationResponse:
    table = request.table_name
    user_prompt = (
        f"Requirement: {request.requirement_text}\n"
        f"Table name to use: {table}\n"
    )
    try:
        raw = call_llm_for_json(SYSTEM_PROMPT, user_prompt, endpoint="sql-validations/generate")
        validations = [
            SqlValidation(
                description=v["description"],
                sql=v["sql"],
                rule_detected=v.get("rule_detected", "llm_detected"),
                requirement_reference=request.requirement_id,
            )
            for v in raw.get("validations", [])
        ]
    except (ValidationError, KeyError, json.JSONDecodeError) as exc:
        raise SqlGenerationError(f"LLM returned a response that didn't match the expected shape: {exc}") from exc

    note = None if validations else "No concrete, checkable data constraint was recognized in this requirement."
    return SqlValidationResponse(validations=validations, unmatched_note=note)


# ---- Mock mode: pattern matching ----

_LENGTH_RANGE_RE = re.compile(r"between\s+(\d+)\s+and\s+(\d+)\s+characters", re.IGNORECASE)
_MIN_LENGTH_RE = re.compile(r"(?:at least|minimum of?)\s+(\d+)\s+characters", re.IGNORECASE)
_UNIQUE_RE = re.compile(r"\b(unique|must not be duplicated|no duplicates?)\b", re.IGNORECASE)
_REQUIRED_RE = re.compile(
    r"\b(shall not be empty|is required|must not be null|cannot be blank|must be present|shall be present)\b",
    re.IGNORECASE,
)
_ENUM_RE = re.compile(r"\bshall be one of\s*[:\-]?\s*(.+?)(?:\.|$)", re.IGNORECASE)
_THRESHOLD_RE = re.compile(
    r"\bafter\s+(\d+)\s+(?:consecutive\s+)?([a-zA-Z ]+?)\s+(?:attempts|tries|failures)\b", re.IGNORECASE
)

_EXPLICIT_COLUMN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
_SHORT_SUBJECT_RE = re.compile(
    r"^\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)\s+(?:shall|must|is|are)\b", re.IGNORECASE
)


def _columns_for_request(request: SqlValidationRequest) -> List[str]:
    if request.column_name:
        candidates = [part.strip() for part in request.column_name.split(",") if part.strip()]
    else:
        candidates = _EXPLICIT_COLUMN_RE.findall(request.requirement_text)
        if not candidates:
            subject_match = _SHORT_SUBJECT_RE.search(request.requirement_text)
            if subject_match:
                candidates = [re.sub(r"[^a-zA-Z0-9]+", "_", subject_match.group(1)).strip("_").lower()]

    columns: List[str] = []
    for candidate in candidates:
        if _IDENTIFIER_RE.fullmatch(candidate) and candidate not in columns:
            columns.append(candidate)
    return columns


def _columns_for_constraint(request: SqlValidationRequest, constraint: re.Pattern[str]) -> List[str]:
    """Return explicit fields from the clause that states this constraint."""
    explicit_request_columns = _columns_for_request(request)
    clauses = re.split(r"[.;\n]+", request.requirement_text)
    matched_columns: List[str] = []
    for clause in clauses:
        if constraint.search(clause):
            for column in _EXPLICIT_COLUMN_RE.findall(clause):
                if column in explicit_request_columns and column not in matched_columns:
                    matched_columns.append(column)

    if matched_columns:
        return matched_columns
    if request.column_name and constraint.search(request.requirement_text):
        return explicit_request_columns
    return []


def _generate_with_patterns(request: SqlValidationRequest) -> SqlValidationResponse:
    text = request.requirement_text
    table = request.table_name
    columns = _columns_for_request(request)
    validations: List[SqlValidation] = []

    if not _TABLE_RE.fullmatch(table):
        return SqlValidationResponse(
            validations=[],
            unmatched_note="The table name must be a SQL identifier such as 'clearance_cases'.",
        )

    if not columns:
        return SqlValidationResponse(
            validations=[],
            unmatched_note=(
                "A validation pattern was recognized, but no explicit column name was provided. "
                "Provide column_name (for example, 'case_id, common_intake_id') or include "
                "snake_case field names in the requirement."
            ),
        )

    column = columns[0]

    if m := _LENGTH_RANGE_RE.search(text):
        low, high = m.group(1), m.group(2)
        validations.append(
            SqlValidation(
                description=f"Finds rows where {column} length falls outside the required {low}-{high} character range.",
                sql=(
                    f"-- Column name is a heuristic guess ('{column}'); verify against the real schema.\n"
                    f"SELECT * FROM {table}\n"
                    f"WHERE LENGTH({column}) NOT BETWEEN {low} AND {high};"
                ),
                rule_detected="length_range",
                requirement_reference=request.requirement_id,
            )
        )

    if m := _MIN_LENGTH_RE.search(text):
        minimum = m.group(1)
        validations.append(
            SqlValidation(
                description=f"Finds rows where {column} is shorter than the required minimum of {minimum} characters.",
                sql=(
                    f"-- Column name is a heuristic guess ('{column}'); verify against the real schema.\n"
                    f"SELECT * FROM {table}\n"
                    f"WHERE LENGTH({column}) < {minimum};"
                ),
                rule_detected="minimum_length",
                requirement_reference=request.requirement_id,
            )
        )

    if _UNIQUE_RE.search(text):
        unique_columns = _columns_for_constraint(request, _UNIQUE_RE)
        if not unique_columns and len(columns) == 1:
            unique_columns = columns
        for column in unique_columns:
            validations.append(
                SqlValidation(
                    description=f"Finds duplicate values of {column}, which should be unique.",
                    sql=(
                        f"SELECT {column}, COUNT(*) AS occurrences\n"
                        f"FROM {table}\n"
                        f"WHERE {column} IS NOT NULL\n"
                        f"GROUP BY {column}\n"
                        f"HAVING COUNT(*) > 1;"
                    ),
                    rule_detected="uniqueness",
                    requirement_reference=request.requirement_id,
                )
            )

    if _REQUIRED_RE.search(text):
        required_columns = _columns_for_constraint(request, _REQUIRED_RE)
        if not required_columns and len(columns) == 1:
            required_columns = columns
        for column in required_columns:
            validations.append(
                SqlValidation(
                    description=f"Finds rows where {column} is null or blank, though the requirement says it's required.",
                    sql=(
                        f"SELECT * FROM {table}\n"
                        f"WHERE {column} IS NULL OR TRIM({column}) = '';"
                    ),
                    rule_detected="required_not_null",
                    requirement_reference=request.requirement_id,
                )
            )

    if m := _ENUM_RE.search(text):
        raw_values = re.split(r",|\bor\b", m.group(1))
        values = [v.strip().strip("'\"") for v in raw_values if v.strip()]
        if values:
            in_clause = ", ".join(f"'{v}'" for v in values)
            validations.append(
                SqlValidation(
                    description=f"Finds rows where {column} is set to a value outside the allowed list ({', '.join(values)}).",
                    sql=(
                        f"-- Column name is a heuristic guess ('{column}'); verify against the real schema.\n"
                        f"SELECT * FROM {table}\n"
                        f"WHERE {column} NOT IN ({in_clause});"
                    ),
                    rule_detected="allowed_values",
                    requirement_reference=request.requirement_id,
                )
            )

    if m := _THRESHOLD_RE.search(text):
        count, subject = m.group(1), m.group(2).strip().lower()
        subject_column = re.sub(r"[^a-z0-9]+", "_", subject).strip("_") or "event"
        validations.append(
            SqlValidation(
                description=(
                    f"Finds accounts/records with {count} or more consecutive '{subject}' events, "
                    "which the requirement says should trigger a threshold action (e.g. lockout)."
                ),
                sql=(
                    f"-- This assumes an event-log table; adapt table/column names to your real schema.\n"
                    f"SELECT account_id, COUNT(*) AS {subject_column}_count\n"
                    f"FROM {subject_column}_log\n"
                    f"GROUP BY account_id\n"
                    f"HAVING COUNT(*) >= {count};"
                ),
                rule_detected="event_threshold",
                requirement_reference=request.requirement_id,
            )
        )

    note = None
    if not validations:
        note = (
            "No recognized data-validation pattern (length, uniqueness, required/not-null, "
            "allowed values, or event threshold) was found in this requirement's text."
        )

    return SqlValidationResponse(validations=validations, unmatched_note=note)
