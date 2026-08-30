# Email Transport Layer

The email transport layer is the foundation of AgentMail's infrastructure, built entirely on Amazon Simple Email Service (SES). It handles every aspect of getting email into and out of the platform -- sending outbound messages on behalf of AI agents, receiving inbound messages addressed to virtual inboxes, verifying custom domains, maintaining sender reputation, and tracking message threads across conversations.

This section of the architecture is critical because email deliverability is fragile. A single misconfiguration -- a missing DKIM record, an unchecked bounce rate, a shared IP on a blocklist -- can render the entire platform useless. Every design decision in this layer prioritizes reliability, isolation between tenants, and compliance with RFC standards.

---

## Table of Contents

### [1. Outbound Sending](./outbound-sending.md)

How AgentMail sends email through SES on behalf of AI agents. Covers SES v2 API usage (`SendEmail`, `SendRawEmail`, `SendBulkEmail`), MIME message construction for text, HTML, attachments, and multipart alternatives. Details configuration sets, event destinations for bounce/complaint/delivery tracking, sending limits (sandbox and production), burst rate handling, multi-region sending strategy, and complete Python code examples with error handling.

### [2. Inbound Receiving](./inbound-receiving.md)

How AgentMail receives email from the internet and routes it to virtual inboxes. Covers MX record configuration, SES Receipt Rule Sets with catch-all architecture, the full inbound pipeline (SES to S3 to Lambda router), and the complete Lambda router function with pseudocode for SES notification parsing, recipient resolution, MIME parsing, thread computation, DynamoDB storage, S3 attachment storage, Kinesis event publishing, and bounce handling. Includes SES inbound limits, verdict processing (spam, virus, SPF, DKIM, DMARC), and address scheme design.

### [3. Custom Domains](./custom-domains.md)

How customers add and verify their own domains for sending and receiving. Covers the domain verification workflow step by step, SES `CreateEmailIdentity` API (Easy DKIM vs BYODKIM), all required DNS records (DKIM CNAMEs, SPF TXT, DMARC TXT, MX, verification TXT), polling for verification status, optional Route 53 auto-setup, DKIM key rotation, zone file generation, and the domain status state machine.

### [4. Deliverability](./deliverability.md)

How AgentMail maintains high deliverability across a multi-tenant platform. Covers IP pool strategy (shared, dedicated, per-tenant, transactional), IP warming schedules, SES Managed Warming with VDM-managed dedicated IPs, Virtual Deliverability Manager configuration, reputation monitoring, per-tenant reputation isolation with automatic throttling and suspension, suppression list management, feedback loops, and CloudWatch alarms.

### [5. Threading](./threading.md)

How AgentMail groups related messages into conversation threads. Covers the RFC 5256-based threading algorithm, the three headers used (`Message-ID`, `In-Reply-To`, `References`), the complete thread resolution algorithm with detailed pseudocode (In-Reply-To lookup, References chain lookup, subject normalization fallback, new thread creation), thread state management with atomic counter updates, and edge cases including missing headers, cross-inbox threads, and forwarded messages.

### [6. Domain Coexistence](./domain-coexistence.md)

How AgentMail coexists with Google Workspace, Microsoft 365, and other email providers on the same domain. Covers six approaches: subdomain strategy, Google Workspace transport rules, Microsoft 365 mail flow rules, MX priority (and why it doesn't work), custom MX smart router with Haraka implementation, and outbound-only mode. Includes complete DNS configuration for multi-provider SPF/DKIM/DMARC, a decision matrix, API changes for coexistence modes, SMTP proxy infrastructure on ECS, and customer onboarding guides for each major provider.

---

## Architecture Diagram

```
OUTBOUND                                          INBOUND
────────                                          ───────

  API Request                                    Internet Sender
  POST /v1/inboxes/{id}/messages                      │
       │                                              ▼
       ▼                                     MX Record (SES Inbound)
  API Gateway → Lambda                               │
       │                                              ▼
       ▼                                     SES Receipt Rule Set
  SQS Send Queue                                      │
       │                                    ┌─────────┴──────────┐
       ▼                                    ▼                    ▼
  Lambda Send Worker                   S3 Action            Lambda Action
       │                            (store raw MIME)      (inbound-router)
       ▼                                    │                    │
  SES v2 API                                └────────────────────┤
  (SendRawEmail)                                                 │
       │                                              ┌──────────┼──────────┐
       ▼                                              ▼          ▼          ▼
  Configuration Set                              DynamoDB       S3       Kinesis
  (per-org tracking)                           (metadata)  (attachments) (events)
       │
       ▼
  Event Destinations (SNS)
  ├── Bounces
  ├── Complaints
  └── Deliveries

DOMAIN VERIFICATION                          DELIVERABILITY
────────────────────                         ──────────────
  POST /v1/domains                           IP Pool Assignment
       │                                          │
       ▼                                          ▼
  SES CreateEmailIdentity                    SES Configuration Set
       │                                     (per-org)
       ▼                                          │
  Return DNS Records to Customer                  ▼
  (3 DKIM CNAMEs, SPF, DMARC, MX)          VDM Dashboard
       │                                     Bounce/Complaint Monitoring
       ▼                                     Per-Tenant Reputation Isolation
  Poll GetEmailIdentity (every 5 min)
       │
       ▼
  Domain Verified → Fire Event
```

## Key Design Principles

1. **Catch-all routing.** SES inbound does not have an "inbox" concept. We run a single Receipt Rule Set per domain that catches all addresses, then route in application code via the Lambda router. This gives us unlimited virtual inboxes without any SES-level per-inbox configuration.

2. **Per-organization configuration sets.** Every SES sending operation includes a configuration set tied to the sender's organization. This gives us per-org delivery metrics, per-org event destinations, and the ability to assign different IP pools per org.

3. **Tenant isolation at the reputation layer.** A single bad tenant can destroy deliverability for everyone. We monitor bounce and complaint rates per tenant in real time and automatically throttle or suspend senders who exceed thresholds -- before SES takes action at the account level.

4. **Thread computation in application code.** SES delivers raw MIME. We parse `Message-ID`, `In-Reply-To`, and `References` headers ourselves and maintain thread state in DynamoDB with atomic updates. This gives us full control over threading behavior including cross-inbox threads and subject-based fallback matching.

5. **Multi-region readiness.** SES inbound is only available in three regions (`us-east-1`, `us-west-2`, `eu-west-1`). We start in `us-east-1` for inbound but use per-region quotas for outbound to distribute sending load across regions when needed.
