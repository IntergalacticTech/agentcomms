# Invoicing Agent Example

A working Python agent that demonstrates the real multi-channel AgentComms flow:
poll a unified inbox, use AI to categorize and extract invoice data, store it in
SQLite, reply to the sender, and fire an alert for large invoices.

## What it does

1. **Provisions itself** — at startup, calls `POST /inboxes` to create (or reuse) an
   inbox named "InvoiceBot". Idempotent: if an inbox with that display name already
   exists it reuses it.
2. **Polls every 30 seconds** for new inbound email messages.
3. **Categorizes each message** via `POST /ai/categorize` with labels
   `["invoice", "receipt", "other"]`.
4. **Extracts structured data** from invoice messages via `POST /ai/extract` with
   schema `{invoice_number, vendor, amount, due_date}`.
5. **Stores** extracted invoices in a local `invoices.db` SQLite file.
6. **Replies** to the sender: "Got it — recorded as invoice {invoice_number} for {amount}."
7. **Fires an alert** by sending an email to `INVOICE_ALERT_EMAIL` when `amount > 1000`.

## Prerequisites

- Python 3.11+
- `AGENTCOMMS_API_KEY` env var set to your API key.
- `AGENTCOMMS_BASE_URL` env var set to your API base URL (e.g. `https://api.agentcomms.dev/v1`).
- `INVOICE_ALERT_EMAIL` env var set to the address that should receive large-invoice alerts.
- An AgentComms tier that includes AI features (Starter or above). AI endpoints return
  `403` on the Free tier.

## Quick start

```bash
cd examples/invoicing-agent

# Install dependencies
pip install -e .

# Configure
export AGENTCOMMS_API_KEY="ac_live_your_key"
export AGENTCOMMS_BASE_URL="https://api.agentcomms.dev/v1"
export INVOICE_ALERT_EMAIL="alerts@yourcompany.com"

# Run
python invoicing_agent.py
```

The agent logs every step to stdout in JSON format. Follow along with:

```bash
python invoicing_agent.py 2>&1 | python -m json.tool
```

## What to watch for

- **Startup:** The agent prints its inbox ID and email address. Send a test invoice
  email to that address.
- **Categorization:** Watch for `{"event": "categorize", "label": "invoice"}` lines.
- **Extraction:** After a categorize hit, watch for `{"event": "extract", ...}` with
  the parsed fields.
- **Reply:** Check your email client — the agent sends a reply within one poll cycle
  (up to 30 seconds).
- **Alert:** If the invoice amount exceeds $1,000, a separate email is sent to
  `INVOICE_ALERT_EMAIL`.
- **Database:** Inspect `invoices.db` with `sqlite3 invoices.db "select * from invoices"`.

## Running the tests (no API key needed)

```bash
pip install pytest
pytest invoicing_agent_test.py -v
```

All HTTP calls are mocked. The test suite covers the full flow: categorize+extract,
non-invoice skip, large-invoice alert, and DB roundtrip.
