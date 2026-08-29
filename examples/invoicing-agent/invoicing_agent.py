"""
invoicing_agent.py — AgentComms invoicing agent example.

Polls an agent's email messages every 30 seconds. For each inbound email:
  - Calls /agents/{agent_id}/ai/categorize to classify as "invoice", "receipt", or "other".
  - If "invoice", calls /agents/{agent_id}/ai/extract for structured fields and stores in SQLite.
  - Replies to the sender with a confirmation.
  - If amount > 1000, sends an alert to INVOICE_ALERT_EMAIL.

Required env vars:
  AGENTCOMMS_API_KEY    — API key (ak_live_...)
  AGENTCOMMS_BASE_URL   — e.g. https://api.agentcomms.dev/v1
  INVOICE_ALERT_EMAIL   — email address for large-invoice alerts

Optional:
  INVOICE_AGENT_ID      — existing AgentComms agent ID to reuse
  POLL_INTERVAL_SECONDS — seconds between polls (default 30)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sqlite3
import sys
import time
from datetime import datetime, timezone

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("AGENTCOMMS_API_KEY", "")
BASE_URL = os.environ.get("AGENTCOMMS_BASE_URL", "https://api.agentcomms.dev/v1").rstrip("/")
ALERT_EMAIL = os.environ.get("INVOICE_ALERT_EMAIL", "")
AGENT_ID = os.environ.get("INVOICE_AGENT_ID", "")
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL_SECONDS", "30"))
DB_PATH = os.environ.get("INVOICE_DB_PATH", "invoices.db")
AGENT_NAME = "InvoiceBot"

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def log(event: str, **kwargs) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **kwargs}
    logger.info(json.dumps(record))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _headers() -> dict[str, str]:
    return {"x-api-key": API_KEY, "Content-Type": "application/json"}


def _get(path: str, **params) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.get(url, headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, body: dict) -> dict:
    url = f"{BASE_URL}/{path.lstrip('/')}"
    resp = requests.post(url, headers=_headers(), json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id            TEXT PRIMARY KEY,
            message_id    TEXT NOT NULL,
            agent_id      TEXT NOT NULL,
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


def store_invoice(conn: sqlite3.Connection, row_id: str, message_id: str,
                  agent_id: str, extracted: dict, received_at: str) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO invoices
           (id, message_id, agent_id, invoice_number, vendor, amount, due_date, received_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row_id,
            message_id,
            agent_id,
            extracted.get("invoice_number"),
            extracted.get("vendor"),
            extracted.get("amount"),
            extracted.get("due_date"),
            received_at,
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Agent logic
# ---------------------------------------------------------------------------

def _email_from_channels(channels: list[dict]) -> str | None:
    for channel in channels:
        if channel.get("channel") != "email":
            continue
        details = channel.get("details") or channel.get("config") or {}
        return details.get("address") or details.get("email")
    return None


def _agent_email(agent_id: str) -> str | None:
    page = _get(f"/agents/{agent_id}/channels")
    return _email_from_channels(page.get("channels", []))


def provision_agent() -> dict:
    """Return an existing InvoiceBot agent or create one with email provisioned."""
    if AGENT_ID:
        agent = _get(f"/agents/{AGENT_ID}")
        email = _agent_email(AGENT_ID)
        log("agent_reused", agent_id=AGENT_ID, email=email)
        return {"agent_id": AGENT_ID, "name": agent.get("name", AGENT_NAME), "email": email}

    page = _get("/agents", limit=100)
    for agent in page.get("agents", page.get("data", [])):
        if agent.get("name") == AGENT_NAME:
            agent_id = agent["agent_id"]
            email = _agent_email(agent_id)
            log("agent_reused", agent_id=agent_id, email=email)
            return {"agent_id": agent_id, "name": AGENT_NAME, "email": email}

    agent = _post("/agents", {"name": AGENT_NAME, "provision": {"email": {}}})
    agent_id = agent["agent_id"]
    email = _email_from_channels(agent.get("channels", [])) or _agent_email(agent_id)
    log("agent_created", agent_id=agent_id, email=email)
    return {"agent_id": agent_id, "name": AGENT_NAME, "email": email}


def categorize(agent_id: str, message_id: str) -> str:
    """Classify the message. Returns the winning label."""
    result = _post(f"/agents/{agent_id}/ai/categorize", {
        "message_id": message_id,
        "labels": ["invoice", "receipt", "other"],
    })
    label = result.get("label", result.get("category", "other"))
    log("categorize", message_id=message_id, label=label)
    return label


def extract_invoice(agent_id: str, message_id: str) -> dict:
    """Extract structured invoice fields from the message."""
    result = _post(f"/agents/{agent_id}/ai/extract", {
        "message_id": message_id,
        "schema": {
            "invoice_number": "string",
            "vendor": "string",
            "amount": "number",
            "due_date": "date",
        },
    })
    extracted = result.get("data", result.get("extracted", {}))
    log("extract", message_id=message_id, fields=extracted)
    return extracted


def reply_to_message(agent_id: str, message_id: str, invoice_number: str | None,
                     amount: float | None) -> None:
    inv_str = invoice_number or "unknown"
    amt_str = f"${amount:,.2f}" if amount is not None else "unknown amount"
    body = f"Got it — recorded as invoice {inv_str} for {amt_str}."
    _post(f"/agents/{agent_id}/messages/{message_id}/reply", {"body": body})
    log("replied", message_id=message_id, invoice_number=inv_str, amount=amt_str)


def send_alert(agent_id: str, invoice_number: str | None, vendor: str | None,
               amount: float | None) -> None:
    """Email the alert address about a large invoice."""
    if not ALERT_EMAIL:
        log("alert_skipped", reason="INVOICE_ALERT_EMAIL not set")
        return
    inv_str = invoice_number or "unknown"
    vendor_str = vendor or "unknown vendor"
    amt_str = f"${amount:,.2f}" if amount is not None else "unknown amount"
    subject = f"Large invoice alert: {inv_str} for {amt_str}"
    body = (
        f"Invoice {inv_str} from {vendor_str} has been recorded for {amt_str}.\n"
        f"This exceeds the $1,000 alert threshold and requires your attention."
    )
    _post(f"/agents/{agent_id}/messages", {
        "to": [{"address": ALERT_EMAIL}],
        "channel": "email",
        "subject": subject,
        "body_text": body,
    })
    log("alert_sent", alert_email=ALERT_EMAIL, invoice_number=inv_str, amount=amount)


def process_message(msg: dict, agent: dict, conn: sqlite3.Connection) -> None:
    """Process a single inbound message."""
    if msg.get("direction") != "inbound":
        return

    message_id = msg.get("message_id") or msg["id"]
    agent_id = agent["agent_id"]
    received_at = msg.get("received_at", msg.get("created_at", ""))

    label = categorize(agent_id, message_id)

    if label != "invoice":
        log("skipped", message_id=message_id, label=label)
        return

    extracted = extract_invoice(agent_id, message_id)
    amount = extracted.get("amount")
    invoice_number = extracted.get("invoice_number")
    vendor = extracted.get("vendor")

    store_invoice(conn, f"{agent_id}:{message_id}", message_id, agent_id,
                  extracted, received_at)
    log("stored", message_id=message_id, invoice_number=invoice_number, amount=amount)

    reply_to_message(agent_id, message_id, invoice_number, amount)

    if amount is not None and amount > 1000:
        send_alert(agent_id, invoice_number, vendor, amount)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_sigterm(signum, frame) -> None:  # noqa: ARG001
    global _shutdown
    log("shutdown_requested")
    _shutdown = True


def main() -> None:
    if not API_KEY:
        print("ERROR: AGENTCOMMS_API_KEY is not set", file=sys.stderr)
        sys.exit(1)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    log("startup", base_url=BASE_URL, poll_interval=POLL_INTERVAL, db_path=DB_PATH)

    conn = init_db(DB_PATH)
    agent = provision_agent()
    agent_id = agent["agent_id"]

    last_check = datetime.now(timezone.utc).isoformat()

    while not _shutdown:
        try:
            now = datetime.now(timezone.utc).isoformat()
            page = _get(f"/agents/{agent_id}/messages",
                        channels="email", limit=100)
            messages = page.get("messages", page.get("data", []))
            new_messages = [
                m for m in messages
                if m.get("received_at", m.get("created_at", "")) > last_check
                and m.get("direction") == "inbound"
            ]
            log("poll", count=len(new_messages), since=last_check)

            for msg in new_messages:
                try:
                    process_message(msg, agent, conn)
                except Exception as exc:  # noqa: BLE001
                    log("process_error", message_id=msg.get("message_id") or msg.get("id"), error=str(exc))

            last_check = now

        except KeyboardInterrupt:
            log("shutdown_requested", source="keyboard")
            break
        except Exception as exc:  # noqa: BLE001
            log("poll_error", error=str(exc))

        if not _shutdown:
            time.sleep(POLL_INTERVAL)

    conn.close()
    log("shutdown_complete")


if __name__ == "__main__":
    main()
