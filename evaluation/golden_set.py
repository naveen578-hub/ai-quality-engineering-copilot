"""
Golden set for evaluating retrieval quality: (query, expected_requirement_id)
pairs against sample-data/sample_requirement.txt.

Includes both close-vocabulary queries (share words with the target
requirement) and paraphrased queries (deliberately reworded, no shared
distinctive terms) — the paraphrased ones are the harder, more realistic
case, and also the ones where mock mode's hashed bag-of-words embedding is
expected to struggle relative to a real semantic embedding. That gap is the
point: it's what this harness is for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class GoldenQuery:
    query: str
    expected_requirement_id: str
    note: str = ""


GOLDEN_SET: List[GoldenQuery] = [
    GoldenQuery(
        query="authorized user with FEP access viewing a patient record",
        expected_requirement_id="REQ-001",
        note="close vocabulary",
    ),
    GoldenQuery(
        query="searching for a patient by member ID",
        expected_requirement_id="REQ-001",
        note="close vocabulary",
    ),
    GoldenQuery(
        query="what happens when someone without FEP access tries to look up a record",
        expected_requirement_id="REQ-002",
        note="paraphrased",
    ),
    GoldenQuery(
        query="generic access denied error that doesn't leak whether the ID exists",
        expected_requirement_id="REQ-002",
        note="close vocabulary",
    ),
    GoldenQuery(
        query="valid length range for a member ID during search",
        expected_requirement_id="REQ-003",
        note="close vocabulary",
    ),
    GoldenQuery(
        query="rejecting a search input before any database lookup happens",
        expected_requirement_id="REQ-003",
        note="paraphrased",
    ),
]
