# AgentComms Licensing

**AgentComms is source-available software.** This document explains what that
means in plain English — what you can do, what you cannot do, and how to get
permission to do more.

---

## What AgentComms is licensed under

AgentComms is licensed under the **Functional Source License, Version 1.1,
with an Apache 2.0 Future License** (SPDX: `FSL-1.1-Apache-2.0`). FSL is a
source-available license created by Sentry. The short version: you can read
the code, run it, modify it, and contribute back — for almost any purpose —
except operating it as a competing paid hosted service. Two years after each
file is committed, that restriction expires and the code becomes Apache 2.0.

Full license text: [LICENSE](../LICENSE)

---

## What you can do

The following are **explicitly permitted** — no commercial license needed:

- **Self-host for your own organization.** Deploy AgentComms in your own AWS
  account at any scale. Use it for all of your agents, all of your teammates,
  your whole company. The self-deploy path (`agentcomms bootstrap`) is the
  whole point.

- **Use it personally.** Running AgentComms for your own coding agent,
  side-project, or personal automation is fully permitted.

- **Modify it freely.** Fork the repo, add adapters, rip out what you don't
  need, customize the CDK stacks. Your modifications are yours.

- **Redistribute modifications under the same license.** Share your fork,
  submit a PR, publish your adapter as a separate repo — as long as you
  include the FSL license and copyright notices.

- **Build products that use AgentComms as a component.** If your SaaS product
  internally uses AgentComms to handle agent communication, that is permitted
  as long as you are not selling AgentComms itself (or a wrapper around it)
  as a hosted service to third parties.

- **Non-commercial education and research.** University courses, academic
  papers, conference demos — all fine.

- **Professional services.** Integrators, consultants, and agencies may
  deploy and configure AgentComms for their clients.

---

## What you cannot do

**Without a commercial license, you may not:**

- Offer AgentComms (or a modification or extension of it) as a **paid hosted
  service to third parties.** In other words: you cannot run an
  "AgentComms-as-a-service" business and charge customers for access to it.

  Examples of Competing Use:
  - A multi-tenant SaaS where customers pay a subscription to use a hosted
    AgentComms hub you operate.
  - A managed-service offering where you run AgentComms in customers' AWS
    accounts for a fee and the core value is the AgentComms hub itself.

  If you are unsure whether your use case qualifies as Competing Use, email
  `commercial@agentcomms.dev` and ask. We are friendly and will give you a
  straight answer.

---

## When this code becomes Apache 2.0

FSL is designed to eventually become an open-source license. Every file in
this repository will become Apache 2.0 **two years after the commit that
introduced that file.**

This means:
- Files committed today become Apache 2.0 in 2028.
- Files committed next year become Apache 2.0 in 2029.
- The Change Date is per-file, not per-repo.
- After the Change Date, you can do anything Apache 2.0 allows — including
  offering the code as a paid hosted service.
- Victory is the only party that can accelerate this (by re-licensing a
  specific version sooner). We have no plans to do so.

The practical implication: if you clone this repo today and wait two years,
you will have a fully open-source codebase with no restrictions.

---

## Getting a commercial license

If you want to operate AgentComms as a paid hosted service for third parties,
you need a commercial license.

**Contact:** `commercial@agentcomms.dev`

In your email, briefly describe:
1. What you are building
2. Your expected scale (number of orgs, agents, message volume)
3. Your preferred fee model (upfront, annual, revenue share, or combination)

Typical commercial license terms include:
- A license fee (upfront and/or annual) or a revenue-share arrangement
- The right to operate AgentComms as a paid hosted service in a defined
  territory
- Attribution requirement ("Built on AgentComms")
- Standard warranty and liability terms (see `LICENSE.commercial` template)

We keep the process lightweight. Most deals close in days, not months.

A template agreement is included in this repository at
[LICENSE.commercial](../LICENSE.commercial).

---

## Comparison to other licenses

| License | Can self-host? | Can sell as SaaS? | Becomes OSS? | CLA required? |
|---------|---------------|-------------------|--------------|---------------|
| MIT / Apache 2.0 | Yes | Yes | Already is | No |
| AGPL | Yes | Triggers copyleft | Already is | Varies |
| SSPL | Yes | Triggers copyleft | No | No |
| ELv2 (Elastic) | Yes | No | No | No |
| **FSL-1.1-Apache-2.0** | **Yes** | **Commercial license** | **Yes, after 2 years** | **No** |

**How FSL differs:**
- Unlike MIT/Apache: FSL prevents competitors from operating a paid hosted
  version without a license.
- Unlike AGPL: FSL does not require you to open-source your modifications
  when you run a service. It simply prevents you from *selling* the service
  without a license.
- Unlike SSPL: FSL's restriction is narrow (hosting-as-a-service), not broad
  (all infrastructure software used to run the service).
- Unlike ELv2: FSL includes a time-limited restriction that expires, giving
  the code an eventual open-source lifecycle. ELv2 does not.
- Unlike all of the above: FSL is recognized on the SPDX license list, making
  it easy to flag in automated dependency scanners.

The FSL was created by Sentry and is used by several successful open-core
companies. Its intent is to protect a narrow commercial moat (hosted service)
while keeping the code as open as possible for everyone else.

---

## Questions?

- Open a GitHub Issue: [github.com/victoryintl/agentcomms/issues](https://github.com/victoryintl/agentcomms/issues)
- Commercial inquiries: `commercial@agentcomms.dev`
- Security disclosures: `security@agentcomms.dev`
