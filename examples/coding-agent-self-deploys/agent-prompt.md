# Agent Prompt — Deploy AgentComms

Paste the paragraph below into your coding agent (Claude Code, Cursor, Aider, etc.)
while your working directory is the root of this repository.

---

Read AGENT.md in this repo. Deploy AgentComms into my AWS account (profile `agentcomms-test`, region `us-east-1`) using the domain `agentcomms-test-demo.com`. My admin email is `demo@agentcomms-test-demo.com`. Use `--non-interactive --json` and give me the final API key. Capture the full stdout stream to `/tmp/bootstrap.log` so I can see the NDJSON events.
