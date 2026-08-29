# AgentComms Examples

Three runnable examples showing how to use AgentComms in real agent workflows.

## Prerequisites

All examples expect two environment variables:

```bash
export AGENTCOMMS_API_KEY="ak_live_your_key_here"
export AGENTCOMMS_BASE_URL="https://api.agentcomms.dev/v1"
```

Get your API key from the [AgentComms dashboard](https://dashboard.agentcomms.dev) or by running
`agentcomms bootstrap` against your own AWS deployment.

## Examples

| Directory | What it demonstrates |
|-----------|---------------------|
| [`coding-agent-self-deploys/`](coding-agent-self-deploys/) | The meta-example: give this prompt to a coding agent (Claude Code, Cursor, Aider) and watch it deploy AgentComms end-to-end into your AWS account. Includes illustrative transcripts for each tool. |
| [`invoicing-agent/`](invoicing-agent/) | A working Python agent that polls email messages, uses AI to categorize and extract invoice data, stores it in SQLite, and replies with a confirmation. Demonstrates the unified message API + AI features together. |
| [`slack-standup-bot/`](slack-standup-bot/) | A working Python agent that DMs each team member at 9 AM asking for their standup, collects replies over an hour, summarizes them with AI, and posts the summary to a Slack channel. |
| [`adapter-template/`](adapter-template/) | A minimal external adapter package with entry-point registration, inbound normalization, outbound sends, and tests. |

## How to use these examples

Each example is **standalone** — clone this repo, `cd` into the example directory, and follow its README. No shared state between examples.

The agent examples (`invoicing-agent/` and `slack-standup-bot/`) use only the standard library plus the `agentcomms` package. Install with:

```bash
pip install agentcomms
# or, for development from this repo:
pip install -e .
```

The test suites mock all HTTP calls, so `pytest` works without a real API key:

```bash
pytest examples/invoicing-agent/ examples/slack-standup-bot/ examples/adapter-template/ -v
```
