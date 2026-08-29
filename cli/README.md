# @agentcomms/cli

Deploy and operate AgentComms — the agent communications hub — in your AWS account.

## Install

```bash
npm i -g @agentcomms/cli
```

## Quick start

```bash
agentcomms bootstrap \
  --domain your-domain.com \
  --admin-email you@your-domain.com \
  --non-interactive \
  --json
```

Wait up to 25 minutes. The final NDJSON line contains your `admin_api_key`. Store it.

## Preconditions

Before running bootstrap, verify:

- AWS credentials work: `aws sts get-caller-identity`
- Region is SES-inbound capable: `us-east-1`, `us-west-2`, or `eu-west-1`
- Route 53 hosted zone exists for your domain in the same AWS account
- Node 20+, Python 3.12+, AWS CLI v2, CDK v2, Docker running

## Commands

| Command | Description |
|---|---|
| `agentcomms bootstrap` | Deploy AgentComms into your AWS account (headline command) |
| `agentcomms doctor` | Run preflight checks only — no deployment |
| `agentcomms status` | Show stack status, SES identity, and channel health |
| `agentcomms channels list` | Show known adapter types and setup status |
| `agentcomms channels enable\|disable` | Explain deployment-time adapter changes; live toggling is not supported yet |
| `agentcomms keys create\|list\|revoke` | Manage API keys |
| `agentcomms agents create\|list\|delete` | Manage agent records |
| `agentcomms destroy` | Tear down all CloudFormation stacks |

## NDJSON event format

All commands emit NDJSON to stdout when `--json` is passed (automatically on `--non-interactive`):

```json
{"phase":"preflight","check":"aws_credentials","status":"ok","msg":"account 123456789012"}
{"phase":"deploy","stack":"AgentCommsData","status":"running","progress":0.3}
{"phase":"done","status":"ok","api_url":"https://api.your-domain.com/v1","admin_api_key":"ak_live_..."}
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Preflight failure |
| 2 | CDK deploy failure |
| 3 | SES DKIM verification timeout |
| 4 | Smoke test failure |

## Configuration

The CLI stores your deployed hub config in `~/.agentcomms/config.json`. You can set the active domain with:

```bash
agentcomms status --json  # reads from config
```

## License

Apache-2.0. See [LICENSE](./LICENSE).

Full deployment guide: [AGENT.md](https://github.com/IntergalacticTech/FreeMail.ai/blob/main/AGENT.md)
