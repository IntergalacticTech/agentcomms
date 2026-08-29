# adapters/sms/tests/test_normalize.py
"""Tests for SMS SNS payload normalization."""
import json
from pathlib import Path

import pytest

from adapters.sms.normalize import ParsedSms, parse_sns_event, parse_sns_record

FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture() -> dict:
    return json.loads((FIXTURES / "inbound_sns.json").read_text())


def test_parse_sns_event_roundtrip():
    """parse_sns_event returns one ParsedSms with correct fields."""
    event = _load_fixture()
    results = parse_sns_event(event)
    assert len(results) == 1
    sms = results[0]
    assert isinstance(sms, ParsedSms)
    assert sms.from_number == "+14155551234"
    assert sms.to_number == "+18005550000"
    assert sms.body == "Your code is 482917"
    assert sms.message_id == "def456"   # inboundMessageId takes priority
    assert sms.message_segments == 1
    assert sms.country == "US"
    assert sms.carrier_id == "310410"


def test_parse_sns_record_inner_payload():
    """parse_sns_record accepts the already-unwrapped inner SMS dict."""
    payload = {
        "originationNumber": "+12125550001",
        "destinationNumber": "+18005550002",
        "messageBody": "Hello world",
        "messageId": "msg-abc",
        "inboundMessageId": "inb-xyz",
        "messageSegmentCount": 2,
        "originationCountryIso": "US",
        "carrierCode": "310260",
    }
    sms = parse_sns_record(payload)
    assert sms.from_number == "+12125550001"
    assert sms.to_number == "+18005550002"
    assert sms.body == "Hello world"
    assert sms.message_id == "inb-xyz"
    assert sms.message_segments == 2
    assert sms.carrier_id == "310260"


def test_parse_sns_record_missing_inbound_id_falls_back_to_message_id():
    """If inboundMessageId is absent, falls back to messageId."""
    payload = {
        "originationNumber": "+14155550003",
        "destinationNumber": "+18005550004",
        "messageBody": "Hi",
        "messageId": "only-message-id",
    }
    sms = parse_sns_record(payload)
    assert sms.message_id == "only-message-id"
