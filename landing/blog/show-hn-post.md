# Show HN post — drafts

Target publish: Tuesday at 09:15 UTC (optimal US/EU overlap). See `docs/PUBLIC_RELEASE.md` for the full public launch checklist.

## Primary (main post)

**Title (choose one):**
- `Show HN: AgentComms - open-source agent comms hub your coding agent deploys`
- `Show HN: AgentComms - unified inbox for AI agents across any channel`
- `Show HN: Open-source comms infrastructure for AI agents, deployed in your AWS`

First option is tightest and lead with the differentiator.

**URL:** `https://agentcomms.dev`

**Body (195 words):**

> AgentComms gives AI agents first-class identity across email, SMS, Slack, Telegram, mobile push, and external adapter channels. Direct messages and explicit @mentions show up in a single `/v1/agents/{id}/messages` feed, interleaved by time.
>
> What's different: the whole thing is open source under Apache-2.0, deploys end-to-end into your own AWS account via a CLI written for coding agents to operate, and uses AWS-native primitives (DynamoDB, Lambda, API Gateway, SES, SNS, SQS, Kinesis, KMS, Bedrock). No Kafka, Redis, or Postgres. Your coding agent can install the CLI, read `AGENT.md`, and bring up the hub in your cloud.
>
> Licensed under Apache-2.0: you can self-host, modify, redistribute, build commercial products, and run your own hosted version. No field-of-use restriction, delayed relicensing period, or separate paid license.
>
> The adapter model is intentionally open-ended. Built-ins cover email/SMS/push/Slack/Telegram; external packages register through the `agentcomms.adapters` entry-point group with stable slugs like `matrix`, `webhook`, or whatever channel your agents need.
>
> Repo: github.com/IntergalacticTech/agentcomms. Quickstart: AGENT.md at the repo root. I'll be around for 24 hours to answer anything.

## First-comment plant (post this yourself immediately as a top-level reply)

**Body (~180 words):**

> Author here. One technical detail that took longer to get right than I expected:
>
> The "unified inbox" part of AgentComms is the marketing headline, but the actual architectural bet is how we handle channels that DON'T fit an inbox model. Slack has workspaces → channels → DMs. Discord has guilds → channels → DMs. Telegram has chats. If you naively merge all of that into one feed your agent drowns in noise from rooms the bot is passively in.
>
> We went with what we're calling "X1": the unified inbox contains ONLY direct messages and explicit @mentions. Everything else (channel chatter, guild activity) stays accessible but lives under channel-native paths like `/v1/agents/{id}/slack/workspaces/{team}/channels/{ch}/messages`. The `is_dm` flag on each message is enforced at write time via a sparse DynamoDB GSI — non-DM traffic can't accidentally appear in the unified feed even if a handler is buggy.
>
> This means agents can treat the unified inbox like a real inbox (low volume, every message deserves attention) while still getting full access to channel-native behavior when they want it. That split turned out to be the right primitive.
>
> Happy to go deeper on anything: data model, deployment, the OSS model, or adapter implementation details.

## Guard rails

- Do NOT upvote your own post from alts or ask anyone to upvote — HN detects and shadowbans.
- Do NOT delete the post and re-post to reset ranking — also detected.
- Respond to every top-level comment within an hour for the first 6 hours.
- If you get into a long back-and-forth with a skeptical commenter, stay technical and concede anything they're right about. HN respects engineers who engage honestly with criticism.
- Share the post URL in your company Slack / Twitter / LinkedIn AFTER it hits ~30 upvotes so the algorithmic boost is already working.
