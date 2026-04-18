# adapters/sms/normalize.py
"""
Parse AWS End User Messaging inbound SMS SNS events into a normalized
intermediate form. This mirrors what adapters/email/normalize.py does
for MIME emails.

The raw SNS Message body (JSON string) has the shape:
    {
      "originationNumber":       "+14155551234",
      "destinationNumber":       "+18005550000",
      "messageBody":             "Your code is 482917",
      "messageId":               "abc123",
      "inboundMessageId":        "def456",
      "previousPublishedMessageId": null,
      "messageKeyword":          "KEYWORD",
      "messageSegmentCount":     1,
      "originationCountryIso":   "US",
      "carrierCode":             "310410",
      "timestamp":               "2026-04-17T12:00:00.000Z",
    }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ParsedSms:
    """Normalized intermediate representation of one inbound SMS."""
    from_number: str          # E.164 origination number
    to_number: str            # E.164 destination (our phone)
    body: str
    message_id: str           # inboundMessageId, falls back to messageId
    message_segments: int = 1
    carrier_id: str = ""
    country: str = ""


def parse_sns_record(record: dict) -> ParsedSms:
    """Parse one SNS Records[] entry → ParsedSms.

    Handles both the raw Lambda event record and a pre-decoded SNS payload dict.
    """
    # If passed a raw SNS Records[] entry, unwrap the Sns.Message string
    if "Sns" in record:
        raw = record["Sns"].get("Message", "{}")
        payload = json.loads(raw) if isinstance(raw, str) else raw
    else:
        # Already the inner payload dict
        payload = record

    from_number = payload.get("originationNumber") or payload.get("from", "")
    to_number = payload.get("destinationNumber") or payload.get("to", "")
    body = payload.get("messageBody") or payload.get("body", "")
    message_id = (
        payload.get("inboundMessageId")
        or payload.get("messageId")
        or ""
    )
    message_segments = int(payload.get("messageSegmentCount") or 1)
    carrier_id = payload.get("carrierCode") or ""
    country = payload.get("originationCountryIso") or ""

    return ParsedSms(
        from_number=from_number,
        to_number=to_number,
        body=body,
        message_id=message_id,
        message_segments=message_segments,
        carrier_id=carrier_id,
        country=country,
    )


def parse_sns_event(event: dict) -> list[ParsedSms]:
    """Parse a full Lambda SNS event (with Records[]) → list of ParsedSms."""
    results = []
    for record in event.get("Records", []):
        parsed = parse_sns_record(record)
        results.append(parsed)
    return results
