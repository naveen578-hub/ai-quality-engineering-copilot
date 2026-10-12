"""Conservative failure triage using signatures verified against input evidence.

Recognized signatures: NoSuchElementException and ElementNotInteractableException
map to automation; connection-refused, timeout, and explicit HTTP 5xx signatures
map to environment; expected/actual business-value mismatches map to product
defect; and NullPointerException on a caller-designated known flaky field maps to
test data. Anything else is returned as unclassified rather than guessed.
"""
from __future__ import annotations

import re
from typing import Optional

from backend.models.schemas import FailureTriageRecord, TriageClassification


_ENVIRONMENT_RE = re.compile(
    r"connection\s*refused|connectionrefused|connectexception|\btime(?:d\s*out|out)\b|"
    r"\bHTTP\s+5\d\d\b|\b(?:status(?:_code)?|response)\D{0,12}5\d\d\b",
    re.IGNORECASE,
)
_AUTOMATION_RE = re.compile(r"NoSuchElementException|ElementNotInteractableException", re.IGNORECASE)
_NULL_POINTER_RE = re.compile(r"NullPointerException", re.IGNORECASE)
_MISMATCH_PATTERNS = (
    re.compile(
        r"expected\s*[:=]\s*(?P<expected>[^,;\n]+?)\s*[,;]\s*actual\s*[:=]\s*(?P<actual>[^\n;]+)",
        re.IGNORECASE,
    ),
    re.compile(r"expected\s*:\s*(?P<expected>.+?)\s+but\s+was\s*:\s*(?P<actual>.+)", re.IGNORECASE),
    re.compile(
        r"expected\s+['\"](?P<expected>[^'\"]+)['\"]\s+but\s+(?:was|got)\s+['\"](?P<actual>[^'\"]+)['\"]",
        re.IGNORECASE,
    ),
    re.compile(r"expected\s+(?P<expected>\S+)\s+but\s+(?:was|got)\s+(?P<actual>\S+)", re.IGNORECASE),
)
_NON_BUSINESS_VALUES = re.compile(
    r"\b(?:exception|null|nullpointer|none|undefined|timeout|connection|traceback|error)\b",
    re.IGNORECASE,
)


def _lines(record: FailureTriageRecord) -> list[str]:
    sources = (record.stack_trace or "", record.error_message or "", record.failed_assertion)
    return [line for source in sources for line in source.splitlines() if line.strip()]


def _result(
    classification: TriageClassification,
    confidence: float,
    justification: str,
    evidence: Optional[str],
) -> dict:
    return {
        "classification": classification,
        "confidence": confidence,
        "justification": justification,
        "evidence_snippet": evidence,
    }


def classify_failure(record: FailureTriageRecord) -> dict:
    """Classify only when a recognized signature can be quoted from the input."""
    lines = _lines(record)
    candidates = []

    for line in lines:
        if _ENVIRONMENT_RE.search(line):
            candidates.append(_result(
                TriageClassification.environment_failure,
                0.94,
                "Environment signature matched the quoted connection, timeout, or HTTP 5xx line.",
                line,
            ))

    for line in lines:
        if _AUTOMATION_RE.search(line):
            candidates.append(_result(
                TriageClassification.automation_issue,
                0.94,
                "Automation exception matched the quoted stack-trace line.",
                line,
            ))

    known_fields = [field.casefold() for field in record.known_flaky_fields if field.strip()]
    if known_fields:
        for line in lines:
            has_known_field = any(
                re.search(rf"(?<![A-Za-z0-9_$]){re.escape(field)}(?![A-Za-z0-9_$])", line, re.IGNORECASE)
                for field in known_fields
            )
            if _NULL_POINTER_RE.search(line) and has_known_field:
                candidates.append(_result(
                    TriageClassification.test_data_problem,
                    0.86,
                    "NullPointerException names a caller-designated known flaky field on the quoted line.",
                    line,
                ))

    assertion_lines = [line for line in record.failed_assertion.splitlines() if line.strip()]
    for line in assertion_lines:
        for pattern in _MISMATCH_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            expected = match.group("expected").strip().strip("'\"")
            actual = match.group("actual").strip().strip("'\"")
            if (
                expected
                and actual
                and expected.casefold() != actual.casefold()
                and not _NON_BUSINESS_VALUES.search(expected)
                and not _NON_BUSINESS_VALUES.search(actual)
            ):
                candidates.append(_result(
                    TriageClassification.product_defect,
                    0.82,
                    "Assertion line reports different expected and actual business values.",
                    line,
                ))
                break

    classifications = {candidate["classification"] for candidate in candidates}
    if len(classifications) == 1:
        return candidates[0]

    return _result(
        TriageClassification.unclassified,
        0.0,
        "No recognized failure signature matched the supplied assertion or error text.",
        None,
    )