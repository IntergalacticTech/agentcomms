"""
Offline unit tests for invoicing_agent.py.
All HTTP calls are mocked — no real API key required.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest

import invoicing_agent as agent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_message(message_id: str = "msg-001", direction: str = "inbound",
                 received_at: str = "2026-04-17T09:00:00Z") -> dict:
    return {
        "id": message_id,
        "direction": direction,
        "from_addr": {"name": "Vendor Co", "address": "billing@vendor.com"},
        "subject": "Invoice INV-1001",
        "snippet": "Please find attached invoice INV-1001...",
        "received_at": received_at,
        "created_at": received_at,
    }


def make_inbox(inbox_id: str = "inbox-001") -> dict:
    return {
        "id": inbox_id,
        "display_name": "InvoiceBot",
        "email": "invoicebot@agentcomms.dev",
    }


def in_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    agent.init_db.__wrapped__(conn) if hasattr(agent.init_db, "__wrapped__") else None
    # Re-run init directly
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id            TEXT PRIMARY KEY,
            message_id    TEXT NOT NULL,
            inbox_id      TEXT NOT NULL,
            invoice_number TEXT,
            vendor        TEXT,
            amount        REAL,
            due_date      TEXT,
            received_at   TEXT NOT NULL,
            created_at    TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Test 1 — categorize + extract flow produces a DB row and reply
# ---------------------------------------------------------------------------

def test_invoice_categorize_and_extract():
    """Full happy path: invoice message is categorized, extracted, stored, replied to."""
    msg = make_message("msg-001")
    inbox = make_inbox("inbox-001")
    conn = in_memory_db()

    with patch.object(agent, "_post") as mock_post, \
         patch.object(agent, "_get"):

        def post_side_effect(path, body):
            if "/ai/categorize" in path:
                return {"message_id": "msg-001", "category": "invoice"}
            if "/ai/extract" in path:
                return {"message_id": "msg-001", "extracted": {
                    "invoice_number": "INV-1001",
                    "vendor": "Vendor Co",
                    "amount": 450.00,
                    "due_date": "2026-05-01",
                }}
            if "/reply" in path:
                return {"id": "reply-001"}
            return {}

        mock_post.side_effect = post_side_effect

        agent.process_message(msg, inbox, conn)

    # Verify DB row was inserted
    row = conn.execute("SELECT * FROM invoices WHERE message_id = 'msg-001'").fetchone()
    assert row is not None, "Invoice row should be stored in DB"
    assert row[3] == "INV-1001", "invoice_number should be extracted"
    assert row[4] == "Vendor Co", "vendor should be extracted"
    assert row[5] == 450.00, "amount should be extracted"

    # Verify reply was sent
    reply_calls = [c for c in mock_post.call_args_list if "/reply" in c.args[0]]
    assert len(reply_calls) == 1
    reply_body = reply_calls[0].args[1]["body_text"]
    assert "INV-1001" in reply_body
    assert "$450.00" in reply_body


# ---------------------------------------------------------------------------
# Test 2 — non-invoice messages are skipped (no extract, no reply, no DB row)
# ---------------------------------------------------------------------------

def test_non_invoice_skipped():
    """Messages categorized as 'other' or 'receipt' are not processed further."""
    msg = make_message("msg-002")
    inbox = make_inbox("inbox-001")
    conn = in_memory_db()

    with patch.object(agent, "_post") as mock_post:

        def post_side_effect(path, body):
            if "/ai/categorize" in path:
                return {"message_id": "msg-002", "category": "other"}
            raise AssertionError(f"Unexpected call to _post({path!r})")

        mock_post.side_effect = post_side_effect

        agent.process_message(msg, inbox, conn)

    row = conn.execute("SELECT * FROM invoices WHERE message_id = 'msg-002'").fetchone()
    assert row is None, "Non-invoice messages should not be stored"

    # Only categorize should have been called
    paths_called = [c.args[0] for c in mock_post.call_args_list]
    assert not any("/ai/extract" in p for p in paths_called)
    assert not any("/reply" in p for p in paths_called)


# ---------------------------------------------------------------------------
# Test 3 — large invoice (> $1000) fires an alert email
# ---------------------------------------------------------------------------

def test_large_invoice_sends_alert():
    """Invoices over $1,000 trigger an alert email to INVOICE_ALERT_EMAIL."""
    msg = make_message("msg-003")
    inbox = make_inbox("inbox-001")
    conn = in_memory_db()

    alert_calls = []

    with patch.object(agent, "_post") as mock_post, \
         patch.object(agent, "ALERT_EMAIL", "alerts@example.com"):

        def post_side_effect(path, body):
            if "/ai/categorize" in path:
                return {"message_id": "msg-003", "category": "invoice"}
            if "/ai/extract" in path:
                return {"message_id": "msg-003", "extracted": {
                    "invoice_number": "INV-2500",
                    "vendor": "Big Vendor Inc",
                    "amount": 2500.00,
                    "due_date": "2026-05-15",
                }}
            if "/reply" in path:
                return {"id": "reply-003"}
            # Alert email — POST to /inboxes/{id}/messages with to=[{ALERT_EMAIL}]
            if "/messages" in path and "to" in body:
                recipients = body.get("to", [])
                if any(r.get("address") == "alerts@example.com" for r in recipients):
                    alert_calls.append(body)
                    return {"id": "alert-003"}
            return {}

        mock_post.side_effect = post_side_effect

        agent.process_message(msg, inbox, conn)

    assert len(alert_calls) == 1, "Exactly one alert email should be sent"
    assert "INV-2500" in alert_calls[0]["subject"]


# ---------------------------------------------------------------------------
# Test 4 — DB roundtrip: stored row survives a re-open of the same DB
# ---------------------------------------------------------------------------

def test_db_roundtrip():
    """Extracted invoice data persisted to SQLite can be read back correctly."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    conn = agent.init_db(db_path)
    agent.store_invoice(
        conn,
        row_id="inbox-x:msg-x",
        message_id="msg-x",
        inbox_id="inbox-x",
        extracted={
            "invoice_number": "INV-9999",
            "vendor": "Roundtrip Corp",
            "amount": 123.45,
            "due_date": "2026-06-30",
        },
        received_at="2026-04-17T10:00:00Z",
    )
    conn.close()

    # Re-open and verify
    conn2 = sqlite3.connect(db_path)
    row = conn2.execute(
        "SELECT invoice_number, vendor, amount, due_date FROM invoices WHERE message_id = 'msg-x'"
    ).fetchone()
    conn2.close()

    assert row is not None, "Row should persist after DB re-open"
    assert row[0] == "INV-9999"
    assert row[1] == "Roundtrip Corp"
    assert abs(row[2] - 123.45) < 0.001
    assert row[3] == "2026-06-30"


# ---------------------------------------------------------------------------
# Test 5 — outbound messages are ignored by process_message
# ---------------------------------------------------------------------------

def test_outbound_messages_ignored():
    """Outbound messages in the inbox listing should not be processed."""
    msg = make_message("msg-004", direction="outbound")
    inbox = make_inbox("inbox-001")
    conn = in_memory_db()

    with patch.object(agent, "_post") as mock_post:
        mock_post.side_effect = AssertionError("Should not call _post for outbound messages")
        agent.process_message(msg, inbox, conn)

    # No HTTP calls should have been made
    mock_post.assert_not_called()
