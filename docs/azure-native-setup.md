# Azure Native Setup

Status: proposed target architecture and implementation plan as of 2026-06-17.

This document describes how to run AgentComms on Azure-native services. It is intentionally direct about the largest gap: Azure Communication Services Email is suitable for outbound email, delivery reports, engagement events, and domain authentication, but generally available ACS Email does not provide an SES-style inbound/catch-all email receiver. A feature-complete Azure deployment must choose an inbound email strategy before claiming full parity with the AWS stack.

## Target Architecture

```text
Clients / SDKs / Console
        |
        v
Azure Front Door or API Management
        |
        v
Azure Functions, Python 3.12
        |
        +--> Cosmos DB for NoSQL, single-container data model
        +--> Blob Storage, raw MIME, bodies, attachments
        +--> Service Bus queues, outbound sends and webhook delivery
        +--> Event Grid, channel events and provider callbacks
        +--> Event Hubs, optional high-volume event stream
        +--> Key Vault, API signing secrets and channel credentials
        +--> Azure Communication Services, outbound email, SMS, voice
        +--> Azure OpenAI and Azure AI Search, AI extraction and semantic search
        +--> Application Insights and Azure Monitor
```

Static assets:

- Developer console: Azure Static Web Apps or Storage static website plus Front Door.
- Landing/docs: Static Web Apps, Storage static website, or GitHub Pages.

Identity:

- Console users: Microsoft Entra External ID, or Azure AD B2C if the tenant already uses it.
- Runtime services: managed identities with least-privilege RBAC.
- API clients: existing AgentComms API keys, hashed and stored in Cosmos DB.

## AWS to Azure Service Map

| Current AWS service | Azure-native equivalent | Notes |
|---|---|---|
| API Gateway REST | API Management or Azure Functions HTTP trigger | API Management is better for quotas, products, policies, and customer-facing API management. |
| Lambda | Azure Functions on Premium plan | Premium avoids cold-start pain and supports VNet integration. Container Apps is a good fit for long-running or TCP services. |
| DynamoDB | Cosmos DB for NoSQL | Preserve the single-table model with `/PK` or `/tenant_id` partitioning. Validate RU costs for hot inboxes. |
| S3 | Blob Storage | Use containers for raw inbound, bodies, attachments, and vault artifacts. |
| SQS | Service Bus queues | Use sessions for ordering where needed. |
| SNS | Event Grid | Good for provider callbacks, fan-out, and system events. |
| Kinesis | Event Hubs | Use only if replay/high-throughput stream semantics are needed. |
| SES outbound | Azure Communication Services Email | Supports custom domains and sender authentication. |
| SES inbound | No exact GA ACS equivalent | Choose ACS private preview, Graph mailbox ingestion, custom SMTP ingress, or a non-native provider. |
| Cognito | Entra External ID or Azure AD B2C | Keep API keys for agent/programmatic auth. |
| KMS | Key Vault keys | Use managed identities and per-tenant key options for enterprise. |
| Secrets Manager/SSM | Key Vault secrets | Store Slack, Telegram, ACS, Stripe, and webhook secrets here. |
| Bedrock | Azure OpenAI | Keep model calls behind a provider interface. |
| OpenSearch Serverless | Azure AI Search | Use vector indexes for semantic search. |
| CloudWatch/X-Ray | Azure Monitor and Application Insights | Add distributed tracing from Functions through outbound calls. |
| Route 53 | Azure DNS | DNS can remain external if customers already manage domains elsewhere. |
| CloudFront | Azure Front Door | Optional WAF and global edge routing. |

## Inbound Email Options

### Option A: ACS Email inbound private preview

Best if Microsoft enables `Microsoft.Communication.EmailInboundReceived` for the subscription and region.

Flow:

```text
MX record
  -> ACS Email inbound event
  -> Event Grid
  -> Azure Function email_ingest
  -> Blob Storage raw MIME/body/attachments
  -> Cosmos DB message records
  -> Event Grid or Service Bus webhook jobs
```

Pros:

- Cleanest Azure-native equivalent to SES inbound.
- Uses Event Grid like other ACS events.
- Avoids polling mailboxes.

Cons:

- Not generally available in public ACS Email docs today.
- Requires support/preview access and product risk acceptance.

### Option B: Microsoft 365 mailbox plus Microsoft Graph

Best GA Microsoft-supported fallback for replies and transactional inbound where customers can tolerate mailbox-backed routing.

Flow:

```text
Exchange Online mailbox or shared mailbox
  -> Microsoft Graph change notification
  -> Azure Function graph_ingest
  -> Graph message fetch
  -> Normalize MIME and headers
  -> Cosmos DB + Blob Storage
```

Pros:

- Supported Microsoft surface.
- Good threading metadata through Graph.
- Works well for replies to outbound email.

Cons:

- Not the same as dynamic catch-all inbox creation.
- Requires Microsoft 365 licensing and tenant administration.
- Per-agent mailbox creation is not as clean as SES virtual inboxes.

### Option C: Custom SMTP ingress on Azure

Best if the product must preserve SES-style virtual inboxes and catch-all domains without waiting for ACS inbound.

Flow:

```text
Azure DNS MX
  -> Public IP / Load Balancer / Container Apps TCP ingress
  -> SMTP receiver service
  -> Blob Storage raw MIME
  -> Service Bus email-ingest queue
  -> Azure Function normalizer
  -> Cosmos DB message records
```

Pros:

- Preserves virtual inbox and catch-all behavior.
- Fully under the customer's Azure subscription.
- Can use the same adapter normalization logic after MIME capture.

Cons:

- Highest operational burden.
- Requires abuse controls, spam/virus filtering, TLS, queueing, backpressure, and reputation-aware handling.
- Azure outbound SMTP port 25 restrictions still matter if the receiver ever relays mail directly; outbound should use ACS Email or another authenticated relay.

### Option D: Non-native inbound provider

Use SendGrid Inbound Parse, Mailgun Routes, or AWS SES inbound while the rest of the stack runs on Azure.

Pros:

- Fastest feature-complete path.
- Reduces SMTP operations.

Cons:

- Not Azure native.
- May violate the deployment goal for regulated customers.

## Recommended Azure v1

For a practical Azure-native v1:

1. Build all non-email-inbound services on Azure-native components.
2. Use ACS Email for outbound sending and delivery events.
3. Use ACS SMS Event Grid events for SMS inbound.
4. Support Graph mailbox ingestion as the GA inbound fallback.
5. Keep custom SMTP ingress as the feature-parity path for customers who need catch-all virtual inboxes.
6. Add ACS Email inbound support behind the same provider interface if/when the customer has preview access or the feature becomes generally available.

## Repository Changes Needed

### 1. Add provider interfaces

Create a provider boundary so the domain model is not coupled to `boto3`.

Suggested modules:

```text
core/providers/
  __init__.py
  table.py
  blob.py
  queue.py
  events.py
  secrets.py
  email.py
  sms.py
  ai.py
  search.py
```

Provider responsibilities:

- `table`: get, put, update, query by index, transactional writes.
- `blob`: put/get/delete object, signed URL generation.
- `queue`: enqueue, batch dequeue handler helpers.
- `events`: publish domain events and channel callbacks.
- `secrets`: get/set/delete secret values.
- `email`: verify domain, send MIME, receive/normalize inbound events.
- `sms`: send SMS, normalize inbound SMS events.
- `ai`: summarize, categorize, extract, embed.
- `search`: index messages and query semantic search.

### 2. Keep AWS as the reference provider

Move direct AWS calls into `core/providers/aws/` first. Do this before adding Azure so behavior remains testable.

High-value first moves:

- `core/api/_common.py`: table provider instead of direct DynamoDB resource creation.
- `adapters/email/adapter.py`: email provider instead of direct SES calls.
- `adapters/email/ingest.py`: blob and event providers instead of direct S3/Kinesis calls.
- SMS and push adapters: ACS/SNS provider boundary.
- Vault and domain handlers: Key Vault/KMS and DNS/email-domain provider boundary.

### 3. Add Azure provider implementations

Suggested package:

```text
core/providers/azure/
  table_cosmos.py
  blob_storage.py
  queue_servicebus.py
  events_eventgrid.py
  secrets_keyvault.py
  email_acs.py
  email_graph.py
  sms_acs.py
  ai_openai.py
  search_ai_search.py
```

Use managed identity in production. Local development can use Azure CLI credentials.

### 4. Add Azure infrastructure

Suggested layout:

```text
infra/azure/
  README.md
  main.bicep
  modules/
    app-insights.bicep
    api-management.bicep
    communication-services.bicep
    cosmos.bicep
    dns.bicep
    event-grid.bicep
    front-door.bicep
    functions.bicep
    key-vault.bicep
    service-bus.bicep
    storage.bicep
    static-web-app.bicep
  azd.yaml
```

Use Azure Developer CLI for setup:

```bash
azd auth login
azd env new agentcomms-prod
azd env set AZURE_LOCATION eastus
azd env set AGENTCOMMS_DOMAIN example.com
azd up
```

### 5. Add Azure-specific runtime configuration

Environment variables:

```text
AGENTCOMMS_PROVIDER=azure
AGENTCOMMS_COSMOS_ENDPOINT=
AGENTCOMMS_COSMOS_DATABASE=agentcomms
AGENTCOMMS_COSMOS_CONTAINER=items
AGENTCOMMS_STORAGE_ACCOUNT=
AGENTCOMMS_SERVICEBUS_NAMESPACE=
AGENTCOMMS_EVENTGRID_TOPIC_ENDPOINT=
AGENTCOMMS_KEYVAULT_URI=
AGENTCOMMS_ACS_ENDPOINT=
AGENTCOMMS_EMAIL_DOMAIN=
AGENTCOMMS_INBOUND_MODE=graph|acs-preview|smtp
```

## Azure Deployment Steps

### Prerequisites

- Azure subscription with permission to create resource groups, managed identities, role assignments, ACS, Cosmos DB, Storage, Service Bus, Event Grid, Key Vault, Azure Functions, and Application Insights.
- Azure CLI and Azure Developer CLI.
- Python 3.12 and Node 20+ for local builds.
- A domain managed in Azure DNS or another DNS provider.
- For outbound email: ACS Email Communication Services resource and verified domain.
- For Graph inbound: Microsoft 365 tenant, mailbox/shared mailbox, and an Entra app registration with the required Graph permissions.

### Step 1: Create infrastructure

```bash
cd infra/azure
azd auth login
azd env new agentcomms-prod
azd env set AZURE_LOCATION eastus
azd env set AGENTCOMMS_DOMAIN example.com
azd up
```

Expected outputs:

- API base URL.
- Console URL.
- Cosmos DB account and database names.
- Storage account and container names.
- Service Bus namespace and queue names.
- Key Vault URI.
- ACS resource endpoint.
- DNS records for email/domain verification.

### Step 2: Verify email sending domain

In ACS Email, provision and verify the custom domain. Add the required DNS records for ownership, SPF, DKIM, and DKIM2. Do not claim inbound support from ACS unless the subscription has inbound email events enabled.

### Step 3: Configure inbound mode

Choose one:

- `AGENTCOMMS_INBOUND_MODE=graph` for Microsoft 365 mailbox ingestion.
- `AGENTCOMMS_INBOUND_MODE=acs-preview` for ACS inbound Event Grid preview.
- `AGENTCOMMS_INBOUND_MODE=smtp` for custom SMTP ingress.

### Step 4: Seed the first organization

Add an Azure equivalent of `tools/seed_first_org.py`:

```bash
python tools/seed_first_org.py \
  --provider azure \
  --org-name "example.com admin" \
  --admin-email admin@example.com
```

The script should print the admin API key once and store only its hash.

### Step 5: Run smoke tests

Required smoke tests:

- Create an agent.
- Provision an outbound email channel.
- Send an email through ACS Email.
- Receive a delivery event through Event Grid.
- Ingest an inbound message through the selected inbound mode.
- List the unified inbox.
- Deliver a webhook.
- Run one AI operation through Azure OpenAI if enabled.

## Security Baseline

- Use managed identities for all Azure resources.
- Store all secrets in Key Vault, not Function app settings except references.
- Use private endpoints for Cosmos DB, Storage, Service Bus, and Key Vault in production.
- Put API Management or Front Door WAF in front of public HTTP APIs.
- Use Application Insights sampling and correlation IDs.
- Enable Cosmos DB point-in-time restore.
- Enable Blob soft delete and versioning on important containers.
- Add per-tenant quotas at the API and queue layer.
- Add email abuse controls before opening custom SMTP ingress.

## Open Decisions

- Whether Azure v1 requires SES-style catch-all virtual inboxes, or whether mailbox-backed Graph ingestion is acceptable.
- Whether to use API Management in every deployment or make it optional for lower-cost installs.
- Whether Cosmos DB should use one global container or per-tenant containers for enterprise isolation.
- Whether Event Hubs is needed initially, or Event Grid plus Service Bus is enough.
- Whether Azure OpenAI is mandatory or optional, since not every customer subscription has model access.

## References

- Azure Communication Services Email overview: https://learn.microsoft.com/en-us/azure/communication-services/concepts/email/email-overview
- ACS Email domain authentication: https://learn.microsoft.com/en-us/azure/communication-services/concepts/email/email-domain-and-sender-authentication
- ACS Email events: https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/email/handle-email-events
- ACS send email quickstart: https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/email/send-email
- ACS receive SMS quickstart: https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/sms/receive-sms
- Azure Container Apps ingress: https://learn.microsoft.com/en-us/azure/container-apps/ingress-overview
- Azure outbound SMTP port 25 restrictions: https://learn.microsoft.com/en-us/troubleshoot/azure/virtual-network/troubleshoot-outbound-smtp-connectivity

