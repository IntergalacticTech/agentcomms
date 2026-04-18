# Coding Agent Self-Deploys AgentComms

This example shows the "meta" use case: you give a single prompt to your coding agent
(Claude Code, Cursor, Aider, etc.) and it reads the project's `AGENT.md`, runs
`agentcomms bootstrap`, and hands you back a working API key — all without human
intervention beyond pasting the prompt.

## Why this matters

This is the central claim of the AgentComms launch: **your coding agent can deploy the
entire communications hub into your own AWS account in about 20 minutes.** These
transcripts prove it. Every other feature — unified inbox, AI categorization, Slack
integration — builds on top of a deployment that a coding agent can reproduce on demand.

## Files in this directory

| File | Description |
|------|-------------|
| `agent-prompt.md` | The exact paragraph you paste into your coding agent |
| `transcript-claude-code.md` | Illustrative transcript for Claude Code (placeholder) |
| `transcript-cursor.md` | Illustrative transcript for Cursor (placeholder) |
| `transcript-aider.md` | Illustrative transcript for Aider (placeholder) |

The transcripts are marked as **illustrative placeholders** at the top of each file.
Real recordings will replace them after the launch screencast is produced.

## How to reproduce

### Prerequisites

1. An AWS sub-account with no existing AgentComms resources.
2. An AWS profile configured locally (e.g. `agentcomms-test`).
3. A domain you control (e.g. `agentcomms-test-demo.com`) with its nameservers
   pointing at Route 53 — or a domain you are willing to add NS records for.
4. One of the supported coding agents installed and authenticated:
   - [Claude Code](https://claude.ai/code) (`claude` CLI, v1.x or later)
   - [Cursor](https://cursor.sh) with an active subscription
   - [Aider](https://aider.chat) with an Anthropic or OpenAI key

### Step 1 — Clone the repo

```bash
git clone https://github.com/agentcomms/agentcomms.git
cd agentcomms
```

### Step 2 — Paste the prompt

Open your coding agent in this repo directory and paste the prompt from
[`agent-prompt.md`](agent-prompt.md) verbatim. The agent reads `AGENT.md`, which
contains the full bootstrap instructions.

### Step 3 — Watch it go

The agent will:
1. Read `AGENT.md` to understand what to do.
2. Run `agentcomms bootstrap --profile agentcomms-test --domain agentcomms-test-demo.com ...`.
3. Stream NDJSON progress events as CloudFormation stacks deploy and SES provisions.
4. Print the final API key.

Typical wall-clock time: **15–25 minutes** (CloudFormation + SES DNS propagation).

### Step 4 — Verify

The agent prints the API key. Test it:

```bash
export AGENTCOMMS_API_KEY="ac_live_<key from agent>"
curl "$AGENTCOMMS_BASE_URL/v1/inboxes" -H "x-api-key: $AGENTCOMMS_API_KEY"
```

## Capture your own transcript

To produce a real transcript:

```bash
# Claude Code
script -q /tmp/bootstrap.log claude "$(cat agent-prompt.md)"
# or with the Claude Code --print flag:
claude --print "$(cat agent-prompt.md)" | tee /tmp/bootstrap.log
```

Then clean up any secrets from the log before committing it as a replacement for the
placeholder transcript.

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| Bootstrap halts at `ses:VerifyDomainIdentity` | DNS not yet delegated to Route 53. Wait for propagation or pre-delegate. |
| `NoCredentialsError` | AWS profile `agentcomms-test` not found. Check `~/.aws/config`. |
| `DOMAIN_ALREADY_EXISTS` | A previous partial run left records. Run `agentcomms teardown` first. |
| Agent doesn't read AGENT.md | Ensure you're in the repo root when invoking the agent. |
