# Self-Hosting AgentComms

AgentComms is Apache-2.0 open source. Self-hosting does not require a paid license, Marketplace purchase, license server, or opaque container image.

## Deployment Model

The supported self-host target is your own AWS account:

```bash
npm i -g @agentcomms/cli
agentcomms bootstrap \
  --domain your-domain.com \
  --admin-email you@your-domain.com \
  --region us-east-1 \
  --non-interactive \
  --json
```

The CLI deploys the CDK stacks from this repository and prints the API URL plus an admin API key in the final NDJSON line.

## What You Own

- DynamoDB table and backups
- S3 buckets for raw inbound payloads, message bodies, and attachments
- API Gateway and Lambda handlers
- Kinesis/SQS/SNS event infrastructure
- SES identities and DNS records
- SSM/KMS secrets
- Provider credentials for Slack, Telegram, push, SMS, and future adapters

Your message data stays in your AWS account unless you configure a webhook or adapter that sends it elsewhere.

## Costs

You pay AWS and provider costs directly. There is no AgentComms license fee for self-hosted use.

Primary cost drivers:

- API Gateway requests
- Lambda invocations and duration
- DynamoDB reads/writes/storage
- S3 storage and requests
- SES sending/receiving
- SMS carrier and registration costs
- Kinesis/SQS/SNS event usage
- Bedrock usage for AI helpers

## Operations

Run:

```bash
agentcomms status --json
agentcomms doctor --json
```

Use CloudFormation, CloudWatch, SES, and the provider consoles for deeper diagnostics.

## Hosted Service

The hosted `agentcomms.dev` service runs from the same open-source code. Hosted customers pay for operations: managed infrastructure, domain pools, sending reputation, provider registrations, support, and uptime.

## License

Apache-2.0. You may self-host, modify, redistribute, use commercially, and run hosted versions under the license terms. See [licensing.md](./licensing.md).
