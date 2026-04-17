# AgentComms Phase 6: Launch — Implementation Plan

> **Fidelity note:** B-fidelity. This phase is mostly content creation + coordinated announcements rather than code. Follow the Phase 1 TDD rhythm only where code is involved.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Spec:** `docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md` §7.5
**Predecessors:** Phases 1–5 complete. `api.agentcomms.dev` is authoritative; repo is public on GitHub; OSS packaging is done.

**Goal:** Public launch — land the "your coding agent can deploy this in your AWS account in 20 minutes" narrative with Show HN, Product Hunt, a technical blog post, a demo screencast, and runnable example projects. Seed the community so that by Week 8 at least one external contributor has opened an adapter PR.

---

## File structure (created/published in Phase 6)

```
landing/
├── index.html                          # refined landing page
├── assets/
│   ├── bootstrap-demo.gif              # 10-second CLI teaser
│   ├── bootstrap-demo.mp4              # full 3-min screencast (hosted on YouTube + self)
│   └── architecture-diagram.svg
└── blog/
    ├── 2026-04-XX-pivot.md             # "Why we pivoted from FreeMail to AgentComms"
    ├── 2026-05-XX-hn-post.md           # the Show HN text
    └── 2026-05-XX-product-hunt.md

examples/
├── coding-agent-self-deploys/
│   ├── README.md
│   ├── transcript-claude-code.md       # recorded agent transcript reading AGENT.md
│   ├── transcript-cursor.md
│   └── agent-prompt.md                 # the single prompt you give your coding agent
├── invoicing-agent/
│   ├── README.md
│   ├── agent.py                        # ~100-line working example: reads inbox, extracts invoice fields, replies
│   ├── pyproject.toml
│   └── tests/
├── slack-standup-bot/
│   ├── README.md
│   ├── agent.py
│   └── pyproject.toml
└── telegram-notifier/
    ├── README.md
    └── agent.py

docs/
├── getting-started.md                  # refined from quickstart.md — front door
├── tutorials/
│   ├── first-agent-in-5-minutes.md
│   ├── slack-bot.md
│   └── email-and-sms-together.md
└── adapters/{email,sms,slack,telegram,push}.md   # finalized from Phase 4 drafts
```

---

## Task 1: Screencast — "Claude Code deploys AgentComms end-to-end"

**Deliverables:**
- 3-minute video, recorded at 1920×1080, 60 fps. Voice-over by a human (not AI TTS — authenticity matters for launch).
- Script structure:
  - 0:00–0:15: problem framing ("Cloudflare gives away free agent email, but you still need SMS, Slack, Telegram…")
  - 0:15–0:45: the setup (fresh AWS sub-account, a domain, Claude Code)
  - 0:45–2:30: the unbroken take of Claude Code reading `AGENT.md`, running `agentcomms bootstrap`, watching the NDJSON phases tick past, getting the API key, creating an agent, sending the first email
  - 2:30–3:00: the provisioned agent receives a reply, the unified inbox populates, the screencast ends with `agent.messages.list()` showing the round-trip

**Steps:**
1. Record the bootstrap against a clean sub-account. Aim for first-take; show real state, don't edit phases out.
2. Edit in Final Cut / DaVinci Resolve: add chapter markers, on-screen highlights for the important NDJSON lines, subtle music.
3. Export 3 versions:
   - MP4 H.264 for YouTube.
   - GIF (10-sec condensed version of the money shot) for README + landing page.
   - MP4 for self-hosted embedding on `agentcomms.dev`.
4. Upload to YouTube with a good thumbnail.
5. **Commit:** `docs(phase6): screencast assets (gif + mp4 + architecture svg)`

---

## Task 2: Example project — `coding-agent-self-deploys/`

**File:** `examples/coding-agent-self-deploys/`

**Deliverable:** the exact inputs + transcripts showing Claude Code, Cursor, and Aider each independently deploying AgentComms end-to-end.

**Steps:**
1. `agent-prompt.md`: the single sentence / paragraph you give the agent. Something like:

   > Read AGENT.md in this repo. Deploy AgentComms into my AWS account (profile `agentcomms-test`) using the domain `my-agent-bot.com`. My admin email is `you@x.com`. Use `--non-interactive --json` and tell me the final API key.

2. Run that prompt with Claude Code end-to-end, record the full terminal transcript to `transcript-claude-code.md`. Clean up only secrets; otherwise verbatim.
3. Repeat with Cursor and Aider.
4. Write the README explaining how to reproduce.

**Why this matters:** This example *is* the launch. Every other claim in the pivot narrative hinges on this being real and reproducible. Treat the transcript as a primary artifact.

**Commit:** `docs(phase6): coding-agent-self-deploys example with 3 verified agent transcripts`

---

## Task 3: Example project — `invoicing-agent/`

**File:** `examples/invoicing-agent/`

**Deliverable:** a working ~100-line Python agent that demonstrates real multi-channel agent logic.

**Behavior:**
- Provisions itself an email + SMS channel at startup (idempotent; reuses if already provisioned).
- Polls the unified inbox every 30s.
- For each inbound email that looks like an invoice (simple keyword check + `ai.categorize` call), extracts structured fields via `ai.extract` with a JSON schema (`invoice_number`, `amount`, `due_date`, `vendor`).
- Writes extracted data to a local SQLite file.
- If the invoice amount > $1000, sends an SMS alert to the agent's owner.
- Replies to the email with a confirmation.

**Why this matters:** proves the unified-inbox + AI + cross-channel story works in real code. Each feature in the spec shows up here.

**Commit:** `docs(phase6): invoicing-agent example — inbox polling + AI extract + SMS alerts + email reply`

---

## Task 4: Example project — `slack-standup-bot/`

**File:** `examples/slack-standup-bot/`

**Deliverable:** a Slack bot that @mentions each team member at 9am asking for their standup, collects replies over an hour, and posts a summary to the team channel.

**Behavior:**
- Uses the Slack native sub-surface (`/v1/agents/{id}/slack/workspaces/{team}/channels/{ch}/messages`) to post the prompt.
- Uses the unified inbox (filtered to Slack DMs) to collect replies.
- At 10am, uses `ai.summarize` to condense the 3-5 replies into a team update, and posts it to the public channel.

**Commit:** `docs(phase6): slack-standup-bot example`

---

## Task 5: Landing page refinement

**File:** `landing/index.html`

**Refinements on top of the Phase 4 landing page:**
- Embed the bootstrap-demo.gif above the fold.
- Add a "proof" section linking to the 3 agent transcripts from Task 2.
- Add a "pricing" section (Free / Developer / Team / Business / Enterprise) linking to the dashboard signup.
- Add a "self-host" section with the exact bootstrap command.
- Add social proof placeholders (will populate post-launch as adoption lands).
- SEO: `<meta>` tags emphasizing "agent communications hub", "source available", "AWS".

**Commit:** `feat(phase6): launch-ready landing page with demo gif and proof section`

---

## Task 6: Blog post — "Why we pivoted from FreeMail to AgentComms"

**File:** `landing/blog/2026-04-XX-pivot.md`

**Outline:**
1. The original FreeMail thesis ("email for AI agents") and what we built.
2. What changed in the market (Cloudflare, AgentMail, the commoditization pattern).
3. Why narrow wedges lose to broader platforms in emerging categories.
4. The new thesis: one hub for all agent comms — email, SMS, Slack, Telegram, Discord, WhatsApp, postal, fax, voice.
5. The architectural bet: agent-centric data model, ChannelAdapter plugin contract, AWS-native.
6. The differentiator Cloudflare can't touch: "your coding agent deploys the whole thing into your AWS account in 20 minutes."
7. The license choice (FSL), why not Apache (defensibility), why not AGPL (reach).
8. What customers need to do (link to MIGRATION.md).
9. What's next (Discord, WhatsApp, postal mail).
10. Call to action: try the bootstrap; contribute an adapter; grab a commercial license if you want to host.

**Length target:** 1,800–2,500 words.

**Commit:** `docs(phase6): pivot blog post (ready to publish)`

---

## Task 7: Show HN post

**File:** `landing/blog/2026-05-XX-hn-post.md`

**Structure:**
- **Title:** `Show HN: AgentComms – the agent-comms hub your coding agent deploys for you (source-available, AWS-native)`
- **Body (~200 words):**
  - One-sentence hook.
  - What it does (unified inbox across email/SMS/Slack/Telegram; your coding agent deploys it into your AWS in 20 min).
  - Why you built it (pivot from FreeMail, market commoditization).
  - What's unique (FSL license, agent-deployable, AWS-native).
  - Link to repo + AGENT.md + screencast.
  - Invitation to ask questions in comments; you'll be around for 24h.
- **First-comment plant:** immediate HN-style technical deep-dive comment explaining a subtle architectural trade-off. Shows you actually built it. Seeds quality discussion.

**Posting strategy:**
- Post at 09:15 UTC Tuesday for optimal US/EU overlap.
- Do NOT ask anyone to upvote — HN shadow-bans this.
- Be present in the thread for 24h.

**Commit:** `docs(phase6): show HN post draft + first-comment plant`

---

## Task 8: Product Hunt launch

**File:** `landing/blog/2026-05-XX-product-hunt.md`

- 60-char tagline: `Your coding agent's new communications hub — email, SMS, Slack, all on AWS.`
- 260-char description with the hook.
- 5 screenshots: landing page, CLI bootstrap, unified inbox UI, Slack integration, architecture diagram.
- Maker comment scheduled for T+0 explaining the "why" in founder voice.
- Hunter: self-hunt (or coordinate with a well-known PH hunter if one of your customers qualifies).

**Commit:** `docs(phase6): Product Hunt launch assets`

---

## Task 9: Seed community engagement

**Deliverables:**
- Open GitHub issue template `new-adapter.md` — a step-by-step guide for contributing an adapter, linking to the spec §4 and the Telegram adapter as the template.
- Open an issue: `[bounty] Discord adapter — $500 bounty paid on merge, scaffolding in adapters/discord/`.
- Open an issue: `[bounty] Postal mail (Lob) adapter — $1,000 bounty paid on merge`.
- Discord server + invite link in README.
- Follow/respond policy: triage all issues and PRs within 48 business hours during the first 60 days.

**Commit:** `docs(phase6): contribution templates + adapter bounties + community channels`

---

## Task 10: Metrics setup

**File:** `cdk/lib/stacks/agentcomms-telemetry-stack.ts`

Set up public (or semi-public) metrics so the launch narrative has a feedback loop:
- CloudWatch metric for "bootstraps completed successfully" (from the smoke-test phase on hosted), published weekly on the landing page.
- GitHub stars/forks tracked via Octokit → simple bar chart on landing page.
- Adapter-install count (if hosted signups pick a channel).

**Commit:** `feat(phase6): launch telemetry — bootstrap success count, GH stars, adapter adoption`

---

## Task 11: Launch day checklist

**File:** `docs/runbooks/launch-day.md`

Hour-by-hour runbook for the Show HN + Product Hunt day (Week 5):

```
T-24h: Final blog post review. Final screencast review. Push all to production.
T-4h:  Pre-post checks: agentcomms bootstrap smoke test passes; api.agentcomms.dev health green; all adapter health_checks green.
T:     09:15 UTC — post Show HN.
T+2m:  Post first-comment plant.
T+5m:  Post to X, LinkedIn, subreddits (r/selfhosted, r/ClaudeAI, r/LocalLLaMA).
T+30m: Post Product Hunt.
T+1h — T+24h: Respond to every HN/PH comment. Fix any docs issues reported.
T+24h: Retrospective note.
```

**Commit:** `docs(phase6): launch-day runbook`

---

## Phase 6 exit criteria

- [ ] Screencast published (YouTube) and embedded on landing page
- [ ] 3 example projects runnable end-to-end against a fresh deploy
- [ ] Blog post, Show HN post, Product Hunt assets all written and committed
- [ ] Community channels live (Discord, issue templates, bounties)
- [ ] Launch-day runbook rehearsed (one dry run)
- [ ] Launch executed: Show HN + Product Hunt live same day
- [ ] First-48h metrics captured (traffic, signups, bootstraps-completed, adapter PRs opened)

---

## 90-day post-launch success metrics (per spec §7.6)

- [ ] ≥ 50 distinct bootstraps completed on hosted (signals product-agent-deployable story is real)
- [ ] ≥ 1 external adapter PR merged (Discord or WhatsApp — signals the adapter SDK works for people who don't have the original context)
- [ ] ≥ 500 GitHub stars (signals narrative is resonant)
- [ ] `api.victorymail.dev` 410'd on schedule (Week 12); no customer complaints post-sunset (signals migration succeeded)
- [ ] ≥ 5 paying Developer-tier signups from launch traffic (signals hosted value prop holds up)

---

*End Phase 6 plan. Estimated calendar: 2 weeks of prep + 1 launch day + 1 week of post-launch iteration. Front-load content; final week reserved for fixing whatever breaks under launch load.*
