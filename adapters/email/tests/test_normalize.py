# adapters/email/tests/test_normalize.py
from pathlib import Path
from adapters.email.normalize import parse_mime_bytes, ParsedEmail

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_simple_email():
    raw = (FIXTURES / "inbound_simple.eml").read_bytes()
    p: ParsedEmail = parse_mime_bytes(raw)
    assert p.from_address == "alice@example.com"
    assert p.from_display_name == "Alice"
    assert p.to_addresses == ["bot@agentcomms.dev"]
    assert p.subject == "March invoice"
    assert p.message_id_header == "<abc123@example.com>"
    assert p.in_reply_to is None
    assert "Hi bot" in p.body_text
    assert p.attachments == []


def test_parse_reply_extracts_threading_headers_and_strips_quote():
    raw = (FIXTURES / "inbound_gmail_reply.eml").read_bytes()
    p = parse_mime_bytes(raw)
    assert p.in_reply_to == "<abc123@example.com>"
    assert p.references == ["<abc123@example.com>"]
    # Quoted original should be removed from body_text
    assert "Thanks for the invoice." in p.body_text
    assert "Here is the invoice" not in p.body_text
    assert "bot@agentcomms.dev wrote" not in p.body_text


def test_parse_invalid_bytes_raises_valueerror():
    import pytest
    with pytest.raises(ValueError):
        parse_mime_bytes(b"")
