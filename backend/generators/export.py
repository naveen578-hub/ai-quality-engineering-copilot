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
import re
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


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def to_gherkin(test_cases: List[PersistedTestCase]) -> str:
    """BDD feature file. Preconditions -> Given, steps -> When/And,
    expected result -> Then. Type, priority and requirement become tags."""
    lines = ["Feature: Generated test cases", ""]
    for tc in test_cases:
        tags = [f"@{tc.type}", f"@{tc.priority}"]
        if tc.requirement_reference:
            tags.append("@" + re.sub(r"\W+", "_", tc.requirement_reference).strip("_"))
        lines.append("  " + " ".join(tags))
        lines.append(f"  Scenario: {tc.id} {_one_line(tc.title)}")
        for i, pre in enumerate(tc.preconditions):
            lines.append(f"    {'Given' if i == 0 else 'And'} {_one_line(pre)}")
        for i, step in enumerate(tc.steps):
            lines.append(f"    {'When' if i == 0 else 'And'} {_one_line(step)}")
        lines.append(f"    Then {_one_line(tc.expected_result)}")
        lines.append("")
    return "\n".join(lines)


def _js_str(text: str) -> str:
    return json.dumps(_one_line(text))


def to_playwright(test_cases: List[PersistedTestCase]) -> str:
    """Playwright Test skeleton: one test per case, each step a test.step with
    a TODO. Not runnable as-is by design."""
    out = ["import { test, expect } from '@playwright/test';", ""]
    for tc in test_cases:
        out.append(f"test({_js_str(tc.id + ' ' + tc.title)}, async ({{ page }}) => {{")
        out.append(f"  // Requirement: {_one_line(tc.requirement_reference or 'n/a')} | Priority: {tc.priority}")
        for pre in tc.preconditions:
            out.append(f"  // Precondition: {_one_line(pre)}")
        for step in tc.steps:
            out.append(f"  await test.step({_js_str(step)}, async () => {{")
            out.append("    // TODO: implement")
            out.append("  });")
        out.append(f"  // Expected: {_one_line(tc.expected_result)}")
        out.append("  // TODO: expect(...) assertion")
        out.append("});")
        out.append("")
    return "\n".join(out)
