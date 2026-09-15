"""
Detects and masks PII-shaped content before it's embedded, stored, sent to
an LLM, or persisted anywhere. This is a QA/requirements tool for a
healthcare-adjacent domain, so even though the shipped sample data is
entirely synthetic, real deployments will have real requirement documents
pasted in — this guardrail means a raw SSN or credit-card number typed into
a requirement box doesn't silently end up in the vector store, an LLM
provider's logs, or an exported CSV.

Deliberately pattern-based rather than an ML PII detector: precise regexes
for a handful of high-confidence, high-harm patterns (SSN, credit card,
email, phone) rather than a fuzzy classifier that would false-positive on
legitimate content like "Member ID search shall accept IDs between 8 and 12
characters" (no dashes, no @ sign, doesn't match any of these).
"""
from __future__ import annotations

import re
from typing import Dict, Tuple

_PATTERNS = {
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b"),
}

_MASKS = {
    "ssn": "[REDACTED-SSN]",
    "credit_card": "[REDACTED-CARD]",
    "email": "[REDACTED-EMAIL]",
    "phone": "[REDACTED-PHONE]",
}

# Order matters: SSN and phone are more specific than the generic digit-run
# credit-card pattern, so check them first to avoid a phone number like
# "555-123-4567" being partially eaten by the credit-card regex first.
_ORDER = ["ssn", "phone", "credit_card", "email"]


def scan_and_mask(text: str) -> Tuple[str, Dict[str, int]]:
    """
    Returns (masked_text, counts) where counts maps pattern name -> number of
    matches redacted. Safe to call on text with no PII (returns it unchanged
    with an empty counts dict).
    """
    counts: Dict[str, int] = {}
    masked = text

    for name in _ORDER:
        pattern = _PATTERNS[name]
        matches = pattern.findall(masked)
        if matches:
            counts[name] = len(matches)
            masked = pattern.sub(_MASKS[name], masked)

    return masked, counts


def has_pii(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PATTERNS.values())
