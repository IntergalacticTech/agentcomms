# Product Hunt launch assets

## Tagline (60 characters max)

**`Your AI agent's communications hub, in your own AWS.`** (52 chars)

Alternates:
- `Unified inbox for AI agents — email, SMS, Slack, Telegram.` (58)
- `Source-available agent comms hub. Deploys into your cloud.` (59)

Primary is best — it signals the agent focus and the self-deploy twist in one line.

## Description (260 characters max)

> AgentComms gives each AI agent an email, phone number, Slack bot, and Telegram bot — routing into ONE unified inbox. Source-available, deploys into YOUR AWS account in 20 minutes via a CLI your coding agent can run. No Kafka, no Redis, pure AWS. FSL-licensed.

## Maker comment (T+0 on launch day)

> I spent the last year running FreeMail — "email for AI agents." It worked until it didn't; the category commoditized faster than expected. Rather than ride the curve down I rebuilt the product from the ground up as AgentComms.
>
> The shift: agents don't need email, agents need to communicate. Email is one channel. The right abstraction is a unified inbox across every channel — email, SMS, Slack, Telegram, mobile push, with more (Discord, WhatsApp, postal, fax, voice) coming.
>
> Two things nobody else is doing: (1) the entire thing deploys into YOUR AWS account via one CLI command, using only AWS-native primitives. Your data never leaves your cloud. (2) The license is Functional Source License — the code's readable, runnable, and modifiable forever, and auto-relicenses to Apache 2.0 per file after two years. You just can't resell the service in competition with ours.
>
> Built on DynamoDB, Lambda, SES, SNS, Kinesis, Bedrock. 390+ tests passing. Phases 1–4 shipped and running in production today; Phase 5 cutover complete; Phase 6 is this launch.
>
> Happy to answer anything. Technical questions especially — the architectural decisions here (agent-centric data model, unified inbox with sparse GSI, source-available license choice) took a while to land and I'm glad to go deep.

## Screenshots / media

Five suggested screenshots / media assets for Product Hunt (1270×760 ideal):

1. **Landing page hero** — "Your AI agent's communications hub, deployed into your own AWS." with the bootstrap command below the fold.
2. **CLI bootstrap in action** — terminal with NDJSON events scrolling: preflight → deploy → ses → seed → done with the API key.
3. **Unified inbox code example** — Python SDK showing `agent.messages.list()` returning interleaved email + SMS + Slack messages.
4. **Architecture diagram** — the ASCII diagram from the README, cleaned up in Excalidraw or Figma. Boxes for SDKs/REST clients → API Gateway → Lambda → DynamoDB/Kinesis/Adapter Runtime → SES/SMS/Slack/Telegram.
5. **Screencast frame** — still from the 3-minute demo, freeze-frame at the "admin_api_key" reveal moment.

Gallery order: 1, 2, 3, 4, 5.

## Tags to select

- Developer tools
- Artificial intelligence
- SaaS
- Open source (PH lets you tag this even though FSL isn't strictly open source — better exposure than not tagging)
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

- **Day -3:** DM 20 early AgentComms / FreeMail customers asking if they'd be willing to comment on launch day with their real-world usage.
- **Day -1:** Set up Twitter/LinkedIn thread explaining the pivot, publish at T+4h on launch day.
- **Day 0:** Launch. Respond to everything.
- **Day +1:** Post retrospective thread on X with screenshots of the ranking timeline + any funny comments.
- **Day +7:** Write a Medium/blog follow-up on what the launch data showed — conversion rate from PH → signup, common questions asked, what surprised us.
