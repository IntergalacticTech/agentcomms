# Making AgentComms public

Runbook for the tasks that need to happen (mostly outside this codebase) to go from "green-on-our-branch" to "public repo users can clone and install."

## 1. Repo rename + visibility flip

The GitHub repo is currently `IntergalacticTech/FreeMail.ai` (private). To match the new product name:

```bash
# Rename on GitHub
gh repo rename agentcomms --repo IntergalacticTech/FreeMail.ai

# OR via the GitHub UI: Settings → General → Rename repository

# After rename, the old URL redirects — but update local remotes:
git remote set-url origin git@github.com:IntergalacticTech/agentcomms.git
```

**Before flipping to public**, verify:

- [ ] `.env` is gitignored and no `.env.*` files are tracked (run `git grep -l 'AWS_ACCESS_KEY' -- '*.env*'` — should be empty)
- [ ] No AWS account IDs in tracked code. An account ID is not a secret, but publishing it needlessly widens your attack surface (it lets outsiders craft ARNs and enumerate your resources). Before going public, move any hardcoded account ID out of `cdk/bin/app.ts` — source it from `CDK_DEFAULT_ACCOUNT`/an env var or CDK context instead of committing the literal. Run `git grep -nE '[0-9]{12}'` and confirm nothing real remains.
- [ ] No real API keys in fixtures — the `ak_live_...` in `project_agentcomms_phase1_status.md` is a memory file (gitignored in `.claude/`); confirm no live key is in the repo via `git grep -E 'ak_live_[A-Za-z0-9]{20,}'` (this matches real base62 keys but not the `ak_live_YOUR_ORG_KEY_HERE` placeholder used in the docs — it should return zero hits)
- [ ] No internal-only docs in `docs/` — `BUILD_PLAN.md` and `ARCHITECTURE.md` are fine to ship; delete `docs/superpowers/` before going public if you'd rather not publish the brainstorming artifacts (they're fine to keep, they just show your work)
- [ ] LICENSE, NOTICE, README, AGENT.md, CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md all exist at repo root

Then in GitHub Settings → General → Danger Zone → Change visibility → Public.

## 2. Publish the CLI to npm

```bash
cd cli
# first-time publish: npm needs to know about the @agentcomms scope
npm login
npm whoami                                # verify
npm publish --access public               # scoped packages default to private; --access public is required
```

The `files` list in `cli/package.json` only includes `dist/`, `README.md`, `LICENSE`. Before publishing, copy the root LICENSE into `cli/`:

```bash
cp LICENSE cli/LICENSE
```

After publish:
```bash
npm view @agentcomms/cli                  # verify the tarball contents look right
```

Users can then run `npm i -g @agentcomms/cli`.

## 3. Publish the Python SDK to PyPI

```bash
cd sdks/python
pip install build twine
python -m build                            # creates dist/agentcomms-1.0.0-py3-none-any.whl + .tar.gz
python -m twine upload dist/*              # authenticates against PyPI credentials
```

The `pyproject.toml` `name = "agentcomms"` must not conflict with an existing PyPI package. Check first:

```bash
pip index versions agentcomms              # should return nothing / "no matching distribution"
```

If the name is taken, pick a scoped alternative (`agentcomms-sdk`, `agentcomms-client`) and update `pyproject.toml` + `__init__.py`.

Users can then run `pip install agentcomms`.

## 4. Publish the Node SDK to npm

```bash
cd sdks/node
npm publish --access public
```

Users can then run `npm i @agentcomms/client`.

## 5. Buy and configure `agentcomms.dev`

Already owned (per project memory: user purchased `agentcomms.dev` during brainstorming). Configure Route 53 + CloudFront:

```bash
# Add to cdk/lib/stacks/agentcomms-landing-stack.ts (new) — deploys landing/index.html to S3 + CloudFront + ACM cert + Route 53 alias

# Once deployed:
#   https://agentcomms.dev → landing page
#   https://docs.agentcomms.dev → documentation (mkdocs or Docusaurus; deferred to Phase 6)
#   https://api.agentcomms.dev → hosted API Gateway (custom domain, deferred to Phase 5 cutover)
#   https://console.agentcomms.dev → hosted developer console
```

For MVP, just:

```bash
# Manual S3 + CloudFront setup if the CDK stack isn't ready yet:
aws s3 mb s3://agentcomms-dev-landing --region us-east-1
aws s3 website s3://agentcomms-dev-landing --index-document index.html
aws s3 cp landing/index.html s3://agentcomms-dev-landing/ --content-type text/html
aws s3api put-bucket-policy --bucket agentcomms-dev-landing --policy '{
  "Version":"2012-10-17",
  "Statement":[{
    "Sid":"PublicReadForStaticWeb","Effect":"Allow","Principal":"*",
    "Action":"s3:GetObject","Resource":"arn:aws:s3:::agentcomms-dev-landing/*"
  }]
}'
# point Route 53 ALIAS A record at the S3 website endpoint
```

Or deploy the static landing content through the AgentComms landing stack for your hosted domain.

## 6. Update email addresses referenced in docs

Several docs and the landing page reference these email addresses:

- `hello@agentcomms.dev` — general inquiries
- `security@agentcomms.dev` — security disclosures
- `conduct@agentcomms.dev` — CoC violations
- `sdks@agentcomms.dev` — SDK maintainer contact

Configure these in AWS SES (either as verified identities that forward to a real inbox, or as provisioned AgentComms inboxes once the hosted service is running). Cheapest option: a single Google Workspace mailbox with aliases.

## 7. GitHub Actions for CI

Two workflows to add to `.github/workflows/`:

- `test.yml` — runs on every PR: `pytest tests/ adapters/` + `cd cdk && npm test` + `cd cli && npm test` + `cd sdks/python && pip install -e . && pytest tests/` + `cd sdks/node && npm test`.
- `publish.yml` — runs on tag `v*`: publishes CLI to npm, Python SDK to PyPI, Node SDK to npm.

Setting up CI credentials:
- `NPM_TOKEN` — npm automation token (scope: publish on @agentcomms/*)
- `PYPI_API_TOKEN` — PyPI scoped token for the `agentcomms` project

## 8. Public launch checklist (Phase 6)

From `docs/superpowers/plans/2026-04-17-agentcomms-phase6-launch.md`:

- [ ] Screencast demonstrating a coding agent deploying AgentComms (3 minutes, YouTube)
- [ ] Launch blog post at `agentcomms.dev/blog/pivot`
- [ ] Show HN post
- [ ] Product Hunt submission
- [ ] Discord community server + invite link in README
- [ ] First community adapter PR (Discord — bounty open)

## Testing checklist before going public

- [ ] `cd cli && npm run build && npm test` — all green
- [ ] `cd sdks/python && pytest tests/` — all green
- [ ] `cd sdks/node && npm test` — all green
- [ ] `pytest tests/core tests/api tests/e2e adapters examples/invoicing-agent examples/slack-standup-bot examples/adapter-template -q` — all green
- [ ] `cd cdk && npx cdk synth --all` — no errors
- [ ] `agentcomms doctor --domain $TEST_DOMAIN --json` — runs cleanly against a fresh AWS sub-account
- [ ] `agentcomms bootstrap ... --json` succeeds end-to-end on a fresh account (see `docs/TESTING.md`)
- [ ] Smoke tests from `docs/TESTING.md` §5-7 all pass
- [ ] `grep -rE 'ak_live_[A-Za-z0-9]{20,}|AKIA|aws_secret' --include='*.py' --include='*.ts' --include='*.md' .` returns zero hits (the pattern matches real base62 keys, not the `ak_live_YOUR_ORG_KEY_HERE` doc placeholder)

Once those pass, the code is ready for a public repo.
