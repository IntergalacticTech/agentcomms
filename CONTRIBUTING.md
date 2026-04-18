# Contributing to AgentComms

Thanks for your interest in contributing. AgentComms is source-available under FSL-1.1-Apache-2.0. External contributions are welcome and, once merged, are governed by the same license.

## Quick start

```bash
git clone https://github.com/IntergalacticTech/FreeMail.ai
cd FreeMail.ai
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                     # 277 tests should pass
```

For CDK/infrastructure work you also need Node 20+, AWS CDK v2, and Docker.

## What to work on

The best place to look for work:
- [GitHub Issues](https://github.com/IntergalacticTech/FreeMail.ai/issues) tagged `good first issue` or `help wanted`
- New channel adapters (see "Adding a channel adapter" below)
- Bug fixes in any lambda handler under `lambdas/` or `adapters/`
- SDK improvements under `sdks/`

## How to contribute

1. **Open an issue first** for any non-trivial change. For bug fixes and small improvements, a PR is fine without an issue.
2. **Fork** the repo and create a branch: `git checkout -b feat/my-change`.
3. **Write tests** for your change. All new functionality should have unit tests. Integration tests are required for new adapters.
4. **Run the test suite**: `pytest`. All 277 existing tests must continue to pass, plus new tests for your change.
5. **Open a PR** against `main`. Fill in the PR template. Link any related issues.

## Adding a channel adapter

Channel adapters live in `adapters/<channel>/`. The simplest template is `adapters/telegram/` (~300 lines of Python).

Each adapter must implement the `ChannelAdapter` abstract base from `core/adapters/base.py`:

- `provision(agent, config)` — create the channel resource (e.g., register a Telegram bot webhook)
- `teardown(channel)` — destroy the channel resource
- `inbound_handler(event)` — Lambda handler for inbound messages from the channel
- `send(channel, message)` — send an outbound message
- `health_check(channel)` — return status dict for `agentcomms status`

You also need:
- A CDK construct in `cdk/lib/adapters/<channel>-adapter.ts` that provisions the Lambda + any channel-specific AWS resources
- An entry in `core/adapters/registry.py`
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
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
```

TypeScript:

```typescript
// SPDX-License-Identifier: FSL-1.1-Apache-2.0
```

The `tools/add_spdx_headers.py` script can add headers in bulk if you forget.

## Questions

Open a [GitHub Discussion](https://github.com/IntergalacticTech/FreeMail.ai/discussions) or email `hello@agentcomms.dev`.
