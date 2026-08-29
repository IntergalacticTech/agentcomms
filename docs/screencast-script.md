# Screencast Script: "Claude Code Deploys AgentComms End-to-End"

**Duration:** 3 minutes (180 seconds)
**Export:** 1920×1080, 60 fps, H.264 (YUV 4:2:0, CRF 18), AAC 192 kbps stereo
**Host:** YouTube primary + self-hosted MP4 on agentcomms.dev
**Voice-over:** Human (not AI TTS — authenticity matters)

---

## Overview

| Section | Timestamp | Duration | Theme |
|---------|-----------|----------|-------|
| A — Problem framing | 0:00–0:15 | 15 s | Hook |
| B — Setup | 0:15–0:45 | 30 s | Context |
| C — The uncut take | 0:45–2:30 | 105 s | The money shot |
| D — Payoff | 2:30–3:00 | 30 s | "It works" |

---

## Section A — Problem Framing (0:00–0:15)

### Shot list

| Time | What is on screen |
|------|-------------------|
| 0:00 | Black screen. Fade in: white text on dark background — "Your AI agent needs to talk to the world." |
| 0:05 | Cut to: a simple diagram showing an AI agent icon connected to Email, SMS, Slack, Telegram icons — all with question marks. |
| 0:10 | Text fades, replaced by: "What if it could deploy its own communications hub?" |
| 0:14 | Text fades. Cut to: a clean terminal window, cursor blinking. |

### Voice-over (word-for-word)

> "AI agents are everywhere. But connecting them to the real world — email, SMS, Slack — still means building and hosting that infrastructure yourself. What if your coding agent could deploy the whole thing into your own AWS account in 20 minutes?"

### On-screen annotations

- 0:05: Label each icon in the diagram. No animation needed — static callouts.
- 0:10: Keep the question on screen long enough to read twice.

### Music

- Start: subtle ambient pad at -18 dB. Stays under voice throughout Section A.

---

## Section B — Setup (0:15–0:45)

### Shot list

| Time | What is on screen |
|------|-------------------|
| 0:15 | Terminal: `aws sts get-caller-identity --profile agentcomms-test` |
| 0:19 | Response JSON shows a clean sub-account (no existing resources). |
| 0:24 | Split screen: left = terminal; right = text editor showing `examples/coding-agent-self-deploys/agent-prompt.md` |
| 0:30 | Zoom into the prompt text in the editor. Highlight the key parameters: profile, domain, admin email. |
| 0:38 | Terminal on left: `claude` CLI starts up. |
| 0:42 | Claude Code reads the prompt. Cursor blinking on the first line. |

### Voice-over (word-for-word)

> "Fresh AWS sub-account. A domain we control. Claude Code open in the repo root. We paste one paragraph — the exact prompt in AGENT.md — and let it go."

### On-screen annotations

- 0:24: Callout box: "One prompt. That's all."
- 0:30: Highlight `--profile agentcomms-test`, `--domain agentcomms-test-demo.com` in yellow.
- 0:38: Callout: "No scripts. No Terraform files to write. Just Claude."

### Music

- 0:15–0:45: Same ambient pad. Slightly increase presence at 0:38 as Claude Code starts.

---

## Section C — The Uncut Take (0:45–2:30)

> **Direction note:** Record the real bootstrap against a clean account. Do not edit out
> any phase. Speed up to 3× for the CloudFormation wait period (1:20–2:00 approx); play
> at real speed for preflight checks and the API key reveal.

### Shot list

| Time | What is on screen | Playback speed |
|------|-------------------|----------------|
| 0:45 | Claude Code reads AGENT.md — visible in terminal output. | 1× |
| 0:52 | Claude runs `agentcomms bootstrap ...` — command appears. | 1× |
| 0:58 | NDJSON events begin streaming: `{"event":"start",...}` | 1× |
| 1:05 | `{"event":"phase","phase":"preflight","status":"running",...}` | 1× |
| 1:12 | Preflight checks pass: `{"event":"check","name":"sts:GetCallerIdentity","status":"ok",...}` | 1× |
| 1:18 | DNS phase: hosted zone creating. | 1× |
| 1:22 | `{"event":"dns_delegation",...,"nameservers":[...]}` | 1× |
| 1:28 | SES phase: email identity creating. | 1× |
| 1:35 | Stacks phase begins: `{"event":"stack","name":"agentcomms-data","status":"CREATE_IN_PROGRESS",...}` | 1× → ramp to 3× |
| 1:38 | CloudFormation stacks deploying — progress events scroll. | 3× |
| 2:00 | `agentcomms-data CREATE_COMPLETE` | 3× → ramp back to 1× |
| 2:04 | `agentcomms-api CREATE_IN_PROGRESS` — final stack | 1× |
| 2:08 | `agentcomms-api CREATE_COMPLETE` | 1× |
| 2:12 | Seed phase: admin org + API key creating. | 1× |
| 2:16 | Smoke test: inbox created, message sent, inbox deleted. | 1× |
| 2:22 | **THE MONEY SHOT:** `{"event":"complete","api_key":"ak_live_..."}` scrolls into view. | 1× |
| 2:25 | Frame freezes on the `api_key` line. Zoom in 1.5×. | FREEZE |
| 2:28 | Callout box over the key: "Your API key. Shown once." | FREEZE |
| 2:30 | Screen un-freezes. Claude Code prints its summary. | 1× |

### Voice-over (word-for-word)

> *(0:45)* "Claude reads AGENT.md, understands what to do, and fires the bootstrap command. No hand-holding."
>
> *(1:05)* "Preflight checks. Credentials. Permissions. SES sandbox status. All green."
>
> *(1:22)* "Route 53 hosted zone is live. These are the nameservers — you'd point your registrar here. Normally takes a few minutes; we pre-delegated for this take."
>
> *(1:35)* "CloudFormation stacks are deploying. DynamoDB, S3, KMS, Lambda, API Gateway, Cognito. 45 resources across two stacks. We'll speed this up..."
>
> *(2:04)* "...and we're back. Both stacks complete. Seeding the admin org now."
>
> *(2:22)* "There it is."
>
> *(2:28 — pause for effect, silence)*
>
> *(2:30)* "Your API key. The smoke test passed. AgentComms is live in your account."

### On-screen annotations

| Timestamp | Annotation |
|-----------|------------|
| 1:05 | Callout on `"status":"ok"` lines: "Real IAM checks — not mocked." |
| 1:22 | Callout on `dns_delegation` event: "Add these NS records at your registrar." |
| 1:38 | Speed indicator badge in corner: "3× speed — CloudFormation deploying" |
| 2:00 | Speed indicator badge: "1× speed" |
| 2:22 | Yellow highlight on entire `complete` JSON line. |
| 2:25 | Zoom 1.5× on `api_key` field. Callout: "Your API key. Save this." |

### Music

- 0:45–1:35: Ambient pad continues, slightly building.
- 1:35–2:15: Upbeat, purposeful underscore at -14 dB. Swells at 2:15.
- 2:15–2:25: Music swells to -10 dB.
- 2:25–2:30: **SILENCE.** The API key reveal should land in dead silence.
- 2:30–2:45: Music resumes quietly at -18 dB.

---

## Section D — Payoff (2:30–3:00)

### Shot list

| Time | What is on screen |
|------|-------------------|
| 2:30 | New terminal tab. `export AGENTCOMMS_API_KEY="ak_live_..."` |
| 2:34 | `curl "$BASE_URL/agents" -H "Authorization: Bearer $AGENTCOMMS_API_KEY"` - runs, returns an empty `agents` array. |
| 2:40 | Short Python snippet (pre-written in editor): create agent, provision email channel, send email, list messages. |
| 2:45 | Terminal: runs the snippet. Agent created. Email sent. |
| 2:50 | Inbox listing shows the sent message AND a reply that arrives live (pre-arranged test). |
| 2:55 | Final shot: `agent.messages.list()` output in terminal showing both messages. Direction=inbound and outbound. |
| 2:58 | Fade to black. Text: "agentcomms.dev" |

### Voice-over (word-for-word)

> *(2:30)* "Let's use it. Export the key, hit the API."
>
> *(2:34)* "Empty inbox. Clean slate. We'll send a real email..."
>
> *(2:45)* "...and watch it appear in the unified inbox. There's the outbound. And here comes the reply."
>
> *(2:55)* "Two messages. One inbox. Your agent, talking to the world. Deploy yours at agentcomms.dev."

### On-screen annotations

- 2:34: Callout on the API response: "Real REST call. Real AWS infrastructure."
- 2:50: Callout on inbound message: "Reply arrived via SES — no polling, just events."
- 2:58: Overlay text: "agentcomms.dev — deploy in 20 minutes"

### Music

- 2:30–2:58: Upbeat outro at -14 dB, resolves to a clean finish at 2:58.
- 2:58: Hard cut to silence as text appears.

---

## Export Settings

| Setting | Value |
|---------|-------|
| Resolution | 1920×1080 |
| Frame rate | 60 fps |
| Codec | H.264 (YUV 4:2:0) |
| Quality | CRF 18 (visually lossless for text/terminal content) |
| Audio codec | AAC-LC |
| Audio bitrate | 192 kbps stereo |
| Container | MP4 (ISOBMFF) |
| Color space | Rec.709 |

### Additional exports

| Format | Use |
|--------|-----|
| MP4 H.264 (above) | YouTube upload |
| MP4 H.265 (CRF 22) | Self-hosted on agentcomms.dev (smaller file) |
| GIF 10-second clip (2:20–2:30) | README + landing page hero |

### YouTube metadata

- **Title:** AgentComms: Your coding agent deploys its own AWS communications hub (live demo)
- **Description:** First paragraph: the one-line hook. Second paragraph: link to repo + AGENT.md. Third: timestamps for each section.
- **Thumbnail:** The frozen frame at 2:25 with the API key visible (key redacted with blur) + overlay text "20 minutes. Your AWS account."
- **Tags:** agentcomms, aws, claude, coding agent, ai agent, email api, slack api, infrastructure

---

## Production Checklist

- [ ] Record against a clean AWS sub-account (verify with `aws sts get-caller-identity`)
- [ ] Pre-delegate DNS before recording (avoids waiting for propagation on-screen)
- [ ] Set terminal font size to 20+ pt (readable at 1080p)
- [ ] Use a dark terminal theme with high contrast (e.g. Dracula or Catppuccin Mocha)
- [ ] Disable notifications on screen before recording
- [ ] Record the full bootstrap in one uncut take; only apply speed change in post
- [ ] Redact API key in thumbnail; keep it visible in the video (it's a demo key — revoke after recording)
- [ ] Add captions/subtitles for accessibility
- [ ] Upload both the full MP4 and the 10-second GIF to the repo's `landing/assets/` directory
