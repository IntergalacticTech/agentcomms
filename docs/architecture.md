# Technical Architecture

FreeMail is built as a fully serverless email platform on AWS. This document describes the system design, data flow, and security model.

## System Overview

```
                     +----------------------------------------------------+
                     |                    CLIENTS                          |
                     |   REST API   |   SDKs   |   MCP Server   |  Console|
                     +------+-------+----+-----+--------+-------+----+----+
                            |            |               |            |
                     +------v------------v---------------v------------v----+
                     |                  API Gateway (REST)                 |
                     |            api.victorymail.dev/v1                   |
                     +------+---------------------------------------------+
                            |
                     +------v------+
                     |   Lambda    |
                     | Authorizer  |----> DynamoDB (API key lookup via GSI)
                     +------+------+
                            |
          +-----------+-----+------+-----------+-----------+----------+
          |           |            |           |           |          |
     +----v----+ +----v----+ +----v----+ +----v----+ +----v----+ +---v----+
     | Inboxes | |Messages | | Domains | |Webhooks | | Wait /  | | Billing|
     | Lambda  | | Lambda  | | Lambda  | | Lambda  | |OTP Lamb.| | Lambda |
     +----+----+ +----+----+ +----+----+ +----+----+ +----+----+ +---+----+
          |           |            |           |           |          |
          +-----------+-----+------+-----------+-----------+         |
                            |                                        |
                     +------v------+                          +------v------+
                     |  DynamoDB   |                          |   Stripe    |
                     | Single Table|                          |   Billing   |
                     +------+------+                          +-------------+
                            |
                     +------v------+
                     |     S3      |
                     | Email Bodies|
                     | Attachments |
                     +-------------+


     INBOUND EMAIL FLOW:

     Internet ---> SES Inbound ---> S3 (raw MIME) ---> Lambda (Inbound Processor)
                                                          |
                                        +-----------------+-----------------+
                                        |                 |                 |
                                   DynamoDB          S3 (bodies)    SQS (webhook queue)
                                  (message +        (text/html)         |
                                   thread)                        Lambda (Webhook Worker)
                                                                        |
                                                                  Customer Endpoint


     OUTBOUND EMAIL FLOW:

     API (POST /messages) ---> Lambda ---> DynamoDB (status=queued)
                                              |
                                        SQS (send queue)
                                              |
                                        Lambda (Outbound Worker)
                                              |
                                           SES v2
                                              |
                                        SNS (bounce/complaint)
                                              |
                                        Lambda (Bounce Processor)
                                              |
                                        DynamoDB (status=bounced)
```

## AWS Services

| Layer | Service | Purpose |
|-------|---------|---------|
| **API** | API Gateway (REST) | Request routing, throttling, CORS |
| **Auth** | Lambda Authorizer + Cognito | API key validation, JWT authentication for console |
| **Compute** | Lambda (Python 3.12) | All API handlers, email processing, workers |
| **Database** | DynamoDB | All metadata: orgs, inboxes, messages, threads, API keys, webhooks |
| **Object Storage** | S3 | Raw MIME emails, message bodies (text/HTML), attachments |
| **Email Transport** | SES v2 | Send and receive email with DKIM/SPF/DMARC |
| **Queuing** | SQS | Outbound send queue, webhook delivery queue |
| **Notifications** | SNS | Bounce and complaint notifications from SES |
| **DNS** | Route 53 | Platform domain management |
| **CDN** | CloudFront | Developer console hosting |
| **IaC** | CDK (TypeScript) | Infrastructure as code |
| **Billing** | Stripe | Subscription management, checkout, billing portal |

## Data Flow: Inbound Email

When someone sends an email to a FreeMail inbox:

1. **MX Record** -- The sender's mail server looks up the MX record for the domain, which points to `inbound-smtp.us-east-1.amazonaws.com`.

2. **SES Receipt** -- Amazon SES receives the email and applies spam/virus/SPF/DKIM/DMARC verdicts.

3. **S3 Storage** -- SES stores the raw MIME email in S3 (`inbound/{message-id}`).

4. **Lambda Invocation** -- SES invokes the Inbound Processor Lambda.

5. **Processing** -- The Lambda:
   - Parses the MIME email (headers, body text/HTML, attachments)
   - Looks up the inbox by recipient email address (GSI2)
   - Stores the message body in S3
   - Stores attachments in a separate S3 bucket
   - Creates message and thread records in DynamoDB
   - Increments inbox message/unread counters
   - Publishes a `message.received` event to the webhook queue

6. **Webhook Delivery** -- The Webhook Worker Lambda delivers the event to subscribed customer endpoints.

## Data Flow: Outbound Email

When an API client sends an email via `POST /inboxes/{id}/messages`:

1. **API Handler** -- The Messages Lambda validates the request, stores the message body in S3, and creates a message record in DynamoDB with `status=queued`.

2. **SQS Enqueue** -- The message ID is enqueued to the send queue (SQS).

3. **Send Worker** -- The Outbound Worker Lambda:
   - Reads the message from DynamoDB
   - Fetches the body from S3
   - Builds a MIME message (multipart/alternative with text and HTML parts)
   - Sends via SES v2 `SendEmail` (raw mode)
   - Updates the message status to `sent` with the SES message ID

4. **Bounce/Complaint Handling** -- If the email bounces or receives a complaint, SES publishes to an SNS topic, which invokes the Bounce Processor Lambda. The Lambda updates the message status to `bounced` or `complained`.

## DynamoDB Table Design

FreeMail uses a single-table design with composite primary keys. All entities share one DynamoDB table (`victorymail`).

### Entity Key Patterns

| Entity | PK | SK |
|--------|----|----|
| Organization | `ORG#{org_id}` | `META` |
| API Key | `ORG#{org_id}` | `APIKEY#{key_id}` |
| Pod | `ORG#{org_id}` | `POD#{pod_id}` |
| Inbox | `ORG#{org_id}` | `INBOX#{inbox_id}` |
| Message | `INBOX#{inbox_id}` | `MSG#{message_id}` |
| Thread | `INBOX#{inbox_id}` | `THREAD#{thread_id}` |
| Draft | `INBOX#{inbox_id}` | `DRAFT#{draft_id}` |
| Domain | `ORG#{org_id}` | `DOMAIN#{domain_id}` |
| Webhook | `ORG#{org_id}` | `WEBHOOK#{webhook_id}` |
| Attachment | `MSG#{message_id}` | `ATTACH#{attachment_id}` |
| List | `ORG#{org_id}` | `LIST#{list_id}` |
| List Member | `LIST#{list_id}` | `MEMBER#{email}` |

### Global Secondary Indexes

| GSI | PK | Purpose |
|-----|----|----|
| GSI1 | Varies | API key lookup by hash, pod-to-inbox mapping, thread messages, inbox drafts, org webhooks, org lists |
| GSI2 | `EMAIL#{address}` | Inbox lookup by email address (inbound routing) |
| GSI3 | `ORG#{org_id}` | Org-level message queries |
| GSI6 | `SES#{ses_message_id}` | Message lookup by SES ID (bounce processing) |

### Design Rationale

- **Single table** -- reduces operational overhead, one set of alarms, one backup config
- **Partition key prefixes** -- natural multi-tenant isolation; an org can never accidentally query another org's data
- **On-demand capacity** -- cost scales with usage; no capacity planning required
- **S3 for large content** -- message bodies and attachments are stored in S3, keeping DynamoDB items small and reads fast

## Security Model

### Authentication

FreeMail supports two authentication methods, both enforced by a Lambda Authorizer at the API Gateway level:

1. **API Keys** -- Tokens prefixed with `am_live_` or `am_test_`. Keys are hashed (SHA-256) before storage. The authorizer hashes the incoming key and looks it up via GSI1. Keys support three scope levels: org, pod, and inbox.

2. **JWT (Cognito)** -- Used by the developer console. The authorizer validates the JWT issuer, expiration, token_use, and kid against the Cognito JWKS endpoint. The `custom:org_id` claim maps the user to their organization.

### Data Isolation

- All DynamoDB queries are scoped by the authenticated `org_id`, which is injected by the authorizer into the Lambda context.
- API key scoping (pod/inbox level) restricts access to specific resources within the organization.
- S3 object keys include the `org_id` prefix, preventing cross-tenant access.

### Transport Security

- All API traffic is HTTPS (TLS 1.2+) via API Gateway.
- SES uses TLS for email transport (opportunistic TLS for SMTP connections).
- DKIM, SPF, and DMARC protect email authenticity.

### Webhook Security

- Each webhook has a unique signing secret (`whsec_` prefix).
- Payloads are signed with HMAC-SHA256.
- Customers verify signatures to ensure webhook authenticity.

### Secrets Management

- API keys are stored as SHA-256 hashes in DynamoDB.
- Stripe keys and other secrets are stored in Lambda environment variables (encrypted at rest by AWS).
- Webhook signing secrets are generated using `secrets.token_hex(32)`.
