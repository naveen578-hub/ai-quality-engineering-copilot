"""
Builds the requirements-traceability matrix: for every requirement indexed
via document upload, which test-case types exist for it (among *persisted*
test cases — generated-but-not-saved test cases don't count, since the
matrix is meant to answer "what do we actually have on record").
"""
from __future__ import annotations

from typing import Dict, List

from backend.models import db
from backend.models.schemas import TestCaseStatus, TestCaseType, TraceabilityMatrix, TraceabilityRow
from backend.rag import store

ALL_TYPES: List[TestCaseType] = [
    TestCaseType.positive,
    TestCaseType.negative,
    TestCaseType.boundary,
    TestCaseType.api,
    TestCaseType.regression,
]


def build_traceability_matrix() -> TraceabilityMatrix:
    documents = store.list_documents()

    # requirement_id -> source_filename, for every requirement seen across all uploads
    requirement_sources: Dict[str, str] = {}
    for doc in documents:
        for req_id in doc["requirement_ids"]:
            requirement_sources.setdefault(req_id, doc["filename"])

    persisted = db.list_test_cases()

    rows: List[TraceabilityRow] = []
    for req_id, filename in sorted(requirement_sources.items()):
        matching = [tc for tc in persisted if tc.requirement_reference == req_id]
        covered_types = sorted({tc.type for tc in matching}, key=lambda t: t.value)
        missing_types = [t for t in ALL_TYPES if t not in covered_types]
        approved_count = sum(1 for tc in matching if tc.status == TestCaseStatus.approved)

        rows.append(
            TraceabilityRow(
                requirement_id=req_id,
                source_filename=filename,
                covered_types=covered_types,
                missing_types=missing_types,
                test_case_count=len(matching),
                approved_count=approved_count,
            )
        )

    # Also surface requirements that only ever appeared via direct (non-RAG) generation,
    # i.e. have persisted test cases but were never uploaded as a document.
    seen_ids = set(requirement_sources.keys())
    direct_only_ids = sorted({tc.requirement_reference for tc in persisted if tc.requirement_reference not in seen_ids})
    for req_id in direct_only_ids:
        matching = [tc for tc in persisted if tc.requirement_reference == req_id]
        covered_types = sorted({tc.type for tc in matching}, key=lambda t: t.value)
        missing_types = [t for t in ALL_TYPES if t not in covered_types]
        approved_count = sum(1 for tc in matching if tc.status == TestCaseStatus.approved)
        rows.append(
            TraceabilityRow(
                requirement_id=req_id,
                source_filename=None,
                covered_types=covered_types,
                missing_types=missing_types,
                test_case_count=len(matching),
                approved_count=approved_count,
            )
        )

    covered_rows = sum(1 for r in rows if r.test_case_count > 0)
    coverage_percent = round((covered_rows / len(rows)) * 100, 1) if rows else 0.0

    return TraceabilityMatrix(rows=rows, coverage_percent=coverage_percent)
