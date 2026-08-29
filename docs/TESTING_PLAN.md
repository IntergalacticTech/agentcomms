# Testing Plan

This plan covers local repository validation and optional live-instance smoke testing for AgentComms.

## Local Prerequisites

- Python 3.12 with `requirements-dev.txt` installed
- Node.js 20+
- Package dependencies installed in `cdk/`, `cli/`, `mcp/`, and `sdks/node/`

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Core Python Tests

```bash
python -m pytest tests/core tests/api tests/e2e adapters -q
```

Use focused suites while developing:

```bash
python -m pytest tests/api/test_messages.py tests/api/test_api_keys.py -q
python -m pytest tests/core/test_authorizer.py tests/e2e/test_email_roundtrip.py -q
python -m pytest tests/adapters -q
```

## CDK

```bash
cd cdk
npm install
npm test -- --runInBand
npm run build
```

The CDK app should synth AgentComms stacks into the caller's configured account/region. It must not pin deployment to a maintainer account.

## CLI

```bash
cd cli
npm install
npm test -- --runInBand
npm run build
```

For non-destructive preflight:

```bash
agentcomms doctor --domain example.com --json
```

## SDKs

Python:

```bash
cd sdks/python
python -m pytest tests -q
```

Node:

```bash
cd sdks/node
npm install
npm test -- --runInBand
npm run build
```

## MCP

```bash
cd mcp
npm install
npm test -- --runInBand
npm run build
```

## Live Smoke Test

Set your own deployment details:

```bash
export AGENTCOMMS_BASE_URL=https://api.example.com/v1
export AGENTCOMMS_API_KEY=ak_live_YOUR_KEY
export DOMAIN_FOR_PROVISION=example.com
```

Run:

```bash
./tools/smoke_test_live.sh
```

The smoke test checks auth, agent lifecycle, channel provisioning, vault/TOTP, personas, domains, webhooks, and cleanup. It creates temporary resources and deletes them before exiting.

## Manual Round Trip

Create an agent with an email channel:

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "manual-test-agent",
    "provision": {
      "email": {"local_part": "manual-test", "domain": "'$DOMAIN_FOR_PROVISION'"}
    }
  }'
```

Send:

```bash
curl -sS -X POST "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/messages" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "you@example.com",
    "subject": "AgentComms test",
    "body": "Outbound smoke test."
  }'
```

Read:

```bash
curl -sS "$AGENTCOMMS_BASE_URL/agents/$AGENT_ID/messages?limit=25" \
  -H "Authorization: Bearer $AGENTCOMMS_API_KEY"
```

Reply to the delivered email from your human inbox, then call the message list again. If inbound is configured correctly, the reply appears as an inbound `UnifiedMessage`.

## Release Gate

Before public release:

```bash
python -m pytest tests/core tests/api tests/e2e adapters -q
cd cdk && npm test -- --runInBand && npm run build
cd ../cli && npm test -- --runInBand && npm run build
cd ../sdks/python && python -m pytest tests -q
cd ../node && npm test -- --runInBand && npm run build
cd ../../mcp && npm test -- --runInBand && npm run build
```

Also run the release hygiene scan for old restrictive-license wording, old API key prefixes, old environment variable names, and maintainer account IDs.

The scan should produce no output except deliberately historical files if you choose to include them.
