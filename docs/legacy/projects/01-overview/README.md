# 01 - FreeMail Overview

## Current Product Identity

- **Product name**: `FreeMail`
- **Temporary deploy/test domain**: `victorymail.dev`
- **Target public brand/domain**: `freemail.dev` when acquired
- **Legacy name in inherited docs**: `AgentMail`

This document is the canonical product overview for the current planning direction.

---

## What Is FreeMail?

FreeMail is an API-first email platform for AI agents and automation systems.

It gives developers:

- programmatic inbox creation
- send and receive email via API
- threads, attachments, and webhooks
- custom domains
- agent-friendly wait/OTP workflows
- an MCP server for tool-based agent access

The initial product is deliberately simple: make core email infrastructure easy and cheap enough that developers can try it without procurement friction.

---

## The Problem

AI agents need email, but traditional providers are a poor fit.

- **Too expensive per inbox**: human-oriented mailbox pricing breaks down at agent scale.
- **No fast provisioning API**: creating mailboxes usually requires admin console work.
- **Automation-hostile auth**: OAuth and interactive consent flows are built for humans.
- **Human-oriented usage patterns**: rate limits and workflows assume a person, not a fleet of agents.
- **No agent-native DX**: waiting for an email, extracting an OTP, or wiring an inbox into an MCP client is still awkward with traditional tools.

---

## The Solution

FreeMail solves the problem with a launch strategy built around distribution and cost discipline.

### Core Product Principles

1. **Launch free SaaS first.**
   The first product should be usable without AWS Marketplace, procurement, or sales.

2. **Use custom domains as the wedge.**
   Offering custom domains on the free tier is a meaningful differentiator and a strong proof-of-value moment.

3. **Keep AI paid-only.**
   Bedrock and OpenSearch are the first features with meaningful variable cost. They should not be bundled into free usage.

4. **Keep self-serve pricing simple.**
   Start with `Free` and `Pro`. Avoid a large self-serve tier ladder before demand exists.

5. **Use AWS Marketplace as the path above Pro.**
   Marketplace is for customers who need more mailboxes, more domains, more throughput, heavier AI usage, or AWS-native procurement.

---

## Target Users

### Primary

- AI agent builders
- developer tools teams
- workflow automation products
- platforms that need many low-friction inboxes

### Secondary

- testing and staging systems that need disposable inboxes
- SaaS products that need per-customer mailboxes
- teams moving email-based workflows into software

---

## Competitive Position

### AgentMail.to

AgentMail.to is the closest product analogue on the core email-infrastructure shape.

Our intended differentiation:

- freer entry point
- more generous custom-domain access on free
- lower-cost self-serve paid path
- AWS Marketplace migration path once usage exceeds Pro

### Lumbox

Lumbox is a strong competitor on agent ergonomics and workflow-oriented features.

Features worth copying or matching early:

- OTP extraction
- wait/long-poll flows
- MCP-first tooling
- prompt-injection-aware parsing

Areas we should **not** chase on the launch path:

- browser automation scope
- credential vault scope
- self-hosting before product-market signal

---

## Current Launch Scope

### Must-Have for Launch

- account signup and login
- API key issuance
- inbox CRUD
- send email
- receive email
- threads and attachments
- webhooks
- custom domains
- wait-for-email
- OTP extraction
- MCP server
- developer console
- free-tier quotas

### Paid-Only at Launch

- semantic search
- AI categorization
- structured extraction
- any Bedrock-backed parsing pipeline beyond low-cost regex-style OTP handling

### Explicitly Deferred

- IMAP/SMTP
- multi-region
- enterprise SSO/SAML
- audit logging beyond basic operational logging
- compliance packaging
- self-hosting

---

## Product Capabilities by Stage

### Launch Capabilities

1. **Programmatic inboxes**
   - create inboxes by API
   - manage status and metadata
   - support platform-domain and custom-domain addresses

2. **Send and receive**
   - SES-backed outbound delivery
   - SES inbound via receipt rules
   - attachments and MIME handling

3. **Threads and retrieval**
   - message listing
   - thread grouping
   - attachment access

4. **Integrations**
   - webhooks
   - MCP server
   - wait/OTP endpoints

5. **Self-service domains**
   - DNS-based verification
   - DKIM/SPF/DMARC guidance
   - inbound and outbound on customer domains

### Post-Launch Paid Capabilities

1. **AI search**
2. **AI categorization**
3. **Structured extraction**
4. **Higher throughput and quota levels**

---

## API Shape

The initial API should stay focused.

### Core Endpoints

- `POST /v1/organizations`
- `POST /v1/api-keys`
- `POST /v1/inboxes`
- `GET /v1/inboxes`
- `GET /v1/inboxes/{inbox_id}`
- `PATCH /v1/inboxes/{inbox_id}`
- `POST /v1/inboxes/{inbox_id}/messages`
- `GET /v1/inboxes/{inbox_id}/messages`
- `GET /v1/inboxes/{inbox_id}/threads`
- `POST /v1/domains`
- `GET /v1/domains/{domain_id}/verify`
- `POST /v1/webhooks`
- `GET /v1/inboxes/{inbox_id}/wait`
- `GET /v1/inboxes/{inbox_id}/otp`

### Paid AI Endpoints

- `POST /v1/inboxes/{inbox_id}/search`
- `PUT /v1/inboxes/{inbox_id}/categorization`
- `PUT /v1/inboxes/{inbox_id}/extraction`

---

## Business Model

### Direct SaaS First

The first commercial model is direct SaaS.

### Launch Tiers

| Tier | Purpose | Key traits |
|------|---------|------------|
| `Free` | onboarding and proof of value | generous limits, custom domain access, no AI |
| `Pro` | paid self-serve | more inboxes, more domains, more throughput, paid AI access |

Pricing is intentionally not frozen yet. The guiding rule is that Pro should be clearly competitive with the current market while still covering non-AI AWS costs comfortably.

### Marketplace After Pro

AWS Marketplace is for customers who:

- exceed Pro quotas
- need higher mailbox/domain counts
- need higher send/receive throughput
- use AI heavily enough that committed contracts make sense
- prefer procurement through AWS

Marketplace should be implemented as a migration path, not as the initial signup experience.

---

## Current Tier Philosophy

### Free

- generous enough to attract developers
- custom domains included
- hard quota enforcement
- no Bedrock-backed AI

### Pro

- more inboxes
- more domains
- higher throughput
- access to AI
- still self-serve

### Marketplace

- starts where Pro stops
- better fit for higher-volume and procurement-led buyers
- supports private offers and committed spend

---

## Success Metrics

### Product Metrics

- time to first inbox under 5 minutes
- time to first sent email under 10 minutes
- free users successfully onboarding custom domains
- users exercising wait/OTP and MCP flows in real usage

### Commercial Metrics

- meaningful free-tier adoption
- clear upgrade pressure from free to Pro
- identifiable set of users who exceed Pro and justify Marketplace work

### Cost Metrics

- free-tier cost ceiling remains bounded
- non-AI free usage remains cheap to serve
- AI usage is only unlocked once billing and quotas exist

---

## What Not to Optimize Yet

Do not spend launch time optimizing for:

- enterprise compliance packaging
- multi-region
- IMAP/SMTP compatibility
- elaborate Marketplace public-tier pricing
- advanced AI workflows

The product needs real usage first.
