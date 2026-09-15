"""
Exports persisted test cases as CSV or JSON. The frontend already offers a
client-side CSV export for whatever's currently on screen (Phase 1); this is
the server-side counterpart for the *saved/approved* library, so someone can
pull the whole persisted set — filtered by status if they want — as a file,
including via `curl` or CI, not just from the browser session that generated it.
"""
from __future__ import annotations

import csv
import io
import json
from typing import List

from backend.models.schemas import PersistedTestCase

CSV_FIELDS = [
    "db_id",
    "id",
    "title",
    "type",
    "priority",
    "status",
    "preconditions",
    "steps",
    "expected_result",
    "requirement_reference",
    "source_chunk",
    "document_id",
    "created_at",
    "updated_at",
]


def to_csv(test_cases: List[PersistedTestCase]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS)
    writer.writeheader()
    for tc in test_cases:
        row = tc.model_dump()
        row["preconditions"] = " | ".join(row["preconditions"])
        row["steps"] = " | ".join(row["steps"])
        writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})
    return buffer.getvalue()


def to_json(test_cases: List[PersistedTestCase]) -> str:
    return json.dumps({"test_cases": [tc.model_dump() for tc in test_cases]}, indent=2, default=str)
