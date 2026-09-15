from backend.guardrails.pii import has_pii, scan_and_mask


def test_masks_ssn():
    text = "Patient SSN is 123-45-6789 on file."
    masked, counts = scan_and_mask(text)
    assert "123-45-6789" not in masked
    assert "[REDACTED-SSN]" in masked
    assert counts == {"ssn": 1}


def test_masks_email():
    text = "Contact the requester at jane.doe@example.com for details."
    masked, counts = scan_and_mask(text)
    assert "jane.doe@example.com" not in masked
    assert "[REDACTED-EMAIL]" in masked
    assert counts == {"email": 1}


def test_masks_phone():
    text = "Call the help desk at 555-123-4567 if this fails."
    masked, counts = scan_and_mask(text)
    assert "555-123-4567" not in masked
    assert "[REDACTED-PHONE]" in masked
    assert counts == {"phone": 1}


def test_masks_credit_card():
    text = "Card on file: 4111 1111 1111 1111 expires soon."
    masked, counts = scan_and_mask(text)
    assert "4111 1111 1111 1111" not in masked
    assert "[REDACTED-CARD]" in masked
    assert counts == {"credit_card": 1}


def test_masks_multiple_categories_in_one_pass():
    text = "SSN 123-45-6789, email admin@example.com, phone 555-123-4567."
    masked, counts = scan_and_mask(text)
    assert counts == {"ssn": 1, "phone": 1, "email": 1}
    assert "123-45-6789" not in masked
    assert "admin@example.com" not in masked
    assert "555-123-4567" not in masked


def test_leaves_ordinary_requirement_text_untouched():
    """The whole point of pattern-based (not fuzzy) detection: realistic
    synthetic requirement text should never trigger a false positive."""
    text = (
        "Member ID search shall accept alphanumeric IDs between 8 and 12 "
        "characters. IDs outside this length shall be rejected."
    )
    masked, counts = scan_and_mask(text)
    assert masked == text
    assert counts == {}
    assert has_pii(text) is False


def test_has_pii_detects_without_masking():
    assert has_pii("Email me at test@example.com") is True
    assert has_pii("Member ID shall be 8-12 characters") is False
