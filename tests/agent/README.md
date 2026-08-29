# AgentComms Agent Test Suite

## Purpose

This suite validates the AgentComms API end to end from an agent user's point of
view: agent creation, channel provisioning, send/list/read/reply flows, OTP
extraction, AI summarization, webhooks, scoped API keys, and cleanup.

Unlike the Python `pytest` suite under `tests/`, this suite is written to be
executed by another AI agent or a human operator using HTTP calls. There is no
test runner; the operator reads `test-suite.md`, performs each scenario, and
reports the result.

## What The Agent Needs

1. An HTTP tool such as `curl`, `fetch`, or `requests`.
2. Scratch memory for values such as `API_KEY`, `AGENT_ID`, and `MESSAGE_ID`.
3. Access to an AgentComms deployment, hosted or self-hosted.
4. An org-scoped API key for that deployment.

## How To Execute

1. Open `test-suite.md`.
2. Set `BASE_URL`, for example `https://api.agentcomms.dev/v1`.
3. Set `API_KEY` to an org-scoped key.
4. Run each scenario in order.
5. Record `PASS` or `FAIL` with a one-line reason.

If a scenario fails, continue where possible. Some later scenarios depend on
state from earlier scenarios, but API-key and cleanup checks can still provide
useful signal.

## Reporting

Print the final report to stdout or the conversation transcript. If a file is
requested, write it to `tests/agent/last-run.txt` relative to the repository
root.

## Conventions

- `{API_KEY}`, `{AGENT_ID}`, `{MESSAGE_ID}`, and similar values are placeholders.
- Most requests require either `Authorization: Bearer {API_KEY}` or
  `x-api-key: {API_KEY}`.
- Successful mutating requests generally return `201` or `204`; reads return
  `200`.
