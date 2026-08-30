# GitHub Actions Workflows

This directory contains CI/CD workflows for the AgentComms project.

---

## Workflows

### `test.yml` — Run tests on every PR and push

Triggers on pull requests and pushes to `main`, `develop`, and `phase1-foundation`.

| Job | What it does |
|-----|-------------|
| `python` | Creates a venv, installs runtime + test deps, runs `tests/core`, `tests/api`, `tests/e2e`, `adapters`, runnable Python examples, the adapter template, and the Python SDK's own test suite |
| `cdk` | `npm ci`, CDK TypeScript tests, `tsc --noEmit`, and a basic `cdk synth` (no AWS credentials required) |
| `cli` | Builds and tests the `cli/` package |
| `sdk-node` | Builds and tests `sdks/node/` |
| `mcp` | Builds and tests the `mcp/` server package |

No secrets are required for this workflow.

**Adding a new test job** — copy any existing job block, change the `name` and the `run` commands to point at the new subsystem directory. The trigger block at the top does not need to change.

---

### `publish-sdks.yml` — Publish packages on version tags

Triggers on any tag matching `v*` (e.g. `v0.1.0`).

| Job | Target registry | GitHub environment |
|-----|-----------------|--------------------|
| `python` | PyPI | `pypi` |
| `node-sdk` | npm | `npm` |
| `cli` | npm | `npm` |
| `mcp` | npm | `npm` |

#### Required secrets

| Secret | Where to set it | Notes |
|--------|-----------------|-------|
| `PYPI_API_TOKEN` | GitHub environment `pypi` | Create an API token at https://pypi.org/manage/account/token/ scoped to the `agentcomms` project |
| `NPM_TOKEN` | GitHub environment `npm` | Create an automation token at https://www.npmjs.com/settings/<org>/tokens |

#### Enabling the environment approval gate (opt-in)

1. Go to **Settings > Environments** in the GitHub repo.
2. Create environments named `pypi` and `npm` if they don't exist.
3. Under each environment, enable **Required reviewers** and add the Victory team.
4. Publishing will pause for human approval before uploading packages to the registry.

To skip the gate for fully-automated releases, leave Required reviewers empty.

---

### `bootstrap-smoke.yml` — Nightly smoke test against a dedicated AWS sub-account

Triggers on a daily cron (`07:00 UTC`) and via `workflow_dispatch` for manual runs.

The job is guarded by `if: github.repository == 'IntergalacticTech/agentcomms'` so it is automatically skipped on forks.

#### What it does

1. Assumes an OIDC role in a **dedicated smoke-test AWS sub-account** (not production).
2. Builds and links the CLI.
3. Runs `agentcomms doctor` as a preflight check.
4. Runs `agentcomms bootstrap` end-to-end, capturing output to `bootstrap.log`.
5. Always runs `agentcomms destroy --yes` as teardown, even on failure.
6. Uploads `bootstrap.log` as an artifact if any step fails.

#### Required secrets (set on the `bootstrap-smoke` GitHub environment)

| Secret | Description |
|--------|-------------|
| `AWS_BOOTSTRAP_SMOKE_ROLE` | ARN of the IAM role in the smoke sub-account, e.g. `arn:aws:iam::ACCOUNT_ID:role/AgentCommsSmokeCIRole` |
| `AGENTCOMMS_SMOKE_DOMAIN` | A domain with a Route 53 hosted zone in the smoke sub-account, e.g. `smoke.agentcomms.dev` |
| `AGENTCOMMS_SMOKE_ADMIN_EMAIL` | An email address to use as the bootstrap admin contact |

#### Setting up the OIDC trust

In the smoke sub-account, create an IAM OIDC identity provider and role:

```bash
# 1. Create the OIDC provider (one-time per account)
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1

# 2. Create a role with a trust policy like:
# {
#   "Version": "2012-10-17",
#   "Statement": [{
#     "Effect": "Allow",
#     "Principal": { "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com" },
#     "Action": "sts:AssumeRoleWithWebIdentity",
#     "Condition": {
#       "StringEquals": {
#         "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
#       },
#       "StringLike": {
#         "token.actions.githubusercontent.com:sub": "repo:IntergalacticTech/agentcomms:*"
#       }
#     }
#   }]
# }
```

Attach a policy to the role granting the permissions required by `agentcomms bootstrap` (Route 53, SES, SQS, DynamoDB, Lambda, IAM, CloudFormation, etc.).

Set the resulting role ARN as the `AWS_BOOTSTRAP_SMOKE_ROLE` secret on the `bootstrap-smoke` GitHub environment.

---

### `deploy.yml` — Production CDK deploy from `main`

Triggers on pushes to `main` and deploys only stacks whose names start with
`AgentComms`, including the public `AgentCommsLanding` static site stack.
Legacy `VictoryMail-*` stacks are intentionally excluded.

The workflow uses the `production` GitHub environment and deploys with these
CDK context values by default:

| Context | Default | Override with |
|---------|---------|---------------|
| `stage` | `prod` | `AGENTCOMMS_DEPLOY_STAGE` environment variable |
| `envName` | `prod` | `AGENTCOMMS_DEPLOY_ENV_NAME` environment variable |
| `domain` | `agentcomms.dev` | `AGENTCOMMS_DOMAIN` environment variable |
| AWS region | `us-east-1` | `AWS_REGION` environment variable |

#### Required production environment secret

| Secret | Description |
|--------|-------------|
| `AGENTCOMMS_DEPLOY_ROLE_ARN` | ARN of the IAM role GitHub Actions assumes to run `cdk deploy`, e.g. `arn:aws:iam::ACCOUNT_ID:role/AgentCommsGitHubDeployRole` |

#### One-time AWS/GitHub OIDC setup

Create the GitHub OIDC provider once per AWS account if it does not already
exist:

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

Bootstrap the AWS account/region once before the first production deploy:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
cd cdk
npx cdk bootstrap "aws://${ACCOUNT_ID}/us-east-1"
```

Create a deploy role with a trust policy scoped to the production environment:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:IntergalacticTech/agentcomms:environment:production"
      }
    }
  }]
}
```

Attach the permissions needed for CDK deployment. The current internal
prototype uses `AdministratorAccess`; before treating the hosted service as
production-grade, replace that with a least-privilege deploy policy covering
CloudFormation, IAM, Lambda, API Gateway, DynamoDB, S3, Kinesis, SQS, SNS, SES,
Route 53, CloudWatch, and SSM resources owned by AgentComms.

Set the role ARN on the GitHub environment:

```bash
gh secret set AGENTCOMMS_DEPLOY_ROLE_ARN --env production
```

Optional environment variables:

```bash
gh variable set AWS_REGION --env production --body us-east-1
gh variable set AGENTCOMMS_DEPLOY_STAGE --env production --body prod
gh variable set AGENTCOMMS_DEPLOY_ENV_NAME --env production --body prod
gh variable set AGENTCOMMS_DOMAIN --env production --body agentcomms.dev
```

---

## Skipping workflows on forks

The `bootstrap-smoke` workflow already contains `if: github.repository == 'IntergalacticTech/agentcomms'`. Fork contributors will never accidentally run the smoke test or spend AWS resources.

The `publish-sdks` workflow is implicitly safe on forks because forked repos do not have access to the `pypi`/`npm` environment secrets.
