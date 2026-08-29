# Billing

AgentComms has two deployment models:

- **Self-hosted:** Apache-2.0 source deployed into your own AWS account. You pay AWS and provider costs directly. There is no AgentComms license fee.
- **Hosted:** `agentcomms.dev` operated by Victory. Pricing covers managed infrastructure, domain pools, provider registrations, support, uptime, and operational work.

## Self-Hosted Costs

Self-hosted users should budget for:

- API Gateway requests
- Lambda invocations and duration
- DynamoDB reads, writes, and storage
- S3 storage and requests for message bodies and attachments
- SES inbound/outbound email
- AWS End User Messaging and carrier registration for SMS
- Kinesis, SQS, and SNS usage
- Bedrock usage for AI helpers
- Third-party provider fees for channels such as Slack, WhatsApp, fax, postal mail, or voice

## Hosted Billing API

Hosted billing endpoints may exist on `agentcomms.dev` deployments, but they are not required for self-hosted OSS use and are not part of the core adapter contract.

Recommended hosted routes:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/billing/status` | Current hosted plan and usage |
| `POST` | `/billing/checkout` | Create hosted checkout session |
| `POST` | `/billing/portal` | Create hosted billing portal session |
| `POST` | `/billing/webhook` | Stripe webhook receiver |

Self-hosted deployments can omit those routes entirely or replace them with their own billing implementation.

## License

Billing does not affect license rights. The repository is Apache-2.0, including for commercial and hosted use. See [licensing.md](./licensing.md).
