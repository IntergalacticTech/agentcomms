# Public Release Runbook

AgentComms is licensed under Apache-2.0 and is intended to be public OSS. This runbook covers the remaining external launch work around GitHub visibility, package registries, and the public website.

## Current Launch Surface

- Product name: `AgentComms`
- Target repo: `IntergalacticTech/agentcomms`
- License: Apache-2.0
- Hosted API default: `https://api.agentcomms.dev/v1`
- Public landing source: [`landing/`](../landing/)
- Landing deployment stack: `AgentCommsLanding`
- Core production stacks: `AgentCommsData`, `AgentCommsEvents`, `AgentCommsApi`, `AgentCommsAdapters`, and adapter sub-stacks

The landing stack deploys the checked-in static site to S3 + CloudFront and emits a CloudFront URL. The `agentcomms.dev` vanity domain still needs Route 53 hosted-zone and ACM certificate setup before it can point at that distribution.

Cutover status as of 2026-08-30: the GitHub repository is public at `IntergalacticTech/agentcomms`, the production OIDC trust policy is scoped to the renamed repo, `main` CI/deploy is green, and the landing site is live on the CloudFront distribution emitted by `AgentCommsLanding`. Vanity DNS and package-registry publishing remain open.

## 1. Final Repository Safety Check

Before flipping GitHub visibility, run:

```bash
secret_re='AKIA[0-9A-Z]{16}|aws_secret_access_''key|ak_live_[A-Za-z0-9]{20,}|sk_live_[A-Za-z0-9]{16,}|xox[baprs]-|ghp_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{20,}'
git grep -nE "$secret_re" -- . ':!**/node_modules/**' ':!**/dist/**' ':!cdk/cdk.out/**' ':!docs/legacy/**' ':!docs/superpowers/**' | grep -Ev 'xox''b-fake(-token)?'

aws_account_re='arn:aws:[^:]+:[^:]*:[^:]*:[0-9]{12}:|account(_id)?[" :=]+[0-9]{12}'
git grep -nE "$aws_account_re" -- . ':!**/node_modules/**' ':!**/dist/**' ':!cdk/cdk.out/**' ':!docs/legacy/**' ':!docs/superpowers/**' | grep -Ev '123456789012|000000000000'
git diff --check
```

Expected result: no live secrets, no real AWS account IDs in active public docs/code, and no whitespace errors.

Historical planning material may mention FreeMail, VictoryMail, or AgentMail because it documents the old project. Current docs, README, landing page, SDK docs, MCP docs, OpenClaw skill, and quickstart should all use AgentComms. The public pivot blog is the only current marketing asset that should intentionally explain the old FreeMail name.

## 2. Rename and Publish the GitHub Repo

```bash
gh repo rename agentcomms --repo IntergalacticTech/FreeMail.ai
git remote set-url origin git@github.com:IntergalacticTech/agentcomms.git
gh repo edit IntergalacticTech/agentcomms --visibility public --accept-visibility-change-consequences
```

After rename, update AWS OIDC trust policies that scope to `github.repository`. This repository uses GitHub's ID-qualified OIDC subject prefix. Confirm the live prefix with:

```bash
gh api repos/IntergalacticTech/agentcomms/actions/oidc/customization/sub --jq .sub_claim_prefix
```

The production deploy role currently allows that ID-qualified repo prefix plus owner/name fallbacks, keeping trust repo-scoped while tolerating GitHub's environment/ref subject forms:

```json
{
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
  },
  "StringLike": {
    "token.actions.githubusercontent.com:sub": [
      "repo:IntergalacticTech@ORG_ID/agentcomms@REPO_ID:*",
      "repo:IntergalacticTech/agentcomms:*",
      "repo:intergalactictech/agentcomms:*"
    ]
  }
}
```

GitHub redirects old repository URLs, but new docs and launch assets should link to `https://github.com/IntergalacticTech/agentcomms`.

## 3. Publish the CLI to npm

```bash
cd cli
cp ../LICENSE LICENSE
npm login
npm whoami
npm publish --access public
npm view @agentcomms/cli
```

Users can then run:

```bash
npm i -g @agentcomms/cli
```

## 4. Publish the Python SDK to PyPI

```bash
cd sdks/python
pip install build twine
python -m build
python -m twine upload dist/*
```

Check name availability first:

```bash
pip index versions agentcomms
```

If `agentcomms` is already taken, pick `agentcomms-sdk` or `agentcomms-client` and update package metadata before publishing.

## 5. Publish Node Packages to npm

```bash
cd sdks/node
npm publish --access public

cd ../../mcp
npm publish --access public
```

Users can then run:

```bash
npm i @agentcomms/client
npm i -g @agentcomms/mcp
```

## 6. Configure Public Domains

Create or transfer a public Route 53 hosted zone for `agentcomms.dev`, then add aliases:

| Hostname | Target |
|---|---|
| `agentcomms.dev` | CloudFront distribution emitted by `AgentCommsLanding` |
| `www.agentcomms.dev` | Same landing distribution or redirect |
| `api.agentcomms.dev` | API Gateway custom domain for `AgentCommsApi` |
| `console.agentcomms.dev` | Console distribution once the AgentComms console backend is live |
| `docs.agentcomms.dev` | Future generated docs site |

The current landing stack intentionally avoids creating vanity-domain aliases until the hosted zone and ACM certificate exist. This keeps production CDK deploys green in fresh AWS accounts.

## 7. Configure Project Email

Set up these addresses before public launch:

- `hello@agentcomms.dev` - general inquiries
- `security@agentcomms.dev` - vulnerability reports
- `conduct@agentcomms.dev` - Code of Conduct reports
- `sdks@agentcomms.dev` - SDK maintainer contact

Use Google Workspace aliases, SES forwarding, or AgentComms-managed channels once the hosted service is ready for inbound production traffic.

## 8. CI/CD Secrets

Required GitHub environments:

| Environment | Required secrets |
|---|---|
| `production` | `AGENTCOMMS_DEPLOY_ROLE_ARN` |
| `npm` | `NPM_TOKEN` |
| `pypi` | `PYPI_API_TOKEN` |
| `bootstrap-smoke` | `AWS_BOOTSTRAP_SMOKE_ROLE`, `AGENTCOMMS_SMOKE_DOMAIN`, `AGENTCOMMS_SMOKE_ADMIN_EMAIL` |

The internal prototype production deploy role currently uses broad CDK deployment permissions. Replace it with least privilege before running a production-grade hosted service.

## 9. Public Launch Checklist

- [x] GitHub repo renamed to `IntergalacticTech/agentcomms`
- [x] GitHub repo visibility set to public
- [x] Production GitHub OIDC trust updated to the renamed repo
- [x] `main` CI and deploy workflows green
- [x] Landing CloudFront URL verified
- [ ] `agentcomms.dev` hosted zone and aliases configured
- [ ] CLI published to npm
- [ ] Python SDK published to PyPI
- [ ] Node SDK and MCP package published to npm
- [ ] Launch assets in [`landing/blog/`](../landing/blog/) reviewed
- [ ] First adapter issues labeled `good first adapter`

## 10. Final Smoke

Run before launch announcement:

```bash
pytest tests/core tests/api tests/e2e adapters examples/invoicing-agent examples/slack-standup-bot examples/adapter-template -q
cd sdks/python && pytest tests -q
cd ../node && npm test
cd ../../mcp && npm test
cd ../cli && npm test
cd ../cdk && npm test && npx tsc --noEmit
```

Then verify the deployed protected API responds through API Gateway:

```bash
curl -i https://API_ID.execute-api.us-east-1.amazonaws.com/prod/v1/agents
```

Expected unauthenticated result: `401 Unauthorized`.
