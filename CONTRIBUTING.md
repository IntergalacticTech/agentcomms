# Contributing to AgentComms

Thanks for your interest in contributing. AgentComms is open source under Apache-2.0. External contributions are welcome and, once merged, are governed by the same license.

## Quick start

```bash
git clone https://github.com/IntergalacticTech/FreeMail.ai
cd FreeMail.ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest tests/core tests/api tests/e2e adapters examples/invoicing-agent examples/slack-standup-bot examples/adapter-template
```

For CDK/infrastructure work you also need Node 20+, AWS CDK v2, and Docker.

## What to work on

The best place to look for work:
- [GitHub Issues](https://github.com/IntergalacticTech/FreeMail.ai/issues) tagged `good first issue` or `help wanted`
- New channel adapters (see "Adding a channel adapter" below)
- Bug fixes in API handlers under `core/api/` or adapter code under `adapters/`
- SDK improvements under `sdks/`

## How to contribute

1. **Open an issue first** for any non-trivial change. For bug fixes and small improvements, a PR is fine without an issue.
2. **Fork** the repo and create a branch: `git checkout -b feat/my-change`.
3. **Write tests** for your change. All new functionality should have unit tests. Integration tests are required for new adapters.
4. **Run the relevant tests**. The core suite is `python -m pytest tests/core tests/api tests/e2e adapters examples/invoicing-agent examples/slack-standup-bot examples/adapter-template`; SDK and CLI changes have package-local test commands.
5. **Open a PR** against `main`. Fill in the PR template. Link any related issues.

## Adding a channel adapter

Channel adapters can live in this repo under `adapters/<channel>/` or in an external package that registers a Python entry point in the `agentcomms.adapters` group. Start with [docs/adapter-authoring.md](./docs/adapter-authoring.md) and [examples/adapter-template/](./examples/adapter-template/) for the external package path. The simplest in-repo reference is `adapters/telegram/`.

Each adapter must implement the `ChannelAdapter` abstract base from `core/adapters/base.py`:

- `provision(agent, config)` — create the channel resource (e.g., register a Telegram bot webhook)
- `teardown(channel)` — destroy the channel resource
- `ingest(payload)` — normalize inbound channel events into `UnifiedMessage`
- `send(channel, message)` — send an outbound message
- `health_check(channel)` — return status dict for `agentcomms status`

You also need:
- CDK wiring in `cdk/lib/adapters/<channel>-adapter-stack.ts` or `cdk/lib/stacks/agentcomms-api-stack.ts` when the adapter needs AWS resources
- An in-repo `manifest.toml` or external package entry point
- Tests in `tests/adapters/test_<channel>.py`
- Docs in `docs/adapters/<channel>.md` covering SSM secret names, limits, and setup steps

Discord scaffolding is already at `adapters/discord/` — it's the easiest starting point.

## Code style

- Python: follow existing style (no formatter enforced yet; PEP 8 approximately)
- TypeScript (CDK + CLI): prettier defaults; `npm run lint` in `cdk/`
- Commit messages: `type(scope): description` — e.g., `feat(adapters): add Discord adapter`
- Keep PRs focused. One logical change per PR.

## SPDX headers

Every new source file must include an SPDX header. Python:

```python
# SPDX-License-Identifier: Apache-2.0
```

TypeScript:

```typescript
// SPDX-License-Identifier: Apache-2.0
```

The `tools/add_spdx_headers.py` script can add headers in bulk if you forget.

## Questions

Open a [GitHub Discussion](https://github.com/IntergalacticTech/FreeMail.ai/discussions) or email `hello@agentcomms.dev`.
