# AgentComms Phase 4: OSS Packaging — Implementation Plan

> **Fidelity note:** B-fidelity. Follow the Phase 1 TDD rhythm.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Spec:** `docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md`
**Predecessors:** Phases 1–3 complete.

**Goal:** Make the repo publicly cloneable, Apache-2.0 licensed, and single-command-deployable by a coding agent. Ship the `agentcomms` CLI + `AGENT.md` + bootstrap flow + SDK v1 packages + MCP server rebuild + console rebrand. At Phase 4 exit, anyone can clone the repo, point their coding agent at it + their AWS credentials, and end up with a working hub in ≤ 25 minutes.

**Architecture:** The repo is restructured but the content is mostly already there. New top-level `cli/` (TypeScript) provides the `agentcomms` binary. New `AGENT.md` at root is the canonical coding-agent guide. License files + SPDX headers added everywhere. SDK v1 packages replace `freemail-*` package names and hit the new API shape.

**Tech Stack:** + Node/TypeScript CLI (commander.js or yargs + chalk for human output + JSON for machine output), Apache-2.0 license text.

---

## File structure changes

### Added

```
LICENSE                               # Apache-2.0
NOTICE                                # third-party attributions
AGENT.md                              # ⭐ coding-agent deployment guide
MIGRATION.md                          # Phase 5 users will read this; start filling in Phase 4
CONTRIBUTING.md  SECURITY.md  CODE_OF_CONDUCT.md  CHANGELOG.md

cli/
├── package.json                      # @agentcomms/cli
├── tsconfig.json
├── src/
│   ├── index.ts                      # binary entry
│   ├── commands/
│   │   ├── bootstrap.ts              # the main command
│   │   ├── doctor.ts                 # preflight only (no deploy)
│   │   ├── status.ts                 # what's deployed, what's verified
│   │   ├── channels.ts               # enable/disable per-channel
│   │   ├── keys.ts                   # CRUD API keys
│   │   ├── agents.ts                 # CRUD agents
│   │   ├── destroy.ts                # cdk destroy with warnings
│   │   └── version.ts
│   ├── lib/
│   │   ├── aws.ts                    # AWS SDK helpers (SES account, STS identity, Route 53 lookups)
│   │   ├── cdk.ts                    # invokes cdk deploy/synth as subprocess
│   │   ├── ndjson.ts                 # phase/status line emitter
│   │   └── config.ts                 # reads ~/.agentcomms/config.json
│   └── tests/

docs/
├── licensing.md                      # plain-English Apache-2.0 explainer
└── adapters/
    ├── email.md
    ├── sms.md
    ├── push.md
    ├── slack.md
    └── telegram.md
```

### Renamed / moved

- `sdks/python/freemail/` → `sdks/python/agentcomms/` (Python package rename)
- `sdks/node/` — Node package renamed from `@freemail/client` to `@agentcomms/client`
- `mcp/` — MCP server name updated from "freemail" to "agentcomms"; tool names renamed `freemail_*` → `agentcomms_*`
- `console/` — rebranded; React app title, logo, copy updated

### Removed in Phase 4

- Old `lambdas/*` handlers that were superseded in Phases 1–3 (if any still remain)

---

## Task 1: License files + SPDX headers

**Files:**
- Create: `LICENSE` (Apache-2.0 canonical text)
- Create: `NOTICE`
- Modify: every `.py` and `.ts` source file — add SPDX header

**Steps:**
1. Use the canonical Apache-2.0 license text.
2. Remove any separate hosted-use or commercial-license template from the public repo.
3. Write `NOTICE` listing every upstream dependency + its license (run `pip-licenses --format=markdown` and `license-checker --production` for Node, paste into NOTICE, manually curate).
4. Script `tools/add_spdx_headers.py`: walks `core/`, `adapters/`, `cli/src/`, `cdk/lib/`, `console/src/`, `sdks/`, `mcp/` and prepends the SPDX header to each source file. Skip files already having one.
5. Run the script; review the diff; commit.
6. **Commit:** `chore(phase4): add Apache-2.0 LICENSE, NOTICE, SPDX headers`

---

## Task 2: `agentcomms` CLI — `bootstrap` command (the headline)

**File:** `cli/src/commands/bootstrap.ts` + supporting lib files.

**Inputs (from CLI flags or env):**
- `--domain` (required): deployer's own domain
- `--region` (default us-east-1)
- `--admin-email` (required)
- `--account` (optional): AWS account ID to validate
- `--profile` (optional): AWS named profile
- `--skip-channels`: comma-separated list of channels to omit
- `--non-interactive`: fails on any prompt; required for agent use
- `--json`: NDJSON on stdout (default when non-interactive)

**Phase-by-phase implementation:**

### Phase A: Preflight (`cli/src/lib/preflight.ts`)
Checks: AWS creds present (STS `GetCallerIdentity`), account matches `--account` if given, region is us-east-1/us-west-2/eu-west-1 (SES inbound availability), Route 53 zone for `--domain` exists in this account, SES account status (sandbox vs production), IAM user/role has required permissions (run a dry-run CDK diff), Node ≥ 20, Python ≥ 3.12, AWS CLI v2, CDK v2, Docker running.

Emit for each check:
```json
{"phase":"preflight","check":"route53_zone","status":"ok","msg":"zone Z123 found"}
{"phase":"preflight","check":"ses_account","status":"warn","msg":"account in sandbox; deployment will continue, production access must be requested manually","cmd":"aws sesv2 put-account-details ..."}
```

Non-interactive mode: any `warn` is OK; any `fail` exits with code 1.

### Phase B: CDK bootstrap
Run `npx cdk bootstrap aws://{account}/{region}` if not already bootstrapped. Stream output to stderr; emit `{"phase":"cdk_bootstrap","status":"ok|fail"}`.

### Phase C: Deploy
Write a config file at `/tmp/agentcomms-deploy.json` containing `{domain, region, admin_email, enabled_channels}`. Invoke `npx cdk deploy --all --require-approval never --context config=/tmp/agentcomms-deploy.json`. Stream per-stack progress as NDJSON:
```json
{"phase":"deploy","stack":"AgentCommsData","status":"running","progress":0.3}
{"phase":"deploy","stack":"AgentCommsData","status":"ok"}
```

Exit with code 2 if any stack fails.

### Phase D: SES identity + DKIM
Create SES identity for `--domain` via Easy DKIM 2048-bit. Write DKIM CNAMEs + SPF TXT + DMARC TXT into the Route 53 zone. Poll `GetEmailIdentity` every 15s until `DkimStatus == SUCCESS`, max 15 min. Emit:
```json
{"phase":"ses","check":"dkim","status":"waiting","msg":"DKIM verification pending (1 of 3 CNAMEs verified)"}
{"phase":"ses","check":"dkim","status":"ok","msg":"DKIM verified"}
```

Exit with code 3 if timeout.

### Phase E: Seed
Invoke `tools/seed_first_org.py` (Python) via subprocess. It creates the first Org + admin API key. The key is echoed to the user **exactly once**:
```json
{"phase":"seed","status":"ok","org_id":"org_01H...","admin_api_key":"ak_live_...","note":"This key is shown once. Store it securely."}
```

### Phase F: Smoke test
Use the admin API key to:
1. `POST /v1/agents` with email provision.
2. Wait for channel status = `active` (up to 60s).
3. `POST /v1/agents/{id}/messages {to: admin_email, body: "AgentComms bootstrap smoke test"}`.
4. Listen for SNS delivery event or DynamoDB status=delivered on the outbound message (up to 60s).
5. Emit `{"phase":"smoke","status":"ok","outbound_message_id":"msg_..."}`.

Exit with code 4 on smoke-test failure (deployment is live but round-trip didn't complete; human attention needed).

### Phase G: Report
Final NDJSON line:
```json
{"phase":"done","status":"ok","api_url":"https://api.acmebot.com/v1","console_url":"https://console.acmebot.com","admin_email":"you@x.com","admin_api_key":"ak_live_...","region":"us-east-1","next_steps":["enable sms: agentcomms channels enable sms","enable slack: agentcomms channels enable slack"]}
```

**Commits (one per phase letter for easy review):**
- `feat(phase4): cli/bootstrap preflight checks`
- `feat(phase4): cli/bootstrap CDK bootstrap + deploy phases`
- `feat(phase4): cli/bootstrap SES identity + DKIM polling`
- `feat(phase4): cli/bootstrap seed first org + admin key`
- `feat(phase4): cli/bootstrap smoke test round-trip`
- `feat(phase4): cli/bootstrap final report + next-steps`

---

## Task 3: `agentcomms` CLI — secondary commands

- `doctor` — runs only Phase A preflight, exits 0/1 based on results.
- `status` — reads the SSM parameter `/agentcomms/{env}/bootstrap/state` + queries CloudFormation stack statuses + SES identity verification status + channel adapter health checks.
- `channels list` — `list_registry()` from `core.adapters.registry`, cross-reference with Channel records per Org.
- `channels enable <channel>` — interactive (or flag-driven) walkthrough for populating the SSM secrets declared in the adapter's manifest. E.g. for Slack: creates the state nonce for the admin's agent, prints the OAuth URL, waits for callback. For Telegram: prompts for a bot token from BotFather.
- `channels disable <channel>` — marks all Channels of that type on all agents as disabled, calls `adapter.teardown(channel)` for each.
- `keys create|list|revoke` — thin wrappers around the API.
- `agents create|list|delete` — thin wrappers around the API.
- `destroy` — runs `cdk destroy --all` with `--yes` confirmation required unless `--non-interactive`. Lists precisely what will and won't be deleted (buckets retained by default, etc.).

**Commit:** `feat(phase4): agentcomms CLI secondary commands (doctor, status, channels, keys, agents, destroy)`

---

## Task 4: `AGENT.md` — the headline deployment guide

**File:** `AGENT.md` (repo root)

**Content structure:**

```markdown
# AGENT.md — Deploy AgentComms into your AWS account

This file is written for coding agents (Claude Code, Cursor, Aider, Codex, etc.).
If you are a human, you can follow it too — it's just terse.

## TL;DR

1. Install: `npm i -g @agentcomms/cli`
2. `agentcomms bootstrap --domain your-domain.com --admin-email you@x.com --non-interactive --json`
3. Wait ≤ 25 minutes.
4. Final NDJSON line contains `admin_api_key`. Store it.

## Preconditions

(explicit checklist — AWS creds, Route 53 zone, region, SES, Node, Python, Docker)

## Commands (exact)

(copy-paste block)

## NDJSON event reference

(every `{"phase":"..."}` line and what it means)

## Exit codes

(the 0/1/2/3/4 contract from Section 5.2 of the spec)

## Top-10 common failures

(grep pattern → cause → fix, for each)

## Enable channels after bootstrap

(per-channel quick-start)

## Teardown

`agentcomms destroy --yes`
```

The document is the single source of truth for agent-driven deployment. Test by running it against a fresh AWS sub-account with Claude Code and recording the transcript.

**Commit:** `docs(phase4): AGENT.md — coding-agent deployment guide`

---

## Task 5: Repo restructure

Move files according to the spec's Section 5.1:

- `lambdas/` → `core/api/` (everything still in `lambdas/` after Phases 1–3) + `adapters/*/` (anything channel-specific).
- `cdk/` stays as `cdk/` (it's already in the right place).
- Create `core/events/` and move webhook fan-out + WS dispatch code there.
- Create `core/data/` (done in Phase 1).
- Remove empty `lambdas/` directory.

Update `pyproject.toml`, all CDK imports, tests.

**Commit:** `refactor(phase4): complete repo restructure to spec §5.1 layout`

---

## Task 6: SDK v1 — Python package `agentcomms`

Rebuild `sdks/python/` as the new `agentcomms` PyPI package:
- Module layout: `agentcomms/{client.py, models.py, resources/{agents,channels,messages,threads,drafts,webhooks,vault,personas,ai,slack,telegram}.py}`.
- API surface mirrors Section 3 of the spec.
- Keep a final-release `freemail` package on PyPI that imports from `agentcomms` and emits a `DeprecationWarning` on import.

**Commit:** `feat(phase4): agentcomms Python SDK v1.0.0; freemail DeprecationWarning shim`

---

## Task 7: SDK v1 — Node package `@agentcomms/client`

Same as Task 6 but for TypeScript. Same deprecation shim for `@freemail/client`.

**Commit:** `feat(phase4): @agentcomms/client Node SDK v1.0.0; @freemail/client deprecation shim`

---

## Task 8: MCP server rebuild

Replace `mcp/` tool names `freemail_*` → `agentcomms_*`. Add new tools for agent CRUD + unified inbox + channel CRUD that didn't exist in the FreeMail MCP. Remove old tools that don't map to the new API.

**Commit:** `feat(phase4): MCP server — new tool names + agent/channel/unified-inbox tools`

---

## Task 9: Console rebrand + redesign

`console/`:
- Replace FreeMail branding, logo, color palette.
- Update landing page of console to show Agents, not Inboxes, as the top nav.
- Add per-channel status views (green/yellow/red dots).
- Add a unified inbox viewer (uses `GET /v1/agents/{id}/messages`).
- Add a channel-native sub-surface viewer for Slack workspaces + Telegram chats.
- Keep billing / settings pages.

**Commit:** `feat(phase4): console rebrand + Agent-centric UX`

---

## Task 10: Landing page at `agentcomms.dev`

`landing/index.html` rebuilt. Lead with the headline from the spec: *"Point your coding agent at this repo and your AWS account. Twenty minutes later, your agent has its own email address, phone number, and Slack identity — running in your cloud, under your control."*

Include: the 3-command block, the AGENT.md link, the full feature list, Apache-2.0 license link, GitHub repo link.

**Commit:** `feat(phase4): new agentcomms.dev landing page`

---

## Task 11: `docs/licensing.md` + per-adapter docs

- `docs/licensing.md`: plain-English explainer of Apache-2.0 — what you can do, notice obligations, patent grant, trademarks, and contribution terms.
- `docs/adapters/{email,sms,push,slack,telegram}.md`: per-channel setup guides + SSM secret names + known limits.

**Commit:** `docs(phase4): licensing explainer + per-adapter setup guides`

---

## Task 12: CI/CD updates

- Add a GitHub Actions workflow `bootstrap-smoke.yml` that runs `agentcomms bootstrap` against a sandbox AWS sub-account on a schedule (daily) and on every PR to `main`. This is how we enforce the "≤ 25 min, >95% success rate" exit criterion.
- Add `publish-sdks.yml` that publishes Python and Node SDKs on tag.
- Mark `deploy-hosted.yml` as Victory-only (check repo owner); on forks it becomes a no-op.

**Commit:** `ci(phase4): bootstrap smoke workflow + SDK publishing + victory-only guard`

---

## Phase 4 exit criteria

- [ ] `LICENSE` (Apache-2.0) in place with correct metadata
- [ ] SPDX headers on every source file
- [ ] `agentcomms bootstrap` succeeds end-to-end on a fresh AWS sub-account in ≤ 25 min (measured via CI)
- [ ] `AGENT.md` tested by running Claude Code against it unaided, transcript recorded
- [ ] `agentcomms-python` v1.0.0 on PyPI, `@agentcomms/client` v1.0.0 on npm
- [ ] MCP server published with new tool names
- [ ] Console rebranded and deployed at `console.agentcomms.dev`
- [ ] Landing page live at `agentcomms.dev`
- [ ] Repo structure matches spec §5.1 exactly

---

*End Phase 4 plan. Estimated calendar: 3–4 weeks. This phase is where public perception is set; leave time for polish.*
