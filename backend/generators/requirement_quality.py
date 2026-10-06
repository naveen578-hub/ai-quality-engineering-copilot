"""
Deterministic requirement testability check, run *before* generation.
Heuristic only: it flags wording that usually produces vague tests; it does
not judge business correctness.
"""
from __future__ import annotations

import re
from typing import List

from pydantic import BaseModel

VAGUE_TERMS = [
    "fast", "quick", "quickly", "slow", "user-friendly", "user friendly", "easy",
    "intuitive", "appropriate", "adequate", "reasonable", "robust", "flexible",
    "efficient", "seamless", "modern", "etc", "and so on", "as needed",
    "if necessary", "where possible", "should be able", "as soon as possible",
    "minimal", "maximum", "optimal", "good", "better", "secure",
]


class QualityFinding(BaseModel):
    severity: str  # "high" | "medium" | "low"
    code: str
    message: str
    excerpt: str = ""


class RequirementQualityResponse(BaseModel):
    score: int
    verdict: str
    findings: List[QualityFinding]


class RequirementQualityRequest(BaseModel):
    requirement_text: str


def analyze_requirement_quality(text: str) -> RequirementQualityResponse:
    findings: List[QualityFinding] = []
    lowered = text.lower()

    for term in VAGUE_TERMS:
        m = re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lowered)
        if m:
            findings.append(QualityFinding(
                severity="medium", code="VAGUE_TERM",
                message=f'"{term}" is not measurable. Replace with a number, limit, or observable behaviour.',
                excerpt=text[max(0, m.start() - 20): m.end() + 20].strip(),
            ))

    if not re.search(r"\b(shall|must|will|should)\b", lowered):
        findings.append(QualityFinding(
            severity="medium", code="NO_MODAL",
            message='No "shall/must/will" statement found; obligation is unclear.',
        ))
    if not re.search(r"\d", text):
        findings.append(QualityFinding(
            severity="low", code="NO_NUMBERS",
            message="No numbers or limits; boundary-value tests cannot be derived.",
        ))
    if not re.search(r"\b(error|invalid|denied|reject|fail|unauthori[sz]ed|not allowed|otherwise|timeout)\b", lowered):
        findings.append(QualityFinding(
            severity="medium", code="NO_NEGATIVE_PATH",
            message="No failure or denial behaviour described; negative tests will be guesses.",
        ))
    if not re.search(r"\b(user|admin|system|customer|operator|api|service|member|role)\b", lowered):
        findings.append(QualityFinding(
            severity="low", code="NO_ACTOR",
            message="No actor identified (who performs or receives this).",
        ))
    if len(re.findall(r"\b(and|or)\b", lowered)) >= 4 or len(re.split(r"[.;]\s", text.strip())) > 5:
        findings.append(QualityFinding(
            severity="low", code="COMPOUND",
            message="Requirement looks compound; split into single testable statements.",
        ))
    if len(text.split()) < 6:
        findings.append(QualityFinding(
            severity="high", code="TOO_SHORT",
            message="Too short to derive meaningful test cases.",
        ))

    weights = {"high": 30, "medium": 12, "low": 6}
    score = max(0, 100 - sum(weights[f.severity] for f in findings))
    verdict = "good" if score >= 80 else "needs work" if score >= 50 else "poor"
    return RequirementQualityResponse(score=score, verdict=verdict, findings=findings)
