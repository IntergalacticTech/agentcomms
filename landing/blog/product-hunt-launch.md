# Product Hunt launch assets

## Tagline (60 characters max)

**`Your AI agent's communications hub, in your own AWS.`** (52 chars)

Alternates:
- `Unified inbox for AI agents across every channel.` (48)
- `Open-source agent comms hub. Deploys into your cloud.` (55)

Primary is best: it signals the agent focus and the self-deploy model in one line.

## Description (260 characters max)

> AgentComms is an Apache-2.0 communications hub for AI agents: email, SMS, Slack, Telegram, push, and third-party adapter channels in one unified inbox. Deploy it into your AWS account with a CLI your coding agent can run.

## Maker comment (T+0 on launch day)

> I started this as narrow infrastructure for agent email. The more real workflows we saw, the more obvious the actual primitive became: agents do not need one more mailbox API; they need a durable communications hub.
>
> AgentComms gives each agent durable identity across email, SMS, Slack, Telegram, mobile push, and any external adapter channel. Direct messages and explicit mentions land in one unified inbox; room or provider-native context stays available through native surfaces instead of flooding the attention stream.
>
> Two things matter most: (1) the whole hub deploys into YOUR AWS account via one CLI command, using AWS-native primitives. Your data stays in your cloud. (2) The license is Apache-2.0: readable, runnable, modifiable, redistributable, and usable for commercial or hosted deployments without a separate agreement from us.
>
> Built on DynamoDB, Lambda, API Gateway, SES, SNS, SQS, Kinesis, KMS, and Bedrock. The REST API, Python SDK, Node SDK, CLI, MCP server, and adapter template are all tested. The production deploy path is live.
>
> Happy to answer anything. Technical questions especially: the agent-centric data model, unified inbox semantics, and adapter contract are the core of the project.

## Screenshots / media

Five suggested screenshots / media assets for Product Hunt (1270×760 ideal):

1. **Landing page hero** — "Your AI agent's communications hub, deployed into your own AWS." with the bootstrap command below the fold.
2. **CLI bootstrap in action** — terminal with NDJSON events scrolling: preflight → deploy → ses → seed → done with the API key.
3. **Unified inbox code example** — Python SDK showing `agent.messages.list()` returning interleaved email, SMS, Slack, Telegram, and adapter messages.
4. **Architecture diagram** — the ASCII diagram from the README, cleaned up in Excalidraw or Figma. Boxes for SDKs/REST clients → API Gateway → Lambda → DynamoDB/Kinesis/Adapter Runtime → SES/SMS/Slack/Telegram.
5. **Screencast frame** — still from the 3-minute demo, freeze-frame at the "admin_api_key" reveal moment.

Gallery order: 1, 2, 3, 4, 5.

## Tags to select

- Developer tools
- Artificial intelligence
- SaaS
- Open source
- AWS
- Productivity

## Launch-day checklist

- [ ] Confirm product page approved by PH moderators (submit 2-3 days ahead).
- [ ] Schedule post for 12:01am PT (optimal PH timing).
- [ ] Post maker comment at T+0 exactly.
- [ ] Share link in founder Slack / X / LinkedIn at T+2h (after initial traction).
- [ ] Email personal network (30+ people who agreed to up-vote + comment) at T+4h.
- [ ] Respond to every comment within 2 hours for the first 12 hours.
- [ ] Post a "thank you" comment at T+24h regardless of ranking.

## Hunter strategy

Self-hunt (you can hunt your own product on PH). If you have a well-known PH hunter in your network who'd hunt it for you, their reach helps — but only if they're genuinely interested, not as a favor. Don't pay anyone to hunt; it shows.

## Cross-promotion timing

- **Day -3:** DM 20 early AgentComms users and OSS contributors asking if they'd be willing to comment on launch day with their real-world usage.
- **Day -1:** Set up Twitter/LinkedIn thread explaining the pivot, publish at T+4h on launch day.
- **Day 0:** Launch. Respond to everything.
- **Day +1:** Post retrospective thread on X with screenshots of the ranking timeline + any funny comments.
- **Day +7:** Write a Medium/blog follow-up on what the launch data showed — conversion rate from PH → signup, common questions asked, what surprised us.
