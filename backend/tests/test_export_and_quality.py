from backend.generators.export import to_gherkin, to_playwright
from backend.generators.requirement_quality import analyze_requirement_quality
from backend.models.schemas import PersistedTestCase


def _tc() -> PersistedTestCase:
    return PersistedTestCase(
        db_id=1,
        id="TC-001",
        title='Login "ok"',
        type="positive",
        priority="high",
        preconditions=["User exists"],
        steps=["Open login", "Submit form"],
        expected_result="Dashboard shown",
        requirement_reference="REQ-001",
        source_chunk="x",
        status="approved",
        document_id=None,
        created_at="2024-01-01",
        updated_at="2024-01-01",
    )


def test_gherkin_structure():
    out = to_gherkin([_tc()])
    assert "Scenario: TC-001" in out
    assert "Given User exists" in out
    assert "When Open login" in out
    assert "And Submit form" in out
    assert "Then Dashboard shown" in out
    assert "@REQ_001" in out


def test_playwright_escapes_and_steps():
    out = to_playwright([_tc()])
    assert "from '@playwright/test'" in out
    assert '\\"ok\\"' in out
    assert out.count("test.step(") == 2


def test_quality_flags_vague_requirement():
    r = analyze_requirement_quality("The system should be fast and user-friendly")
    codes = {f.code for f in r.findings}
    assert "VAGUE_TERM" in codes and "NO_NEGATIVE_PATH" in codes
    assert r.verdict != "good"


def test_quality_accepts_precise_requirement():
    r = analyze_requirement_quality(
        "The system shall lock a user account after 5 failed login attempts "
        "and shall reject further logins with an error until an admin unlocks it."
    )
    assert r.score >= 80
