# SaaS Platform Layer

## Planning Refresh

This file contains both current launch planning and older future-state detail.

The current source of truth is:

- the product is **FreeMail**
- `victorymail.dev` is the temporary deployment and testing domain
- direct SaaS launches before AWS Marketplace
- the self-serve plan ladder is **Free -> Pro**
- AI features are **paid-only**
- AWS Marketplace is the path **beyond Pro**, not the first launch channel

If a later section in this file conflicts with those rules, follow this section and the current [build plan](/Users/jwc/code/Victory/FreeMail.ai/BUILD_PLAN.md).

### Current Tier Model

| Tier | Channel | Purpose | AI |
|------|---------|---------|----|
| Free | Direct SaaS | developer adoption and proof of value | No |
| Pro | Direct SaaS | higher quotas and paid self-serve usage | Yes |
| Marketplace | AWS Marketplace | higher mailbox/domain/throughput needs and procurement-led buying | Yes |

### Current Launch Principles

- Keep the free tier generous, especially on custom domains.
- Do not add Business or Scale self-serve tiers before Free and Pro are live.
- Do not make Marketplace a launch dependency.
- Use Marketplace when a customer outgrows Pro or needs AWS procurement.

---

AgentMail was originally designed as a pure AWS Marketplace product -- enterprise customers subscribe through Marketplace, usage is metered hourly, and billing flows through AWS's consolidated invoicing. That model works for enterprise procurement but creates a fatal bottleneck for developer adoption: requiring an AWS account, navigating Marketplace, and committing to a contract before sending a single email is too much friction for the individual developer or small team who just wants to try the product.

The SaaS Platform Layer solves this by adding a **direct-to-consumer channel** alongside the existing Marketplace channel. A developer can visit the AgentMail website, sign up with an email address, get an API key, and create their first inbox in under two minutes -- no AWS account, no credit card, no procurement process. The free tier gives them enough capacity to build a proof of concept. When they outgrow the free tier, they upgrade to a paid SaaS plan with a credit card. When they outgrow the paid plans -- or when their enterprise procurement team gets involved -- they migrate to AWS Marketplace for custom contracts, committed spend credits, and enterprise features.

This is not a pivot away from Marketplace. This is an **acquisition funnel** that feeds Marketplace. The SaaS platform is a growth engine; the Marketplace is the revenue engine.

---

## Table of Contents

- [1. Platform Strategy](#1-platform-strategy)
- [2. Tier System](#2-tier-system)
- [3. User Registration and Authentication](#3-user-registration-and-authentication)
- [4. Developer Console](#4-developer-console)
- [5. Billing System](#5-billing-system)
- [6. Feature Gating Architecture](#6-feature-gating-architecture)
- [7. Cost Containment for Free Tier](#7-cost-containment-for-free-tier)
- [8. Self-Service Domain Onboarding](#8-self-service-domain-onboarding)
- [9. AWS Marketplace Migration Path](#9-aws-marketplace-migration-path)
- [10. Platform Operations](#10-platform-operations)

---

## 1. Platform Strategy

### Two-Channel Distribution Model

```
                                    AgentMail
                                       |
                    ┌──────────────────┴──────────────────┐
                    |                                      |
             Direct SaaS                          AWS Marketplace
          (agentmail.to web)                   (enterprise procurement)
                    |                                      |
        ┌───────────┼───────────┐                ┌────────┴────────┐
        |           |           |                |                 |
    Free Tier    Pro Tier    Business +      Contract Tiers   Private Offers
    (no card)   ($29/mo)    ($99+/mo)       (custom pricing)  (negotiated)
        |           |           |                |                 |
        └───────────┼───────────┘                └────────┬────────┘
                    |                                      |
                    └──────────────┬───────────────────────┘
                                   |
                        Same API, Same Infrastructure
                        Same DynamoDB, Same SES, Same Lambda
                        Same Multi-Tenant Isolation Model
```

### Why Both Channels

**Direct SaaS exists for developer adoption:**
- No AWS account required to sign up
- No procurement process -- sign up in 2 minutes
- Credit card billing (Stripe) -- familiar to every developer
- Free tier for experimentation -- zero commitment to evaluate
- Self-service everything: domains, inboxes, API keys, webhooks
- The developer who builds the proof of concept is the champion who drives enterprise procurement

**AWS Marketplace exists for enterprise revenue:**
- Consolidated billing with existing AWS spend
- Enterprise Discount Program (EDP) credits apply
- Procurement teams can approve without new vendor onboarding
- Custom contracts with committed spend and volume discounts
- Private offers for negotiated pricing
- SOC2, HIPAA compliance guarantees
- SLA-backed uptime commitments
- SSO/SAML integration, audit logs, dedicated infrastructure

### Revenue Split Expectation

| Metric | Direct SaaS | AWS Marketplace |
|--------|-------------|-----------------|
| **Revenue share** | 20% | 80% |
| **Customer count** | 80% | 20% |
| **ARPU** | $50-150/month | $2,000-50,000/month |
| **Acquisition cost** | Near-zero (organic/developer) | Sales-assisted |
| **Gross margin** | 70-80% | 65-75% (after Marketplace fee) |
| **Primary value** | Funnel, product-led growth | Revenue, enterprise scale |

This is the classic **bottom-up SaaS** model used by Twilio, Stripe, Datadog, and others. The individual developer signs up for free, builds something, their company grows into an enterprise contract. Our version adds the AWS Marketplace as the enterprise endpoint instead of a traditional enterprise sales motion.

### The Funnel

```
Developer discovers AgentMail (docs, blog, HN, Twitter)
        |
        v
Signs up for free tier (email + password, 2 minutes)
        |
        v
Creates first inbox, sends test email (< 5 minutes)
        |
        v
Builds proof of concept (days/weeks)
        |
        v
Hits free tier limits (5 inboxes, 1000 emails)
        |
        v
Upgrades to Pro tier ($29/mo, credit card)        ← 5% conversion target
        |
        v
Production usage grows, needs more capacity
        |
        v
Upgrades to Business ($99) or Scale ($299)         ← upsell
        |
        v
Enterprise procurement gets involved
        |
        v
Migrates to AWS Marketplace (custom contract)      ← revenue engine
```

**Target metrics:**
- Free → Paid conversion: 5% within 3 months
- Paid → Scale conversion: 20% within 6 months
- Scale → Marketplace: 30% within 12 months
- Time to first inbox (from signup): < 5 minutes
- Time to first email sent (from signup): < 10 minutes

---

## 2. Tier System

### Tier Comparison Table

Note: the table below reflects an earlier future-state plan. For the current launch plan, use the `Planning Refresh` section above: direct SaaS is `Free` and `Pro`, and AWS Marketplace starts above Pro.

| Feature | Free | Pro ($29/mo) | Business ($99/mo) | Scale ($299/mo) | Enterprise (Marketplace) |
|---------|------|--------------|--------------------|-----------------|--------------------------| 
| **Inboxes** | 5 | 25 | 100 | 500 | Custom |
| **Emails/month** (sent+received) | 1,000 | 10,000 | 50,000 | 200,000 | Custom |
| **Custom domains** | 1 | 3 | 10 | Unlimited | Unlimited |
| **REST API rate limit** | 5 req/sec | 50 req/sec | 200 req/sec | 500 req/sec | Custom |
| **Webhooks** | 3 endpoints | 10 endpoints | 25 endpoints | 100 endpoints | Unlimited |
| **MCP server** | Yes | Yes | Yes | Yes | Yes |
| **WebSocket connections** | 1 concurrent | 5 concurrent | 25 concurrent | 100 concurrent | Custom |
| **OTP extraction** | Yes | Yes | Yes | Yes | Yes |
| **Long-poll wait** | Yes | Yes | Yes | Yes | Yes |
| **Storage** | 100 MB | 1 GB | 10 GB | 100 GB | Custom |
| **Semantic search** | No | 500 queries/mo | 5,000 queries/mo | 50,000 queries/mo | Custom |
| **AI categorization** | No | 2,000/mo | 20,000/mo | 200,000/mo | Custom |
| **AI extraction** | No | 500/mo | 5,000/mo | 50,000/mo | Custom |
| **IMAP/SMTP access** | No | No | Yes | Yes | Yes |
| **Pods** | 1 (default) | 3 | 10 | Unlimited | Unlimited |
| **API keys** | 1 | 5 | 25 | Unlimited | Unlimited |
| **Support** | Email (48h) | Email (24h) | Email + Chat (4h) | Priority (1h) | Dedicated (custom SLA) |
| **Message retention** | 30 days | 90 days | 365 days | Configurable | Configurable |
| **SSO/SAML** | No | No | No | No | Yes |
| **Audit logs** | No | No | No | Basic | Full |
| **Dedicated IPs** | No | No | No | Optional ($25/mo) | Included |
| **SLA** | None | 99.5% | 99.9% | 99.95% | Custom (up to 99.99%) |

### Free Tier -- Detailed Specification

The free tier is designed to give a developer everything they need to build and validate a proof of concept, without any features that incur per-invocation AWS costs we cannot amortize across free users.

```json
{
  "tier": "free",
  "billing_channel": "none",
  "limits": {
    "inboxes": 5,
    "emails_per_month": 1000,
    "custom_domains": 1,
    "api_rate_limit_per_second": 5,
    "webhook_endpoints": 3,
    "websocket_connections": 1,
    "storage_bytes": 104857600,
    "api_keys": 1,
    "pods": 1
  },
  "features": {
    "rest_api": true,
    "mcp_server": true,
    "websocket": true,
    "otp_extraction": true,
    "long_poll": true,
    "webhooks": true,
    "semantic_search": false,
    "ai_categorization": false,
    "ai_extraction": false,
    "imap_smtp": false,
    "custom_domains": true,
    "audit_logs": false,
    "sso_saml": false,
    "dedicated_ips": false
  },
  "retention_days": 30,
  "overage_policy": "hard_block",
  "support_channel": "email",
  "support_sla_hours": 48
}
```

**What is included and why:**
- **REST API**: The core product. Without it, there is nothing to evaluate.
- **MCP server**: Critical for the AI agent audience. MCP is how agents actually interact with the platform. Excluding it would block the primary use case.
- **WebSocket (1 connection)**: Enables real-time event listening for proof-of-concept demos. One connection is enough for a single agent to subscribe.
- **OTP extraction**: This is the killer feature that hooks developers. It is computationally cheap -- it is regex extraction on already-received email content, no Bedrock tokens involved.
- **Long-poll wait**: Same rationale as OTP. Long-poll is implemented via Lambda with DynamoDB Streams, not Bedrock. The marginal cost is negligible.
- **Webhooks (3 endpoints)**: Essential for event-driven architectures. Three is enough for dev/staging/production or primary/secondary/logging.
- **1 custom domain**: Lets the developer prove the platform works with their domain. One domain is enough for a PoC.

**What is excluded and why:**
- **Semantic search**: Each query invokes Bedrock for embedding generation. At ~$0.0001 per embedding, 1000 queries/month = $0.10/user. Seems small, but at 100K free users = $10,000/month in pure Bedrock cost with zero revenue.
- **AI categorization**: Each categorization invokes a Bedrock model. ~$0.002/invocation. 2000/month per user at 100K users = $400,000/month. Absolutely not on free tier.
- **AI extraction**: Same cost profile as categorization. Cannot be offered for free.
- **IMAP/SMTP**: Requires a Fargate-based protocol proxy (see Section 07). Each concurrent IMAP/SMTP connection holds a container task. Free users on IMAP/SMTP would require scaling ECS tasks proportional to free user count -- an unbounded cost.
- **Multiple pods**: Pods are an organizational feature for platform builders. Free tier users are experimenting, not building multi-tenant platforms. One default pod is sufficient.
- **SSO/SAML, audit logs**: Enterprise features that add implementation complexity with zero value for individual developers.

### Pro Tier -- $29/month

The Pro tier is for individual developers and small teams with production workloads. It unlocks AI features at metered quantities and significantly increases all limits.

```json
{
  "tier": "pro",
  "billing_channel": "stripe",
  "price_monthly_cents": 2900,
  "price_annual_cents": 27840,
  "limits": {
    "inboxes": 25,
    "emails_per_month": 10000,
    "custom_domains": 3,
    "api_rate_limit_per_second": 50,
    "webhook_endpoints": 10,
    "websocket_connections": 5,
    "storage_bytes": 1073741824,
    "api_keys": 5,
    "pods": 3,
    "semantic_search_queries_per_month": 500,
    "ai_categorization_per_month": 2000,
    "ai_extraction_per_month": 500
  },
  "features": {
    "rest_api": true,
    "mcp_server": true,
    "websocket": true,
    "otp_extraction": true,
    "long_poll": true,
    "webhooks": true,
    "semantic_search": true,
    "ai_categorization": true,
    "ai_extraction": true,
    "imap_smtp": false,
    "custom_domains": true,
    "audit_logs": false,
    "sso_saml": false,
    "dedicated_ips": false
  },
  "retention_days": 90,
  "overage_policy": "grace_then_block",
  "overage_grace_percent": 10,
  "support_channel": "email",
  "support_sla_hours": 24
}
```

**Key design decisions for Pro:**
- **$29/month price point**: Low enough that an individual developer can expense it without approval. High enough to cover AWS costs with margin ($29 revenue vs ~$3-5 AWS cost at typical Pro usage).
- **No IMAP/SMTP**: The Pro tier is for API-first users. IMAP/SMTP adds Fargate cost that does not make sense below Business tier.
- **AI quotas are intentionally modest**: 500 semantic searches, 2000 categorizations, 500 extractions. This is enough for real usage but not enough for bulk processing. It creates a natural upgrade path to Business.
- **10% overage grace**: Paid users get a 10% buffer on all numeric limits before hard block. The overage is billed at tier-appropriate rates. This prevents surprise disruptions for slightly bursty workloads while containing cost.

### Business Tier -- $99/month

The Business tier is for teams and companies with significant production workloads. It unlocks IMAP/SMTP and dramatically increases all limits.

```json
{
  "tier": "business",
  "billing_channel": "stripe",
  "price_monthly_cents": 9900,
  "price_annual_cents": 95040,
  "limits": {
    "inboxes": 100,
    "emails_per_month": 50000,
    "custom_domains": 10,
    "api_rate_limit_per_second": 200,
    "webhook_endpoints": 25,
    "websocket_connections": 25,
    "storage_bytes": 10737418240,
    "api_keys": 25,
    "pods": 10,
    "semantic_search_queries_per_month": 5000,
    "ai_categorization_per_month": 20000,
    "ai_extraction_per_month": 5000
  },
  "features": {
    "rest_api": true,
    "mcp_server": true,
    "websocket": true,
    "otp_extraction": true,
    "long_poll": true,
    "webhooks": true,
    "semantic_search": true,
    "ai_categorization": true,
    "ai_extraction": true,
    "imap_smtp": true,
    "custom_domains": true,
    "audit_logs": false,
    "sso_saml": false,
    "dedicated_ips": false
  },
  "retention_days": 365,
  "overage_policy": "grace_then_block",
  "overage_grace_percent": 10,
  "support_channel": "email_and_chat",
  "support_sla_hours": 4
}
```

**Key design decisions for Business:**
- **IMAP/SMTP unlocked**: At $99/month, the Fargate cost for IMAP/SMTP proxy is justified. Business tier users are likely to have legacy integrations that require IMAP/SMTP.
- **10 custom domains**: Enough for a multi-brand company or a platform builder with several client domains.
- **10 pods**: Enables the "platform within a platform" model where a Business customer serves multiple end-customers, each in their own pod.
- **365-day retention**: Production workloads need longer history for compliance, debugging, and audit trails.

### Scale Tier -- $299/month

The Scale tier is the highest self-service tier. It is designed for platform builders and high-volume users who need significant capacity but are not yet ready for (or do not want) an enterprise contract.

```json
{
  "tier": "scale",
  "billing_channel": "stripe",
  "price_monthly_cents": 29900,
  "price_annual_cents": 287040,
  "limits": {
    "inboxes": 500,
    "emails_per_month": 200000,
    "custom_domains": -1,
    "api_rate_limit_per_second": 500,
    "webhook_endpoints": 100,
    "websocket_connections": 100,
    "storage_bytes": 107374182400,
    "api_keys": -1,
    "pods": -1,
    "semantic_search_queries_per_month": 50000,
    "ai_categorization_per_month": 200000,
    "ai_extraction_per_month": 50000
  },
  "features": {
    "rest_api": true,
    "mcp_server": true,
    "websocket": true,
    "otp_extraction": true,
    "long_poll": true,
    "webhooks": true,
    "semantic_search": true,
    "ai_categorization": true,
    "ai_extraction": true,
    "imap_smtp": true,
    "custom_domains": true,
    "audit_logs": true,
    "sso_saml": false,
    "dedicated_ips": true
  },
  "retention_days": -1,
  "overage_policy": "grace_then_block",
  "overage_grace_percent": 10,
  "support_channel": "priority",
  "support_sla_hours": 1
}
```

**Notes:**
- `-1` denotes "unlimited" (enforced at a very high ceiling, e.g., 100,000, to prevent abuse; true unlimited is only on Enterprise).
- **Basic audit logs**: Scale tier gets read-only audit logs for API key usage and inbox lifecycle events. Full audit logs (including admin actions, configuration changes, data access patterns) are Enterprise only.
- **Dedicated IPs**: Available as an add-on at $25/month per IP. Scale tier users sending high volumes need dedicated IPs to maintain sender reputation.
- **Configurable retention**: Scale tier users can set retention from 30 days to 3 years. Longer retention increases storage cost, which is reflected in the storage quota.

### Enterprise / AWS Marketplace Tier

The Enterprise tier is not a fixed tier -- it is a custom engagement delivered through AWS Marketplace.

```
Enterprise features beyond Scale:
- SSO/SAML integration (Cognito User Pool federation)
- Full audit logs (CloudTrail-grade, every API call, every data access)
- SOC2 Type II compliance report
- HIPAA BAA available
- Custom SLA (up to 99.99%)
- Dedicated infrastructure options (isolated DynamoDB table, dedicated SES account)
- Custom data residency (deploy in customer-preferred region)
- Volume discounts on all metering dimensions
- AWS EDP credits apply to AgentMail spend
- Named support engineer
- Quarterly business reviews
- Custom integration support
```

**How it works:**
1. Customer reaches out via "Contact Sales" or is proactively contacted when hitting Scale limits
2. Sales team creates a **Private Offer** on AWS Marketplace
3. Customer accepts the offer through their AWS account
4. Offer can include: custom pricing, committed spend, payment schedule, EULA amendments
5. Customer's existing AgentMail org is migrated from Stripe billing to Marketplace billing (see Section 9)
6. Enterprise features are unlocked via the `tier: "enterprise"` flag on their org record

---

## 3. User Registration and Authentication

### Architecture

```
                                    ┌──────────────────────┐
                                    │   Developer Console   │
                                    │    (React SPA on      │
                                    │     CloudFront)       │
                                    └─────────┬────────────┘
                                              │
                                    ┌─────────▼────────────┐
                                    │    AWS Cognito        │
                                    │    User Pool          │
                                    │                       │
                                    │  - Email/password     │
                                    │  - Google OAuth       │
                                    │  - GitHub OAuth       │
                                    │  - Email verification │
                                    │  - MFA (optional)     │
                                    │  - JWT issuance       │
                                    └─────────┬────────────┘
                                              │
                              ┌───────────────┼───────────────┐
                              │               │               │
                    ┌─────────▼──┐   ┌────────▼───┐  ┌───────▼────────┐
                    │  Console   │   │  REST API  │  │  MCP / WS      │
                    │  Sessions  │   │  (API Keys)│  │  (API Keys)    │
                    │  (JWT)     │   │            │  │                │
                    └────────────┘   └────────────┘  └────────────────┘
```

### Cognito User Pool Configuration

```json
{
  "UserPoolName": "agentmail-saas-users",
  "Policies": {
    "PasswordPolicy": {
      "MinimumLength": 12,
      "RequireUppercase": true,
      "RequireLowercase": true,
      "RequireNumbers": true,
      "RequireSymbols": false,
      "TemporaryPasswordValidityDays": 1
    }
  },
  "AutoVerifiedAttributes": ["email"],
  "UsernameAttributes": ["email"],
  "Schema": [
    {
      "Name": "email",
      "AttributeDataType": "String",
      "Required": true,
      "Mutable": false
    },
    {
      "Name": "custom:org_id",
      "AttributeDataType": "String",
      "Required": false,
      "Mutable": true
    },
    {
      "Name": "custom:tier",
      "AttributeDataType": "String",
      "Required": false,
      "Mutable": true
    }
  ],
  "MfaConfiguration": "OPTIONAL",
  "AccountRecoverySetting": {
    "RecoveryMechanisms": [
      {
        "Priority": 1,
        "Name": "verified_email"
      }
    ]
  },
  "UserPoolTags": {
    "Project": "agentmail",
    "Component": "saas-auth"
  }
}
```

### OAuth Identity Providers

**Google OAuth (Sign in with Google):**

```json
{
  "ProviderName": "Google",
  "ProviderType": "Google",
  "ProviderDetails": {
    "client_id": "${GOOGLE_CLIENT_ID}",
    "client_secret": "${GOOGLE_CLIENT_SECRET}",
    "authorize_scopes": "openid email profile"
  },
  "AttributeMapping": {
    "email": "email",
    "email_verified": "email_verified",
    "name": "name",
    "picture": "picture",
    "username": "sub"
  }
}
```

**GitHub OAuth (Sign in with GitHub):**

GitHub is not a native Cognito provider, so we use the **OIDC provider** type with GitHub as the IdP:

```json
{
  "ProviderName": "GitHub",
  "ProviderType": "OIDC",
  "ProviderDetails": {
    "client_id": "${GITHUB_CLIENT_ID}",
    "client_secret": "${GITHUB_CLIENT_SECRET}",
    "authorize_scopes": "user:email read:user",
    "oidc_issuer": "https://token.actions.githubusercontent.com",
    "authorize_url": "https://github.com/login/oauth/authorize",
    "token_url": "https://github.com/login/oauth/access_token",
    "attributes_url": "https://api.github.com/user",
    "attributes_url_add_attributes": false
  },
  "AttributeMapping": {
    "email": "email",
    "name": "name",
    "username": "id"
  }
}
```

**Note:** GitHub does not support OIDC natively. We implement a thin Lambda-backed adapter behind API Gateway that translates GitHub's OAuth2 flow into the OIDC contract Cognito expects. The adapter:
1. Receives the authorization code from GitHub
2. Exchanges it for an access token via `POST https://github.com/login/oauth/access_token`
3. Fetches user info via `GET https://api.github.com/user`
4. Returns a JWT in OIDC-compliant format

### Registration Flow

```
User clicks "Sign Up" on agentmail.to
        |
        v
Registration form: email, password (or "Sign in with Google/GitHub")
        |
        ├── Email/password path:
        |     |
        |     v
        |   Cognito SignUp API creates unconfirmed user
        |     |
        |     v
        |   Cognito sends verification email (uses SES under the hood)
        |   ** We configure Cognito to use OUR SES verified identity **
        |   ** so the email comes from verify@agentmail.to **
        |     |
        |     v
        |   User enters 6-digit OTP from email
        |     |
        |     v
        |   Cognito ConfirmSignUp confirms the user
        |
        ├── Google/GitHub OAuth path:
        |     |
        |     v
        |   Cognito Hosted UI redirects to provider
        |     |
        |     v
        |   User authenticates with provider
        |     |
        |     v
        |   Cognito receives tokens, creates/links user
        |   (email already verified by provider)
        |
        v
Post-confirmation Lambda trigger fires:
        |
        v
Lambda: create-org-on-signup
  1. Generate org_id (ULID)
  2. Create DynamoDB org record:
     {
       PK: "ORG#org_abc123",
       SK: "METADATA",
       org_id: "org_abc123",
       name: user.email.split("@")[0] + "'s Organization",
       tier: "free",
       billing_channel: "none",
       stripe_customer_id: null,
       marketplace_customer_id: null,
       owner_email: user.email,
       owner_cognito_sub: user.sub,
       created_at: "2026-04-10T12:00:00Z",
       limits: { ... free tier limits ... },
       features: { ... free tier features ... },
       usage_this_month: {
         emails_sent: 0,
         emails_received: 0,
         inboxes_created: 0,
         storage_bytes: 0,
         semantic_searches: 0,
         ai_categorizations: 0,
         ai_extractions: 0
       }
     }
  3. Create default pod:
     {
       PK: "ORG#org_abc123",
       SK: "POD#pod_default",
       pod_id: "pod_default",
       name: "Default",
       created_at: "2026-04-10T12:00:00Z"
     }
  4. Generate initial API key:
     {
       PK: "ORG#org_abc123",
       SK: "APIKEY#ak_live_abc123...",
       key_hash: sha256(api_key),
       name: "Default API Key",
       created_at: "2026-04-10T12:00:00Z",
       last_used_at: null,
       permissions: ["*"]
     }
  5. Also store API key lookup record:
     {
       PK: "APIKEY#ak_live_abc123...",
       SK: "LOOKUP",
       org_id: "org_abc123",
       tier: "free"
     }
  6. Update Cognito user attributes:
     custom:org_id = "org_abc123"
     custom:tier = "free"
  7. Send welcome email (via SES):
     From: hello@agentmail.to
     Subject: "Welcome to AgentMail"
     Body: quickstart guide, API key (masked), link to console
        |
        v
User is redirected to console dashboard with getting-started wizard
```

### Authentication Flows

**Console (web dashboard) authentication:**
- Cognito Hosted UI or embedded Amplify UI components
- Returns JWT (ID token + access token + refresh token)
- ID token contains: `sub`, `email`, `custom:org_id`, `custom:tier`
- Access token used for API Gateway authorizer (Cognito authorizer type)
- Refresh token: 30-day expiry, stored in httpOnly secure cookie
- JWT expiry: 1 hour (ID token), 1 hour (access token)

**API authentication (programmatic access):**
- API key in `Authorization: Bearer ak_live_...` header
- API keys are resolved to `org_id` via the DynamoDB APIKEY lookup record
- API key lookup is cached in Redis with 5-minute TTL
- API keys do not expire (but can be revoked)
- API keys are prefixed: `ak_live_` for production, `ak_test_` for sandbox (future)

**MCP server authentication:**
- Same API key mechanism as REST API
- Key passed in MCP connection parameters
- Resolved identically to REST API

**WebSocket authentication:**
- API key passed as query parameter on connect: `wss://ws.agentmail.to?apiKey=ak_live_...`
- Lambda authorizer on $connect route validates the key
- Connection ID is mapped to org_id in Redis for the duration of the connection

### Account-to-Organization Mapping

```
Cognito User (person)
    |
    | -- has custom:org_id attribute
    | -- can be member of exactly one org (v1)
    | -- future: multiple org membership via Cognito groups
    |
    v
Organization (billing entity)
    |
    | -- has exactly one billing_channel: "none" | "stripe" | "marketplace"
    | -- has one or more Cognito users (owner + team members, future)
    | -- has one or more API keys
    | -- contains pods, inboxes, messages
    |
    v
Billing Channel
    |
    ├── "none" = free tier, no payment method
    ├── "stripe" = direct SaaS, Stripe subscription
    └── "marketplace" = AWS Marketplace contract
```

**Migration path:** When an org moves from free to paid (Stripe) or from Stripe to Marketplace, only the `billing_channel` and associated billing metadata change. The org_id, all data, all inboxes, all API keys remain identical. This is a billing-layer change, not a platform-layer change.

---

## 4. Developer Console

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Developer Console                       │
│                                                              │
│  React SPA (TypeScript, Vite, TailwindCSS, shadcn/ui)      │
│  Hosted on: S3 + CloudFront (agentmail.to/console)          │
│                                                              │
│  Auth: Cognito (JWT) via @aws-amplify/auth                  │
│  API: Same REST API as external users (eat our own dog food)│
│  State: React Query (TanStack Query) for server state       │
│  Charts: Recharts for usage visualization                   │
│                                                              │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           │ HTTPS (JWT in Authorization header)
                           │
                           ▼
                    ┌──────────────┐
                    │ API Gateway  │
                    │ (REST API)   │
                    │              │
                    │ Cognito      │
                    │ Authorizer   │
                    │ (for console)│
                    │              │
                    │ API Key      │
                    │ Authorizer   │
                    │ (for API)    │
                    └──────┬───────┘
                           │
                           ▼
                    Lambda Functions
                    (same functions for console and API users)
```

**Key principle: the console is just another API client.** Every operation the console performs is a standard REST API call with a JWT token instead of an API key. There is no separate "admin API" or "console backend." This ensures:
1. The API is complete -- if the console can do it, so can the API
2. The API is tested -- the console exercises every endpoint
3. Third-party integrations get the same capabilities as the console

### Console Pages and Features

**Dashboard (home page):**
```
┌──────────────────────────────────────────────────────────────────┐
│  AgentMail Console                              [user@email.com] │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Inboxes         │  │  Emails          │  │  Storage         │ │
│  │  3 / 5           │  │  847 / 1,000     │  │  23 MB / 100 MB  │ │
│  │  ████████░░ 60%  │  │  █████████░ 85%  │  │  ███░░░░░░░ 23%  │ │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                   │
│  ⚠ You've used 85% of your monthly email quota.                  │
│    [Upgrade to Pro for 10,000 emails/month →]                    │
│                                                                   │
│  Email Volume (Last 30 Days)                                     │
│  ┌──────────────────────────────────────────┐                    │
│  │    ▄                                      │                    │
│  │   ▄█▄     ▄                               │                    │
│  │  ▄███▄   ▄█▄    ▄▄                        │                    │
│  │ ▄█████▄ ▄███▄  ▄██▄   ▄                   │                    │
│  │▄███████▄█████▄▄████▄ ▄█▄                  │                    │
│  └──────────────────────────────────────────┘                    │
│                                                                   │
│  Recent Activity                                                 │
│  • inbox agent-1@company.com received 12 emails today            │
│  • inbox support-bot@company.com sent 8 emails today             │
│  • Domain company.com verified successfully                      │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

**Inbox Management page:**
- List all inboxes with search and filter
- Create inbox: choose email address, assign to pod, assign to domain
- Delete inbox (with confirmation and data deletion warning)
- Inbox detail: view messages (read-only), see inbox stats, manage allow/block lists
- Inbox message viewer: list messages, view message body (HTML rendered safely in sandboxed iframe), view headers, view attachments

**Domain Management page:**
- List domains with verification status (pending, verified, failed)
- Add domain flow (see Section 8 for full detail):
  - Enter domain name
  - Choose coexistence mode (subdomain, transport rule, standalone, outbound-only)
  - Display DNS records with copy buttons
  - Show verification status per DNS record
  - "Check DNS" button for on-demand verification
  - Green checkmarks as records propagate
- Remove domain (only if no inboxes are assigned to it)

**API Keys page:**
- List API keys (masked, showing only last 4 characters)
- Create new API key (with name/description)
- Revoke API key (with confirmation)
- Show key only once on creation (cannot be retrieved later)
- Copy-to-clipboard button on creation

**Webhook Configuration page:**
- List webhook endpoints with status (active, failing, disabled)
- Add endpoint: URL, events to subscribe to, optional secret for signature verification
- Test endpoint: sends a test event
- View delivery log: last 100 deliveries with status code and response time
- Retry failed deliveries

**Settings page:**
- Account: email, password change, MFA setup
- Organization: name, billing email
- Billing: current plan, usage, upgrade/downgrade, payment method (Stripe Customer Portal link)
- API: default rate limit, IP allowlist (future)
- Danger zone: delete account (requires email confirmation, 30-day grace period)

**Usage Dashboard:**
- Real-time usage meters for all quota dimensions
- Historical charts (daily, weekly, monthly)
- Breakdown by pod and inbox
- Cost projection for paid tiers ("At current usage, you'll hit your email limit in 8 days")
- Export usage data as CSV

**Upgrade Prompts:**
The console strategically surfaces upgrade prompts:
- Dashboard banners when any quota is at 80%+
- Inline messages when a feature gate blocks an action ("Semantic search requires Pro tier")
- Modal when hitting a hard limit ("You've reached 1,000 emails this month")
- Comparison table showing what the next tier unlocks
- One-click upgrade button (opens Stripe Checkout in new tab)

### CloudFront Distribution Configuration

```json
{
  "DistributionConfig": {
    "Origins": [
      {
        "DomainName": "agentmail-console.s3.amazonaws.com",
        "Id": "S3-console-spa",
        "S3OriginConfig": {
          "OriginAccessIdentity": "origin-access-identity/cloudfront/EDFDVBD..."
        }
      }
    ],
    "DefaultCacheBehavior": {
      "AllowedMethods": ["GET", "HEAD"],
      "TargetOriginId": "S3-console-spa",
      "ViewerProtocolPolicy": "redirect-to-https",
      "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6",
      "Compress": true
    },
    "CustomErrorResponses": [
      {
        "ErrorCode": 404,
        "ResponseCode": 200,
        "ResponsePagePath": "/index.html",
        "ErrorCachingMinTTL": 0
      },
      {
        "ErrorCode": 403,
        "ResponseCode": 200,
        "ResponsePagePath": "/index.html",
        "ErrorCachingMinTTL": 0
      }
    ],
    "Aliases": ["console.agentmail.to"],
    "ViewerCertificate": {
      "AcmCertificateArn": "arn:aws:acm:us-east-1:ACCOUNT:certificate/...",
      "SslSupportMethod": "sni-only",
      "MinimumProtocolVersion": "TLSv1.2_2021"
    },
    "HttpVersion": "http2and3",
    "DefaultRootObject": "index.html"
  }
}
```

**Notes:**
- SPA routing: all 404/403 errors return `index.html` so React Router handles client-side routing
- HTTP/3 enabled for performance
- TLS 1.2 minimum
- CloudFront Functions for security headers (CSP, HSTS, X-Frame-Options)

---

## 5. Billing System

### Architecture

```
┌───────────────────────────────────────────────────────────────────┐
│                         Billing System                            │
│                                                                    │
│   Direct SaaS                              AWS Marketplace         │
│   ──────────                              ────────────────         │
│                                                                    │
│   Stripe                                  Marketplace Metering     │
│   ├── Products & Prices                   ├── BatchMeterUsage      │
│   ├── Checkout Sessions                   ├── GetEntitlements      │
│   ├── Billing Portal                      ├── ResolveCustomer      │
│   ├── Subscriptions                       └── SNS Lifecycle Events │
│   ├── Invoices                                                     │
│   ├── Metered Billing (overage)                                    │
│   └── Webhooks                                                     │
│         │                                        │                 │
│         ▼                                        ▼                 │
│   ┌───────────────────────────────────────────────────────┐       │
│   │              DynamoDB Org Record                       │       │
│   │                                                        │       │
│   │  billing_channel: "stripe" | "marketplace" | "none"   │       │
│   │  stripe_customer_id: "cus_..."                         │       │
│   │  stripe_subscription_id: "sub_..."                     │       │
│   │  marketplace_customer_id: "..."                        │       │
│   │  tier: "free" | "pro" | "business" | "scale"          │       │
│   │  billing_period_start: "2026-04-01"                    │       │
│   │  billing_period_end: "2026-05-01"                      │       │
│   │                                                        │       │
│   └───────────────────────────────────────────────────────┘       │
│                                                                    │
└───────────────────────────────────────────────────────────────────┘
```

### Stripe Products and Prices

We create one Stripe Product per tier and one Price per billing interval (monthly/annual):

```python
# Stripe product/price setup (run once, or via Stripe Dashboard)

import stripe

# Pro tier
pro_product = stripe.Product.create(
    name="AgentMail Pro",
    description="25 inboxes, 10K emails/month, AI features",
    metadata={"agentmail_tier": "pro"}
)

pro_monthly = stripe.Price.create(
    product=pro_product.id,
    unit_amount=2900,  # $29.00
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_tier": "pro", "interval": "monthly"}
)

pro_annual = stripe.Price.create(
    product=pro_product.id,
    unit_amount=2320,  # $23.20/month billed annually ($278.40/year = 20% discount)
    currency="usd",
    recurring={"interval": "month", "interval_count": 12},
    metadata={"agentmail_tier": "pro", "interval": "annual"}
)

# Business tier
business_product = stripe.Product.create(
    name="AgentMail Business",
    description="100 inboxes, 50K emails/month, IMAP/SMTP, full AI",
    metadata={"agentmail_tier": "business"}
)

business_monthly = stripe.Price.create(
    product=business_product.id,
    unit_amount=9900,  # $99.00
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_tier": "business", "interval": "monthly"}
)

business_annual = stripe.Price.create(
    product=business_product.id,
    unit_amount=7920,  # $79.20/month billed annually ($950.40/year = 20% discount)
    currency="usd",
    recurring={"interval": "month", "interval_count": 12},
    metadata={"agentmail_tier": "business", "interval": "annual"}
)

# Scale tier
scale_product = stripe.Product.create(
    name="AgentMail Scale",
    description="500 inboxes, 200K emails/month, unlimited pods, priority support",
    metadata={"agentmail_tier": "scale"}
)

scale_monthly = stripe.Price.create(
    product=scale_product.id,
    unit_amount=29900,  # $299.00
    currency="usd",
    recurring={"interval": "month"},
    metadata={"agentmail_tier": "scale", "interval": "monthly"}
)

scale_annual = stripe.Price.create(
    product=scale_product.id,
    unit_amount=23920,  # $239.20/month billed annually ($2,870.40/year = 20% discount)
    currency="usd",
    recurring={"interval": "month", "interval_count": 12},
    metadata={"agentmail_tier": "scale", "interval": "annual"}
)

# Overage metered prices (per-unit, usage-based)
email_overage = stripe.Price.create(
    product=pro_product.id,  # Shared across tiers, linked to whichever product
    nickname="Email Overage",
    unit_amount=5,  # $0.05 per email over quota
    currency="usd",
    recurring={"interval": "month", "usage_type": "metered", "aggregate_usage": "sum"},
    metadata={"agentmail_dimension": "email_overage"}
)

search_overage = stripe.Price.create(
    product=pro_product.id,
    nickname="Semantic Search Overage",
    unit_amount=2,  # $0.02 per search over quota
    currency="usd",
    recurring={"interval": "month", "usage_type": "metered", "aggregate_usage": "sum"},
    metadata={"agentmail_dimension": "search_overage"}
)

categorization_overage = stripe.Price.create(
    product=pro_product.id,
    nickname="AI Categorization Overage",
    unit_amount=1,  # $0.01 per categorization over quota
    currency="usd",
    recurring={"interval": "month", "usage_type": "metered", "aggregate_usage": "sum"},
    metadata={"agentmail_dimension": "categorization_overage"}
)

extraction_overage = stripe.Price.create(
    product=pro_product.id,
    nickname="AI Extraction Overage",
    unit_amount=3,  # $0.03 per extraction over quota
    currency="usd",
    recurring={"interval": "month", "usage_type": "metered", "aggregate_usage": "sum"},
    metadata={"agentmail_dimension": "extraction_overage"}
)
```

### Checkout Session Flow (Free to Paid Upgrade)

```python
# Lambda: create-checkout-session
# Called when user clicks "Upgrade to Pro" in console

import stripe
import json

def handler(event, context):
    # JWT from Cognito authorizer contains org_id
    org_id = event['requestContext']['authorizer']['claims']['custom:org_id']
    body = json.loads(event['body'])
    
    tier = body['tier']  # "pro", "business", or "scale"
    interval = body.get('interval', 'monthly')  # "monthly" or "annual"
    
    # Get org record to check current state
    org = get_org(org_id)
    
    if org['billing_channel'] == 'marketplace':
        return error_response(400, "Organization is billed through AWS Marketplace")
    
    # Get or create Stripe customer
    if org.get('stripe_customer_id'):
        customer_id = org['stripe_customer_id']
    else:
        customer = stripe.Customer.create(
            email=org['owner_email'],
            metadata={
                'agentmail_org_id': org_id,
                'agentmail_tier': tier
            }
        )
        customer_id = customer.id
        # Store customer ID on org record
        update_org(org_id, stripe_customer_id=customer_id)
    
    # Look up the price ID for the requested tier/interval
    price_id = PRICE_MAP[tier][interval]
    
    # Build line items: base subscription + metered overage prices
    line_items = [
        {"price": price_id, "quantity": 1}
    ]
    
    # Add metered prices for overage tracking (paid tiers only)
    if tier in ('pro', 'business', 'scale'):
        line_items.extend([
            {"price": OVERAGE_PRICES['email'], "quantity": None},      # metered
            {"price": OVERAGE_PRICES['search'], "quantity": None},     # metered
            {"price": OVERAGE_PRICES['categorize'], "quantity": None}, # metered
            {"price": OVERAGE_PRICES['extract'], "quantity": None},    # metered
        ])
    
    # Create Stripe Checkout Session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=['card'],
        mode='subscription',
        line_items=line_items,
        success_url='https://console.agentmail.to/settings/billing?session_id={CHECKOUT_SESSION_ID}&status=success',
        cancel_url='https://console.agentmail.to/settings/billing?status=cancelled',
        metadata={
            'agentmail_org_id': org_id,
            'agentmail_tier': tier
        },
        subscription_data={
            'metadata': {
                'agentmail_org_id': org_id,
                'agentmail_tier': tier
            }
        },
        allow_promotion_codes=True,
        billing_address_collection='auto',
        tax_id_collection={'enabled': True}
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'checkout_url': session.url,
            'session_id': session.id
        })
    }
```

### Stripe Customer Portal

For self-service billing management (update payment method, download invoices, cancel subscription):

```python
# Lambda: create-billing-portal-session

def handler(event, context):
    org_id = event['requestContext']['authorizer']['claims']['custom:org_id']
    org = get_org(org_id)
    
    if not org.get('stripe_customer_id'):
        return error_response(400, "No billing account. Upgrade to a paid plan first.")
    
    session = stripe.billing_portal.Session.create(
        customer=org['stripe_customer_id'],
        return_url='https://console.agentmail.to/settings/billing',
        configuration=PORTAL_CONFIG_ID  # Pre-configured in Stripe Dashboard
    )
    
    return {
        'statusCode': 200,
        'body': json.dumps({'portal_url': session.url})
    }
```

**Portal configuration** (created once in Stripe Dashboard or API):
```python
portal_config = stripe.billing_portal.Configuration.create(
    business_profile={
        "headline": "Manage your AgentMail subscription",
        "privacy_policy_url": "https://agentmail.to/privacy",
        "terms_of_service_url": "https://agentmail.to/terms"
    },
    features={
        "customer_update": {
            "enabled": True,
            "allowed_updates": ["email", "tax_id"]
        },
        "invoice_history": {"enabled": True},
        "payment_method_update": {"enabled": True},
        "subscription_cancel": {
            "enabled": True,
            "mode": "at_period_end",
            "cancellation_reason": {
                "enabled": True,
                "options": [
                    "too_expensive",
                    "missing_features",
                    "switched_service",
                    "unused",
                    "other"
                ]
            }
        },
        "subscription_update": {
            "enabled": True,
            "default_allowed_updates": ["price"],
            "proration_behavior": "always_invoice",
            "products": [
                {
                    "product": PRO_PRODUCT_ID,
                    "prices": [PRO_MONTHLY_PRICE, PRO_ANNUAL_PRICE]
                },
                {
                    "product": BUSINESS_PRODUCT_ID,
                    "prices": [BUSINESS_MONTHLY_PRICE, BUSINESS_ANNUAL_PRICE]
                },
                {
                    "product": SCALE_PRODUCT_ID,
                    "prices": [SCALE_MONTHLY_PRICE, SCALE_ANNUAL_PRICE]
                }
            ]
        }
    }
)
```

### Webhook Handler

A single Lambda function receives all Stripe webhook events via API Gateway:

```python
# Lambda: stripe-webhook-handler
# Endpoint: POST /webhooks/stripe (no auth -- verified by Stripe signature)

import stripe
import json
import hashlib
import hmac

STRIPE_WEBHOOK_SECRET = get_secret('stripe-webhook-secret')

def handler(event, context):
    payload = event['body']
    sig_header = event['headers'].get('Stripe-Signature', '')
    
    # Verify webhook signature (critical -- prevents spoofed events)
    try:
        stripe_event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return {'statusCode': 400, 'body': 'Invalid signature'}
    
    event_type = stripe_event['type']
    data = stripe_event['data']['object']
    
    # ── Checkout completed: user just subscribed ──
    if event_type == 'checkout.session.completed':
        handle_checkout_completed(data)
    
    # ── Subscription created ──
    elif event_type == 'customer.subscription.created':
        handle_subscription_created(data)
    
    # ── Subscription updated (tier change, renewal) ──
    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data)
    
    # ── Subscription cancelled ──
    elif event_type == 'customer.subscription.deleted':
        handle_subscription_cancelled(data)
    
    # ── Invoice paid (monthly renewal success) ──
    elif event_type == 'invoice.paid':
        handle_invoice_paid(data)
    
    # ── Invoice payment failed ──
    elif event_type == 'invoice.payment_failed':
        handle_payment_failed(data)
    
    # ── Invoice finalized (for record keeping) ──
    elif event_type == 'invoice.finalized':
        handle_invoice_finalized(data)
    
    return {'statusCode': 200, 'body': 'OK'}


def handle_checkout_completed(session):
    """User completed Stripe Checkout. Upgrade their org."""
    org_id = session['metadata']['agentmail_org_id']
    tier = session['metadata']['agentmail_tier']
    subscription_id = session['subscription']
    customer_id = session['customer']
    
    # Update org record
    update_org(org_id,
        tier=tier,
        billing_channel='stripe',
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        limits=TIER_LIMITS[tier],
        features=TIER_FEATURES[tier],
        retention_days=TIER_RETENTION[tier],
        upgraded_at=now_iso8601()
    )
    
    # Update Cognito user attribute
    update_cognito_user_tier(org_id, tier)
    
    # Invalidate Redis cache for this org
    invalidate_org_cache(org_id)
    
    # Send upgrade confirmation email
    send_email(
        to=get_org_owner_email(org_id),
        template='upgrade-confirmation',
        data={'tier': tier, 'features': TIER_FEATURES[tier]}
    )
    
    # Emit event for analytics
    emit_event('org.upgraded', {
        'org_id': org_id,
        'from_tier': 'free',
        'to_tier': tier,
        'billing_channel': 'stripe'
    })


def handle_subscription_updated(subscription):
    """Subscription was updated (tier change or renewal)."""
    org_id = subscription['metadata'].get('agentmail_org_id')
    if not org_id:
        return  # Not an AgentMail subscription
    
    new_tier = subscription['metadata'].get('agentmail_tier')
    status = subscription['status']
    
    if status == 'active':
        update_org(org_id,
            tier=new_tier,
            limits=TIER_LIMITS[new_tier],
            features=TIER_FEATURES[new_tier],
            retention_days=TIER_RETENTION[new_tier]
        )
        invalidate_org_cache(org_id)
    
    elif status == 'past_due':
        # Payment failed but subscription is in retry period
        # Do NOT downgrade yet -- Stripe will retry
        send_email(
            to=get_org_owner_email(org_id),
            template='payment-past-due',
            data={'retry_count': get_retry_count(subscription)}
        )
    
    elif status in ('canceled', 'unpaid'):
        # Subscription terminated -- downgrade to free
        handle_downgrade_to_free(org_id)


def handle_subscription_cancelled(subscription):
    """Subscription was cancelled (end of billing period or immediate)."""
    org_id = subscription['metadata'].get('agentmail_org_id')
    if not org_id:
        return
    
    handle_downgrade_to_free(org_id)


def handle_payment_failed(invoice):
    """Payment failed. Stripe will retry per dunning settings."""
    customer_id = invoice['customer']
    org_id = get_org_by_stripe_customer(customer_id)
    attempt_count = invoice['attempt_count']
    
    if attempt_count == 1:
        # First failure: gentle reminder
        send_email(
            to=get_org_owner_email(org_id),
            template='payment-failed-first',
            data={'amount': invoice['amount_due'] / 100, 'next_retry': 'in 3 days'}
        )
    elif attempt_count == 2:
        # Second failure: more urgent
        send_email(
            to=get_org_owner_email(org_id),
            template='payment-failed-second',
            data={'amount': invoice['amount_due'] / 100, 'next_retry': 'in 3 days'}
        )
    elif attempt_count >= 3:
        # Third failure: final warning, will downgrade
        send_email(
            to=get_org_owner_email(org_id),
            template='payment-failed-final',
            data={
                'amount': invoice['amount_due'] / 100,
                'downgrade_date': 'in 24 hours',
                'data_deletion_date': 'in 30 days'
            }
        )


def handle_invoice_paid(invoice):
    """Invoice was successfully paid. Reset monthly usage counters."""
    customer_id = invoice['customer']
    org_id = get_org_by_stripe_customer(customer_id)
    
    if not org_id:
        return
    
    # Reset monthly usage counters on successful renewal
    reset_monthly_usage(org_id)
    
    # Store invoice reference
    store_invoice(org_id, {
        'invoice_id': invoice['id'],
        'amount': invoice['amount_paid'],
        'period_start': invoice['period_start'],
        'period_end': invoice['period_end'],
        'pdf_url': invoice['invoice_pdf'],
        'status': 'paid'
    })


def handle_downgrade_to_free(org_id):
    """Downgrade an org to free tier."""
    org = get_org(org_id)
    previous_tier = org['tier']
    
    update_org(org_id,
        tier='free',
        billing_channel='none',
        stripe_subscription_id=None,
        limits=TIER_LIMITS['free'],
        features=TIER_FEATURES['free'],
        retention_days=30,
        downgraded_at=now_iso8601(),
        previous_tier=previous_tier
    )
    
    update_cognito_user_tier(org_id, 'free')
    invalidate_org_cache(org_id)
    
    # If org exceeds free tier limits, resources are NOT deleted immediately.
    # They become read-only. User has 30 days to either upgrade or export.
    # After 30 days, auto-deletion of resources exceeding free tier limits begins.
    if org_exceeds_free_limits(org_id):
        schedule_excess_resource_cleanup(org_id, days=30)
    
    send_email(
        to=get_org_owner_email(org_id),
        template='downgraded-to-free',
        data={
            'previous_tier': previous_tier,
            'excess_inboxes': max(0, count_inboxes(org_id) - 5),
            'data_retention_deadline': (now() + timedelta(days=30)).isoformat()
        }
    )
    
    emit_event('org.downgraded', {
        'org_id': org_id,
        'from_tier': previous_tier,
        'to_tier': 'free',
        'reason': 'payment_failure'
    })
```

### Dunning Sequence

```
Day 0: Payment fails
  └── Email: "We couldn't process your payment"
  └── Stripe auto-retries in 3 days
  └── Console: yellow banner "Payment issue -- update payment method"

Day 3: Stripe retry #1 fails
  └── Email: "Second attempt failed -- please update your payment method"
  └── Stripe auto-retries in 3 days
  └── Console: orange banner "Payment failing -- service may be interrupted"

Day 6: Stripe retry #2 fails
  └── Email: "Final warning -- your account will be downgraded in 24 hours"
  └── Console: red banner "Action required: update payment or lose paid features"

Day 7: Stripe retry #3 fails (or subscription marked unpaid)
  └── Subscription cancelled
  └── Org downgraded to free tier immediately
  └── Email: "Your account has been downgraded to Free"
  └── All resources exceeding free tier become read-only
  └── 30-day countdown to data deletion begins

Day 37: Data deletion
  └── Inboxes beyond the first 5 are deleted (oldest first)
  └── Messages beyond 30-day retention are deleted
  └── Storage exceeding 100MB is purged (oldest attachments first)
  └── Email: "Data deletion complete -- remaining data preserved on Free tier"
```

### Usage-Based Overage Billing

For paid tiers, the 10% grace overage is billed via Stripe Metered Billing:

```python
# Lambda: record-overage-usage
# Called by the feature gate when usage exceeds the tier's included quota
# but is within the 10% grace window

def record_overage(org_id, dimension, quantity):
    """Report overage usage to Stripe for metered billing."""
    org = get_org(org_id)
    
    if org['billing_channel'] != 'stripe':
        return  # Marketplace orgs use BatchMeterUsage instead
    
    subscription_id = org['stripe_subscription_id']
    
    # Find the subscription item for this dimension's metered price
    subscription = stripe.Subscription.retrieve(subscription_id)
    metered_item = None
    for item in subscription['items']['data']:
        if item['price']['metadata'].get('agentmail_dimension') == f'{dimension}_overage':
            metered_item = item
            break
    
    if not metered_item:
        return
    
    # Report usage to Stripe
    stripe.SubscriptionItem.create_usage_record(
        metered_item['id'],
        quantity=quantity,
        timestamp=int(time.time()),
        action='increment'
    )
    
    # Also record locally for our dashboards
    record_usage_event(org_id, dimension, quantity, 'overage')
```

### Proration on Tier Changes

Stripe handles proration automatically when configured correctly:

- **Upgrade (Pro to Business)**: Immediate. Stripe calculates the prorated charge for the remainder of the billing cycle at the new price minus credit for the unused portion of the old price. Charged immediately.
- **Downgrade (Business to Pro)**: Takes effect at the end of the current billing period. No immediate refund -- the customer has already paid for the current period. They retain Business features until the period ends.

```python
# Lambda: change-subscription-tier

def handler(event, context):
    org_id = event['requestContext']['authorizer']['claims']['custom:org_id']
    body = json.loads(event['body'])
    new_tier = body['tier']
    
    org = get_org(org_id)
    current_tier = org['tier']
    
    if org['billing_channel'] != 'stripe':
        return error_response(400, "Cannot change tier for Marketplace-billed org")
    
    tier_rank = {'free': 0, 'pro': 1, 'business': 2, 'scale': 3}
    is_upgrade = tier_rank[new_tier] > tier_rank[current_tier]
    
    subscription = stripe.Subscription.retrieve(org['stripe_subscription_id'])
    
    # Find the base price subscription item
    base_item = None
    for item in subscription['items']['data']:
        if item['price']['recurring']['usage_type'] != 'metered':
            base_item = item
            break
    
    new_price_id = PRICE_MAP[new_tier][get_current_interval(subscription)]
    
    if is_upgrade:
        # Upgrade: immediate proration
        stripe.Subscription.modify(
            subscription.id,
            items=[{
                'id': base_item['id'],
                'price': new_price_id
            }],
            proration_behavior='always_invoice',
            metadata={'agentmail_tier': new_tier}
        )
    else:
        # Downgrade: at period end
        stripe.Subscription.modify(
            subscription.id,
            items=[{
                'id': base_item['id'],
                'price': new_price_id
            }],
            proration_behavior='none',
            metadata={
                'agentmail_tier': new_tier,
                'agentmail_pending_downgrade': 'true',
                'agentmail_downgrade_effective': subscription['current_period_end']
            }
        )
        # Note: actual tier change happens when invoice.paid fires for the new period
    
    # For upgrades, update org immediately
    if is_upgrade:
        update_org(org_id,
            tier=new_tier,
            limits=TIER_LIMITS[new_tier],
            features=TIER_FEATURES[new_tier],
            retention_days=TIER_RETENTION[new_tier]
        )
        invalidate_org_cache(org_id)
    
    return success_response({
        'tier': new_tier,
        'effective': 'immediate' if is_upgrade else 'end_of_period',
        'proration_amount': calculate_proration(subscription, new_price_id) if is_upgrade else 0
    })
```

---

## 6. Feature Gating Architecture

### Overview

Every API request passes through a feature gate middleware that checks three things in order:

1. **Is this feature enabled for the org's tier?** (e.g., semantic search requires Pro+)
2. **Is the org within its quota for this resource?** (e.g., 847/1000 emails used this month)
3. **Is the request within rate limits?** (e.g., 5 req/sec for free tier)

If any check fails, the request is rejected with an appropriate error code and an `upgrade_url` in the response body.

### Architecture

```
API Request
    │
    ▼
API Gateway
    │
    ▼
Lambda Authorizer
    │── Resolves API key to org_id
    │── Returns org_id, tier, billing_channel as context
    │
    ▼
Feature Gate Middleware (runs in every Lambda function)
    │
    ├── 1. Feature Check
    │   │── Is this endpoint available on this tier?
    │   │── If no: return 403 with upgrade_url
    │   │
    ├── 2. Quota Check
    │   │── Load org usage from Redis (or DynamoDB fallback)
    │   │── Compare against tier limits
    │   │── If exceeded:
    │   │   │── Free tier: hard block (429)
    │   │   │── Paid tier within grace: allow + record overage
    │   │   │── Paid tier beyond grace: hard block (429)
    │   │
    ├── 3. Rate Limit Check
    │   │── Redis INCR with TTL (sliding window)
    │   │── If exceeded: return 429 with Retry-After header
    │   │
    └── 4. All checks pass: execute request
            │── After execution: increment usage counters
            │── Add X-RateLimit-* and X-Quota-* headers to response
```

### Feature Gate Implementation

```python
# middleware/feature_gate.py
# Imported and called at the top of every Lambda handler

import json
import time
import redis

REDIS = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

# Feature-to-minimum-tier mapping
FEATURE_TIERS = {
    '/v1/search':           'pro',      # Semantic search
    '/v1/categorize':       'pro',      # AI categorization
    '/v1/extract':          'pro',      # AI extraction
    '/v1/inboxes/*/imap':   'business', # IMAP access
    '/v1/inboxes/*/smtp':   'business', # SMTP access
    '/v1/audit-logs':       'scale',    # Audit logs
}

TIER_RANK = {
    'free': 0,
    'pro': 1,
    'business': 2,
    'scale': 3,
    'enterprise': 4
}

# Quota dimensions and their tier limits
TIER_LIMITS = {
    'free': {
        'emails_per_month': 1000,
        'inboxes': 5,
        'storage_bytes': 104857600,          # 100 MB
        'custom_domains': 1,
        'webhook_endpoints': 3,
        'websocket_connections': 1,
        'api_keys': 1,
        'pods': 1,
        'semantic_searches_per_month': 0,    # Disabled
        'ai_categorizations_per_month': 0,   # Disabled
        'ai_extractions_per_month': 0,       # Disabled
    },
    'pro': {
        'emails_per_month': 10000,
        'inboxes': 25,
        'storage_bytes': 1073741824,         # 1 GB
        'custom_domains': 3,
        'webhook_endpoints': 10,
        'websocket_connections': 5,
        'api_keys': 5,
        'pods': 3,
        'semantic_searches_per_month': 500,
        'ai_categorizations_per_month': 2000,
        'ai_extractions_per_month': 500,
    },
    'business': {
        'emails_per_month': 50000,
        'inboxes': 100,
        'storage_bytes': 10737418240,        # 10 GB
        'custom_domains': 10,
        'webhook_endpoints': 25,
        'websocket_connections': 25,
        'api_keys': 25,
        'pods': 10,
        'semantic_searches_per_month': 5000,
        'ai_categorizations_per_month': 20000,
        'ai_extractions_per_month': 5000,
    },
    'scale': {
        'emails_per_month': 200000,
        'inboxes': 500,
        'storage_bytes': 107374182400,       # 100 GB
        'custom_domains': 100000,            # "Unlimited"
        'webhook_endpoints': 100,
        'websocket_connections': 100,
        'api_keys': 100000,                  # "Unlimited"
        'pods': 100000,                      # "Unlimited"
        'semantic_searches_per_month': 50000,
        'ai_categorizations_per_month': 200000,
        'ai_extractions_per_month': 50000,
    }
}

RATE_LIMITS = {
    'free': 5,       # req/sec
    'pro': 50,
    'business': 200,
    'scale': 500,
    'enterprise': 1000  # Default, can be customized
}


class FeatureGateError(Exception):
    def __init__(self, status_code, error_code, message, upgrade_url=None):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.upgrade_url = upgrade_url


def check_feature_gate(org_id, tier, endpoint, method='GET'):
    """
    Main entry point for feature gating.
    Call at the top of every Lambda handler.
    Raises FeatureGateError if the request should be blocked.
    Returns a dict of response headers to add (quota/rate limit info).
    """
    headers = {}
    
    # 1. Feature availability check
    check_feature_availability(tier, endpoint)
    
    # 2. Rate limit check
    check_rate_limit(org_id, tier, headers)
    
    # 3. Quota check (for quota-consuming endpoints)
    check_quota(org_id, tier, endpoint, headers)
    
    return headers


def check_feature_availability(tier, endpoint):
    """Check if the endpoint is available on this tier."""
    for pattern, min_tier in FEATURE_TIERS.items():
        if matches_pattern(endpoint, pattern):
            if TIER_RANK[tier] < TIER_RANK[min_tier]:
                raise FeatureGateError(
                    status_code=403,
                    error_code='feature_not_available',
                    message=f'This feature requires {min_tier} tier or above.',
                    upgrade_url=f'https://console.agentmail.to/settings/billing?upgrade_to={min_tier}'
                )


def check_rate_limit(org_id, tier, headers):
    """Sliding window rate limiter using Redis."""
    limit = RATE_LIMITS.get(tier, 5)
    window_key = f'ratelimit:{org_id}:{int(time.time())}'
    
    pipe = REDIS.pipeline()
    pipe.incr(window_key)
    pipe.expire(window_key, 2)  # 2-second TTL covers the 1-second window
    result = pipe.execute()
    current = result[0]
    
    headers['X-RateLimit-Limit'] = str(limit)
    headers['X-RateLimit-Remaining'] = str(max(0, limit - current))
    headers['X-RateLimit-Reset'] = str(int(time.time()) + 1)
    
    if current > limit:
        raise FeatureGateError(
            status_code=429,
            error_code='rate_limit_exceeded',
            message=f'Rate limit exceeded. Limit: {limit} req/sec.',
            upgrade_url=f'https://console.agentmail.to/settings/billing'
        )


def check_quota(org_id, tier, endpoint, headers):
    """Check usage quota for the requested operation."""
    dimension = get_quota_dimension(endpoint)
    if not dimension:
        return  # Endpoint doesn't consume a metered quota
    
    # Load usage from Redis (cached) or DynamoDB (fallback)
    usage = get_org_usage(org_id)
    limit = TIER_LIMITS[tier].get(dimension)
    
    if limit is None or limit == 0:
        # Feature disabled for this tier (e.g., semantic search on free)
        raise FeatureGateError(
            status_code=403,
            error_code='feature_not_available',
            message=f'{dimension} is not available on the {tier} tier.',
            upgrade_url=f'https://console.agentmail.to/settings/billing'
        )
    
    current = usage.get(dimension, 0)
    
    # Add quota headers
    headers[f'X-Quota-{dimension}-Limit'] = str(limit)
    headers[f'X-Quota-{dimension}-Used'] = str(current)
    headers[f'X-Quota-{dimension}-Remaining'] = str(max(0, limit - current))
    
    # Check if at 80% -- add upgrade hint header
    if current >= limit * 0.8:
        headers['X-Quota-Warning'] = f'{dimension} at {int(current/limit*100)}% of limit'
        headers['X-Upgrade-URL'] = 'https://console.agentmail.to/settings/billing'
    
    if current >= limit:
        if tier == 'free':
            # Free tier: hard block, no overage
            raise FeatureGateError(
                status_code=429,
                error_code='quota_exceeded',
                message=f'Monthly {dimension} quota exceeded ({current}/{limit}). '
                        f'Resets on {get_next_billing_date(org_id)}.',
                upgrade_url=f'https://console.agentmail.to/settings/billing'
            )
        else:
            # Paid tier: check grace window (10% overage)
            grace_limit = int(limit * 1.10)
            if current >= grace_limit:
                # Beyond grace -- hard block
                raise FeatureGateError(
                    status_code=429,
                    error_code='quota_exceeded_with_overage',
                    message=f'Monthly {dimension} quota exceeded including 10% grace '
                            f'({current}/{grace_limit}). Upgrade for higher limits.',
                    upgrade_url=f'https://console.agentmail.to/settings/billing'
                )
            else:
                # Within grace -- allow but record overage
                overage_amount = current - limit
                record_overage(org_id, dimension, 1)
                headers['X-Quota-Overage'] = str(overage_amount)
                headers['X-Quota-Overage-Billed'] = 'true'


def get_quota_dimension(endpoint):
    """Map an API endpoint to its quota dimension."""
    DIMENSION_MAP = {
        'POST /v1/inboxes/*/messages': 'emails_per_month',
        'POST /v1/messages/send': 'emails_per_month',
        'POST /v1/search': 'semantic_searches_per_month',
        'POST /v1/categorize': 'ai_categorizations_per_month',
        'POST /v1/extract': 'ai_extractions_per_month',
        'POST /v1/inboxes': 'inboxes',
        'POST /v1/domains': 'custom_domains',
        'POST /v1/webhooks': 'webhook_endpoints',
        'POST /v1/api-keys': 'api_keys',
        'POST /v1/pods': 'pods',
    }
    for pattern, dimension in DIMENSION_MAP.items():
        method_pattern, path_pattern = pattern.split(' ', 1)
        if matches_pattern(endpoint, path_pattern):
            return dimension
    return None


def get_org_usage(org_id):
    """
    Get current month's usage for an org.
    Cached in Redis with 60-second TTL.
    Falls back to DynamoDB if Redis is unavailable.
    """
    cache_key = f'usage:{org_id}:{current_month()}'
    
    cached = REDIS.get(cache_key)
    if cached:
        return json.loads(cached)
    
    # DynamoDB fallback
    usage = query_dynamodb_usage(org_id, current_month())
    
    # Cache for 60 seconds
    REDIS.setex(cache_key, 60, json.dumps(usage))
    
    return usage
```

### Usage Counter Updates

Usage counters are updated atomically after each successful API operation:

```python
# middleware/usage_counter.py

def increment_usage(org_id, dimension, amount=1):
    """
    Atomically increment a usage counter.
    Uses DynamoDB atomic counter as source of truth.
    Updates Redis cache for fast reads.
    """
    # DynamoDB atomic increment (source of truth)
    response = dynamodb.update_item(
        TableName='agentmail-main',
        Key={
            'PK': {'S': f'ORG#{org_id}'},
            'SK': {'S': f'USAGE#{current_month()}'}
        },
        UpdateExpression=f'ADD #dim :amount',
        ExpressionAttributeNames={'#dim': dimension},
        ExpressionAttributeValues={':amount': {'N': str(amount)}},
        ReturnValues='UPDATED_NEW'
    )
    
    new_value = int(response['Attributes'][dimension]['N'])
    
    # Update Redis cache
    cache_key = f'usage:{org_id}:{current_month()}'
    REDIS.hset(cache_key, dimension, new_value)
    REDIS.expire(cache_key, 60)
    
    return new_value
```

### Response Format for Gated Requests

**403 -- Feature not available:**
```json
{
  "error": {
    "code": "feature_not_available",
    "message": "Semantic search requires Pro tier or above.",
    "tier_required": "pro",
    "current_tier": "free",
    "upgrade_url": "https://console.agentmail.to/settings/billing?upgrade_to=pro"
  }
}
```

**429 -- Quota exceeded (free tier):**
```json
{
  "error": {
    "code": "quota_exceeded",
    "message": "Monthly email quota exceeded (1000/1000). Resets on 2026-05-01.",
    "dimension": "emails_per_month",
    "current_usage": 1000,
    "limit": 1000,
    "resets_at": "2026-05-01T00:00:00Z",
    "upgrade_url": "https://console.agentmail.to/settings/billing?upgrade_to=pro"
  }
}
```

**429 -- Rate limit exceeded:**
```json
{
  "error": {
    "code": "rate_limit_exceeded",
    "message": "Rate limit exceeded. Limit: 5 req/sec. Try again in 1 second.",
    "limit": 5,
    "retry_after_seconds": 1,
    "upgrade_url": "https://console.agentmail.to/settings/billing"
  }
}
```

**Successful response with quota headers:**
```
HTTP/1.1 200 OK
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 3
X-RateLimit-Reset: 1712764801
X-Quota-emails_per_month-Limit: 1000
X-Quota-emails_per_month-Used: 847
X-Quota-emails_per_month-Remaining: 153
X-Quota-Warning: emails_per_month at 85% of limit
X-Upgrade-URL: https://console.agentmail.to/settings/billing
```

---

## 7. Cost Containment for Free Tier

### Per-Free-User Cost Ceiling Analysis

This analysis determines the maximum cost a single free-tier user can impose on the platform per month, assuming they use every resource to its limit.

**DynamoDB costs:**
```
Inboxes: 5 inboxes x 1 WCU (create) = 5 WCU = $0.000006
Messages: 1,000 messages x 5 WCU = 5,000 WCU = $0.00625
Message reads: 1,000 messages x 2 RCU x 10 reads = 20,000 RCU = $0.005
Inbox queries: ~500 queries x 2 RCU = 1,000 RCU = $0.00025
Storage: ~30 KB/message x 1,000 = 30 MB x $0.25/GB = $0.0075
DynamoDB Streams: 1,000 records x $0.02/100K = $0.0002
─────────────────────────────────────────────────────────────
DynamoDB total per free user: ~$0.02/month
```

**SES costs:**
```
Outbound: 500 emails x $0.10/1000 = $0.05
Inbound: 500 emails x $0.10/1000 = $0.05
Data (outbound): 500 x 25 KB = 12.5 MB x $0.12/GB = $0.0015
Data (inbound): 500 x 25 KB = 12.5 MB (included in receiving price)
─────────────────────────────────────────────────────────────
SES total per free user: ~$0.10/month
```

**S3 costs:**
```
Storage: 100 MB (max) x $0.023/GB = $0.0023
PUT requests: 1,000 x $0.005/1000 = $0.005
GET requests: 5,000 x $0.0004/1000 = $0.002
─────────────────────────────────────────────────────────────
S3 total per free user: ~$0.01/month
```

**Lambda costs:**
```
Invocations: ~3,000 (API calls + event processing) x $0.20/1M = $0.0006
Duration: 3,000 x 200ms x 512 MB = 300 GB-sec x $0.0000166667 = $0.005
─────────────────────────────────────────────────────────────
Lambda total per free user: ~$0.006/month
```

**Other costs:**
```
Kinesis: 1,000 records, negligible = ~$0.001
Redis: shared, per-user fraction = ~$0.001
API Gateway: 3,000 requests x $3.50/1M = $0.01
WebSocket: 1 connection x ~30 min/day x 30 days = 900 min = $0.003
CloudWatch: logs ~50 MB/user/month = $0.025
─────────────────────────────────────────────────────────────
Other total per free user: ~$0.04/month
```

### Cost Summary Per Free User

```
┌─────────────────────────────────────────────────────┐
│         Per-Free-User Monthly Cost Ceiling           │
├──────────────────────────┬──────────────────────────┤
│ Component                │ Max Monthly Cost          │
├──────────────────────────┼──────────────────────────┤
│ DynamoDB                 │ $0.020                    │
│ SES                      │ $0.100                    │
│ S3                       │ $0.010                    │
│ Lambda                   │ $0.006                    │
│ API Gateway              │ $0.010                    │
│ Kinesis                  │ $0.001                    │
│ Redis (shared)           │ $0.001                    │
│ WebSocket                │ $0.003                    │
│ CloudWatch               │ $0.025                    │
├──────────────────────────┼──────────────────────────┤
│ TOTAL PER FREE USER      │ $0.176                    │
├──────────────────────────┼──────────────────────────┤
│ With 30% overhead buffer │ $0.23                     │
└──────────────────────────┴──────────────────────────┘
```

### Cost at Scale

| Free Users | Monthly Cost | Annual Cost | Status |
|------------|-------------|-------------|--------|
| 1,000 | $230 | $2,760 | Trivial |
| 10,000 | $2,300 | $27,600 | Acceptable |
| 50,000 | $11,500 | $138,000 | Manageable with 5% conversion |
| 100,000 | $23,000 | $276,000 | Concerning -- need conversion |
| 500,000 | $115,000 | $1,380,000 | Unsustainable without conversion |

**Break-even analysis at 5% conversion to Pro ($29/month):**
```
100,000 free users x $0.23 = $23,000/month cost
5,000 paid users (5%) x $29 = $145,000/month revenue
Margin: $145,000 - $23,000 = $122,000/month (84% gross margin)
```

Even at 100K free users, a 5% conversion rate to Pro alone covers costs with strong margin. The math works because:
1. Free users are cheap ($0.23/month each)
2. Paid users are lucrative ($29/month for ~$3-5 in AWS cost)
3. The ratio only needs to be 1:20 (5%) to be profitable

### Cost Guardrails

**Hard limits (no exceptions on free tier):**
```python
FREE_TIER_GUARDRAILS = {
    # Absolute limits -- enforced in feature gate
    'inboxes': 5,
    'emails_per_month': 1000,
    'storage_bytes': 100 * 1024 * 1024,  # 100 MB
    'api_rate_limit_per_second': 5,
    'webhook_endpoints': 3,
    'websocket_connections': 1,
    'api_keys': 1,
    'custom_domains': 1,
    'pods': 1,
    
    # Feature gates -- blocked entirely
    'semantic_search': False,
    'ai_categorization': False,
    'ai_extraction': False,
    'imap_smtp': False,
    
    # Behavioral limits
    'overage_policy': 'hard_block',  # No grace, no overage
    'retention_days': 30,             # Auto-delete after 30 days
}
```

**30-day message retention (free tier only):**

A scheduled Lambda runs daily to delete messages older than 30 days for free-tier orgs:

```python
# Lambda: free-tier-message-cleanup
# EventBridge: runs daily at 03:00 UTC

def handler(event, context):
    # Query all free-tier orgs
    free_orgs = query_free_tier_orgs()
    
    for org_id in free_orgs:
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        
        # Query messages older than cutoff
        old_messages = query_messages_before(org_id, cutoff)
        
        for msg in old_messages:
            # Delete from DynamoDB
            delete_message(org_id, msg['inbox_id'], msg['message_id'])
            
            # Delete from S3 (body + attachments)
            delete_s3_objects(org_id, msg['inbox_id'], msg['message_id'])
        
        # Update storage counter
        recalculate_storage(org_id)
        
        # Log cleanup stats
        log_cleanup(org_id, len(old_messages))
```

**Abuse detection:**

```python
# Lambda: free-tier-abuse-detector
# EventBridge: runs every 6 hours

ABUSE_RULES = [
    {
        'name': 'inbox_squatting',
        'description': 'Created inboxes but never sent or received email',
        'condition': lambda org: (
            org['usage']['inboxes_created'] >= 4 and
            org['usage']['emails_sent'] == 0 and
            org['usage']['emails_received'] == 0 and
            days_since_creation(org) > 7
        ),
        'action': 'flag_for_review'
    },
    {
        'name': 'high_bounce_rate',
        'description': 'Bounce rate exceeds 90%',
        'condition': lambda org: (
            org['usage']['emails_sent'] > 50 and
            org['usage']['bounces'] / org['usage']['emails_sent'] > 0.9
        ),
        'action': 'suspend_sending'
    },
    {
        'name': 'single_domain_spam',
        'description': 'Sending >80% of email to same recipient domain',
        'condition': lambda org: (
            org['usage']['emails_sent'] > 100 and
            top_recipient_domain_pct(org) > 0.8
        ),
        'action': 'flag_for_review'
    },
    {
        'name': 'api_key_sharing',
        'description': 'API requests from >20 distinct IPs in 1 hour',
        'condition': lambda org: (
            distinct_ips_last_hour(org) > 20
        ),
        'action': 'flag_for_review'
    },
    {
        'name': 'rapid_inbox_churn',
        'description': 'Creating and deleting inboxes rapidly (cycling through limit)',
        'condition': lambda org: (
            org['usage']['inboxes_created_lifetime'] > 20 and
            org['usage']['inboxes_deleted_lifetime'] > 15
        ),
        'action': 'rate_limit_inbox_creation'
    }
]

def handler(event, context):
    free_orgs = query_free_tier_orgs()
    
    for org_id in free_orgs:
        org = get_org_with_usage(org_id)
        
        for rule in ABUSE_RULES:
            if rule['condition'](org):
                handle_abuse(org_id, rule['name'], rule['action'])

def handle_abuse(org_id, rule_name, action):
    if action == 'flag_for_review':
        # Create internal ticket, do not act on the account yet
        create_abuse_ticket(org_id, rule_name)
    
    elif action == 'suspend_sending':
        # Immediately suspend outbound sending
        update_org(org_id, sending_suspended=True, suspension_reason=rule_name)
        send_email(
            to=get_org_owner_email(org_id),
            template='sending-suspended',
            data={'reason': rule_name, 'appeal_url': 'https://agentmail.to/support'}
        )
    
    elif action == 'rate_limit_inbox_creation':
        # Reduce inbox creation rate to 1 per hour
        update_org(org_id, inbox_creation_rate_limit=1)
```

**Aggregate cost monitoring:**

```python
# CloudWatch alarm: free-tier-aggregate-cost
{
    "AlarmName": "free-tier-aggregate-cost-warning",
    "MetricName": "FreeTierEstimatedMonthlyCost",
    "Namespace": "AgentMail/Billing",
    "Statistic": "Maximum",
    "Period": 86400,           # Daily check
    "EvaluationPeriods": 1,
    "Threshold": 25000,        # $25,000/month
    "ComparisonOperator": "GreaterThanThreshold",
    "AlarmActions": ["arn:aws:sns:us-east-1:ACCOUNT:ops-critical"],
    "TreatMissingData": "notBreaching"
}
```

**What the alarm means:** If we are spending $25,000/month on free-tier users, that implies approximately 109,000 free users. At that point:
- If conversion rate is 5%: 5,450 paid users generating $158,000/month revenue. We are fine.
- If conversion rate is 2%: 2,180 paid users generating $63,000/month revenue. Margin is thin.
- If conversion rate is <1%: Something is wrong. Either the product does not convert, or we are attracting the wrong audience. This triggers a product and marketing review, not an engineering response.

---

## 8. Self-Service Domain Onboarding

### Overview

Self-service domain onboarding is one of the most critical user-facing flows. It must be simple enough that a developer can add a domain, configure DNS, and start receiving email within 30 minutes -- including DNS propagation time.

### Domain Lifecycle State Machine

```
                    ┌──────────┐
                    │  Created  │
                    └─────┬────┘
                          │ POST /v1/domains
                          │ (SES CreateEmailIdentity)
                          ▼
                    ┌──────────────┐
                    │  Pending     │
                    │  Verification│──────── DNS records shown in console
                    └─────┬───────┘
                          │
              ┌───────────┼───────────┐
              │           │           │
              ▼           ▼           ▼
        ┌─────────┐ ┌─────────┐ ┌─────────┐
        │  DKIM   │ │  SPF    │ │  MX     │
        │ Pending │ │ Pending │ │ Pending │
        └────┬────┘ └────┬────┘ └────┬────┘
             │           │           │
             ▼           ▼           ▼
        ┌─────────┐ ┌─────────┐ ┌─────────┐
        │  DKIM   │ │  SPF    │ │  MX     │
        │ Verified│ │ Verified│ │ Verified│
        └────┬────┘ └────┬────┘ └────┬────┘
             │           │           │
             └───────────┼───────────┘
                         │ All verified
                         ▼
                   ┌──────────┐
                   │ Verified │──── Inboxes can be created on this domain
                   └──────────┘
                         │
                         │ (DNS removed / domain deleted)
                         ▼
                   ┌──────────┐
                   │ Inactive │
                   └──────────┘
```

### API: Add Domain

```
POST /v1/domains
```

**Request body:**
```json
{
  "domain": "company.com",
  "mode": "subdomain",
  "subdomain_prefix": "agents",
  "existing_provider": "google_workspace",
  "receive_email": true,
  "send_email": true
}
```

**Mode options:**
- `standalone` -- Standard setup. MX records point to SES. No existing provider.
- `subdomain` -- Uses a subdomain (e.g., `agents.company.com`). Coexists with existing provider on the apex domain.
- `transport_rule` -- Coexists via transport/mail flow rules in Google Workspace or Microsoft 365.
- `outbound_only` -- Only configure sending. No MX records needed.

**Response (201 Created):**
```json
{
  "domain_id": "dom_abc123",
  "domain": "agents.company.com",
  "mode": "subdomain",
  "status": "pending_verification",
  "dns_records": [
    {
      "type": "MX",
      "name": "agents.company.com",
      "value": "10 inbound-smtp.us-east-1.amazonaws.com",
      "purpose": "Receive email via AgentMail",
      "status": "pending",
      "required": true
    },
    {
      "type": "TXT",
      "name": "agents.company.com",
      "value": "v=spf1 include:amazonses.com ~all",
      "purpose": "SPF authentication for sending",
      "status": "pending",
      "required": true
    },
    {
      "type": "CNAME",
      "name": "selector1._domainkey.agents.company.com",
      "value": "selector1._domainkey.agents.company.com.dkim.amazonses.com",
      "purpose": "DKIM signature (key 1 of 3)",
      "status": "pending",
      "required": true
    },
    {
      "type": "CNAME",
      "name": "selector2._domainkey.agents.company.com",
      "value": "selector2._domainkey.agents.company.com.dkim.amazonses.com",
      "purpose": "DKIM signature (key 2 of 3)",
      "status": "pending",
      "required": true
    },
    {
      "type": "CNAME",
      "name": "selector3._domainkey.agents.company.com",
      "value": "selector3._domainkey.agents.company.com.dkim.amazonses.com",
      "purpose": "DKIM signature (key 3 of 3)",
      "status": "pending",
      "required": true
    },
    {
      "type": "TXT",
      "name": "_dmarc.agents.company.com",
      "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc@agentmail.to",
      "purpose": "DMARC policy",
      "status": "pending",
      "required": false
    }
  ],
  "created_at": "2026-04-10T12:00:00Z",
  "verified_at": null
}
```

### API: Check Domain Verification

```
POST /v1/domains/{domain_id}/verify
```

This triggers an on-demand DNS check (instead of waiting for the background poller).

**Response (200 OK, partially verified):**
```json
{
  "domain_id": "dom_abc123",
  "domain": "agents.company.com",
  "status": "pending_verification",
  "dns_records": [
    {
      "type": "MX",
      "name": "agents.company.com",
      "value": "10 inbound-smtp.us-east-1.amazonaws.com",
      "status": "verified",
      "verified_at": "2026-04-10T12:15:00Z"
    },
    {
      "type": "TXT",
      "name": "agents.company.com",
      "value": "v=spf1 include:amazonses.com ~all",
      "status": "verified",
      "verified_at": "2026-04-10T12:15:00Z"
    },
    {
      "type": "CNAME",
      "name": "selector1._domainkey.agents.company.com",
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "selector2._domainkey.agents.company.com",
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "selector3._domainkey.agents.company.com",
      "status": "pending"
    },
    {
      "type": "TXT",
      "name": "_dmarc.agents.company.com",
      "status": "pending"
    }
  ]
}
```

### Backend: Domain Verification Lambda

```python
# Lambda: domain-verification-poller
# EventBridge: runs every 5 minutes

import boto3
import dns.resolver

ses = boto3.client('sesv2')
dynamodb = boto3.resource('dynamodb')

def handler(event, context):
    # Query all domains with status = pending_verification
    pending_domains = query_pending_domains()
    
    for domain_record in pending_domains:
        domain = domain_record['domain']
        domain_id = domain_record['domain_id']
        org_id = domain_record['org_id']
        
        # Check SES identity verification status
        try:
            ses_response = ses.get_email_identity(EmailIdentity=domain)
        except ses.exceptions.NotFoundException:
            continue
        
        dkim_status = ses_response.get('DkimAttributes', {}).get('Status', 'NOT_STARTED')
        
        # DNS checks
        dns_results = check_dns_records(domain, domain_record['dns_records'])
        
        # Update individual record statuses
        all_required_verified = True
        for record in domain_record['dns_records']:
            record_key = f"{record['type']}:{record['name']}"
            if record_key in dns_results and dns_results[record_key]:
                record['status'] = 'verified'
                record['verified_at'] = now_iso8601()
            else:
                if record.get('required', True):
                    all_required_verified = False
        
        # Also check SES's own DKIM verification
        if dkim_status == 'SUCCESS':
            # Mark all DKIM records as verified (SES confirmed them)
            for record in domain_record['dns_records']:
                if record['type'] == 'CNAME' and '_domainkey' in record['name']:
                    record['status'] = 'verified'
                    record['verified_at'] = now_iso8601()
        elif dkim_status in ('PENDING', 'NOT_STARTED'):
            all_required_verified = False
        
        # Update DynamoDB
        if all_required_verified:
            update_domain_status(org_id, domain_id, 'verified', domain_record['dns_records'])
            
            # Fire webhook: domain.verified
            fire_webhook(org_id, 'domain.verified', {
                'domain_id': domain_id,
                'domain': domain,
                'verified_at': now_iso8601()
            })
            
            # Send email notification
            send_email(
                to=get_org_owner_email(org_id),
                template='domain-verified',
                data={'domain': domain}
            )
        else:
            # Update individual record statuses
            update_domain_records(org_id, domain_id, domain_record['dns_records'])
        
        # Check for stale domains (pending > 7 days)
        if days_since_creation(domain_record) > 7 and not all_required_verified:
            send_email(
                to=get_org_owner_email(org_id),
                template='domain-verification-reminder',
                data={
                    'domain': domain,
                    'days_pending': days_since_creation(domain_record),
                    'missing_records': [r for r in domain_record['dns_records'] if r['status'] != 'verified']
                }
            )


def check_dns_records(domain, expected_records):
    """Check DNS for each expected record."""
    results = {}
    
    for record in expected_records:
        record_key = f"{record['type']}:{record['name']}"
        try:
            if record['type'] == 'MX':
                answers = dns.resolver.resolve(record['name'], 'MX')
                found = any(
                    record['value'].split(' ', 1)[1].rstrip('.') in str(rdata.exchange).rstrip('.')
                    for rdata in answers
                )
                results[record_key] = found
            
            elif record['type'] == 'TXT':
                answers = dns.resolver.resolve(record['name'], 'TXT')
                found = any(
                    record['value'] in str(rdata).strip('"')
                    for rdata in answers
                )
                results[record_key] = found
            
            elif record['type'] == 'CNAME':
                answers = dns.resolver.resolve(record['name'], 'CNAME')
                found = any(
                    record['value'].rstrip('.') in str(rdata.target).rstrip('.')
                    for rdata in answers
                )
                results[record_key] = found
        
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            results[record_key] = False
        except Exception as e:
            results[record_key] = False
    
    return results
```

### Console UX: Domain Onboarding Wizard

```
Step 1: Enter domain
┌──────────────────────────────────────────────────────────────┐
│                     Add Custom Domain                        │
│                                                               │
│  Domain name: [company.com_____________________]             │
│                                                               │
│  Do you currently use another email provider for this domain?│
│  ○ No -- this domain is new or not used for email            │
│  ○ Yes -- Google Workspace                                    │
│  ○ Yes -- Microsoft 365                                       │
│  ○ Yes -- Other provider                                      │
│                                                               │
│  [Continue →]                                                 │
└──────────────────────────────────────────────────────────────┘

Step 2: Choose coexistence strategy (if existing provider selected)
┌──────────────────────────────────────────────────────────────┐
│              Domain Setup: company.com                        │
│                                                               │
│  Since you use Google Workspace, we recommend using a         │
│  subdomain for AgentMail to avoid disrupting your existing   │
│  email.                                                       │
│                                                               │
│  ● Use a subdomain (Recommended)                              │
│    e.g., agents.company.com                                   │
│    Your existing email at company.com is not affected.        │
│    Subdomain prefix: [agents______]                           │
│                                                               │
│  ○ Use transport rules                                        │
│    Route specific addresses from company.com to AgentMail.    │
│    Requires Google Workspace admin access.                    │
│    [View detailed setup guide →]                              │
│                                                               │
│  ○ Outbound only                                              │
│    Send email from company.com addresses, but receive         │
│    through @agentmail.to addresses.                           │
│                                                               │
│  [Continue →]                                                 │
└──────────────────────────────────────────────────────────────┘

Step 3: DNS records
┌──────────────────────────────────────────────────────────────┐
│         DNS Configuration: agents.company.com                │
│                                                               │
│  Add these DNS records to your domain registrar:             │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ ⬜ MX Record                                           │  │
│  │ Name:  agents.company.com                              │  │
│  │ Value: 10 inbound-smtp.us-east-1.amazonaws.com    [📋] │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ ⬜ TXT Record (SPF)                                    │  │
│  │ Name:  agents.company.com                              │  │
│  │ Value: v=spf1 include:amazonses.com ~all          [📋] │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ ⬜ CNAME Record (DKIM 1/3)                             │  │
│  │ Name:  selector1._domainkey.agents.company.com        │  │
│  │ Value: selector1._domainkey.agents.company.com.       │  │
│  │        dkim.amazonses.com                         [📋] │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  (... DKIM 2/3, DKIM 3/3, DMARC similarly ...)              │
│                                                               │
│  Need help? [Guide: Cloudflare] [Guide: Route 53]           │
│  [Guide: GoDaddy] [Guide: Namecheap]                        │
│                                                               │
│  [Check DNS ↻]                  [I'll do this later]         │
└──────────────────────────────────────────────────────────────┘

Step 4: Verification progress
┌──────────────────────────────────────────────────────────────┐
│         Verifying: agents.company.com                        │
│                                                               │
│  ✅ MX Record                          Verified              │
│  ✅ SPF Record                         Verified              │
│  ⏳ DKIM Record 1/3                    Waiting...            │
│  ⏳ DKIM Record 2/3                    Waiting...            │
│  ⏳ DKIM Record 3/3                    Waiting...            │
│  ⬜ DMARC Record                       Optional              │
│                                                               │
│  DNS changes can take 15-60 minutes to propagate.            │
│  We'll check automatically every 5 minutes.                  │
│  You can also close this page -- we'll email you when        │
│  verification is complete.                                    │
│                                                               │
│  [Check DNS ↻]                                               │
└──────────────────────────────────────────────────────────────┘

Step 5: Verified
┌──────────────────────────────────────────────────────────────┐
│         agents.company.com Verified! ✓                       │
│                                                               │
│  Your domain is ready. You can now create inboxes like:      │
│                                                               │
│    support-bot@agents.company.com                            │
│    sales-agent@agents.company.com                            │
│    *@agents.company.com (catch-all)                          │
│                                                               │
│  [Create your first inbox on this domain →]                  │
└──────────────────────────────────────────────────────────────┘
```

### Free Tier Domain Limit Enforcement

```python
# In the POST /v1/domains handler:

def create_domain(org_id, body):
    org = get_org(org_id)
    tier = org['tier']
    
    # Count existing domains
    existing_domains = count_domains(org_id)
    domain_limit = TIER_LIMITS[tier]['custom_domains']
    
    if existing_domains >= domain_limit:
        return {
            'statusCode': 403,
            'body': json.dumps({
                'error': {
                    'code': 'domain_limit_reached',
                    'message': f'Your {tier} tier allows {domain_limit} custom domain(s). '
                               f'You currently have {existing_domains}.',
                    'current_count': existing_domains,
                    'limit': domain_limit,
                    'upgrade_url': 'https://console.agentmail.to/settings/billing'
                }
            })
        }
    
    # Proceed with domain creation...
```

For detailed domain onboarding flows per provider (Google Workspace, Microsoft 365, etc.), see [domain-onboarding-flows.md](./domain-onboarding-flows.md).

---

## 9. AWS Marketplace Migration Path

### Why Migrate

Customers migrate from direct SaaS (Stripe) to AWS Marketplace when:
- Their company requires procurement through AWS (consolidated billing, EDP credits)
- They need enterprise features (SSO/SAML, audit logs, compliance certifications)
- They want custom pricing with committed spend discounts
- Their usage exceeds Scale tier limits and they want a negotiated contract
- Their IT team mandates vendor procurement through AWS

### Migration Architecture

```
Before Migration:
┌─────────────────────────────────────────────┐
│ Organization: org_abc123                     │
│ Billing: Stripe (sub_xyz789)                │
│ Tier: scale                                  │
│ Stripe Customer: cus_def456                 │
│ Marketplace Customer: null                   │
│                                              │
│ Pods: [pod_1, pod_2, pod_3, ...]            │
│ Inboxes: [inbox_1, inbox_2, ..., inbox_487] │
│ Domains: [company.com, agents.company.com]  │
│ API Keys: [ak_live_1, ak_live_2, ...]      │
└─────────────────────────────────────────────┘

After Migration:
┌─────────────────────────────────────────────┐
│ Organization: org_abc123  (SAME org_id)     │
│ Billing: Marketplace (mkt_customer_xyz)     │
│ Tier: enterprise                             │
│ Stripe Customer: cus_def456 (cancelled)     │
│ Marketplace Customer: mkt_customer_xyz      │
│                                              │
│ Pods: [pod_1, pod_2, pod_3, ...]  (SAME)   │
│ Inboxes: [inbox_1, inbox_2, ..., inbox_487] │
│ Domains: [company.com, agents.company.com]  │
│ API Keys: [ak_live_1, ak_live_2, ...]      │
│                                              │
│ NEW: SSO/SAML, audit logs, custom limits    │
└─────────────────────────────────────────────┘
```

**Critical requirement:** Zero-downtime migration. Not a single API call fails during the transition. Not a single email is lost. Not a single webhook is missed. The customer's agents and integrations continue operating without interruption.

### Migration Wizard Flow

```
Step 1: Initiation
┌──────────────────────────────────────────────────────────────┐
│          Upgrade to Enterprise (AWS Marketplace)             │
│                                                               │
│  Benefits of AWS Marketplace:                                │
│  • Pay through your existing AWS account                     │
│  • Apply EDP committed spend credits                         │
│  • Custom pricing with volume discounts                      │
│  • Enterprise features: SSO, audit logs, compliance          │
│  • Dedicated support with named engineer                     │
│  • Custom SLA up to 99.99%                                   │
│                                                               │
│  Your current usage:                                         │
│  • 487 inboxes (Scale limit: 500)                            │
│  • 189,000 emails/month (Scale limit: 200,000)              │
│  • 2 domains                                                 │
│                                                               │
│  [Start Migration →]                                         │
└──────────────────────────────────────────────────────────────┘

Step 2: AWS Account Details
┌──────────────────────────────────────────────────────────────┐
│           AWS Marketplace Migration                          │
│                                                               │
│  AWS Account ID: [123456789012__________]                    │
│                                                               │
│  Company name: [Acme Corp___________________]                │
│  Contact email: [procurement@acme.com_______]                │
│                                                               │
│  [Submit →]                                                   │
│                                                               │
│  Our team will create a private offer within 1 business day. │
│  You'll receive an email with the offer link.                │
└──────────────────────────────────────────────────────────────┘

Step 3: (Async) Private Offer Created
  - AgentMail sales team creates Marketplace private offer
  - Customer receives email with offer link
  - Customer accepts offer in AWS Marketplace console

Step 4: (Automatic) Post-Accept Processing
  - Marketplace sends SNS notification (subscribe-success)
  - Lambda: marketplace-onboarding receives the event
  - Lambda detects existing org via email match or org_id in offer metadata
  - Lambda executes migration:
```

### Migration Lambda

```python
# Lambda: marketplace-migration
# Triggered by: SNS notification from Marketplace OR manual API call

def migrate_org_to_marketplace(org_id, marketplace_customer_id, contract_details):
    """
    Migrate an existing org from Stripe billing to Marketplace billing.
    This is the most sensitive operation in the billing system.
    """
    org = get_org(org_id)
    
    # Validate preconditions
    assert org['billing_channel'] == 'stripe', "Org must be on Stripe billing"
    assert marketplace_customer_id, "Marketplace customer ID required"
    
    # Step 1: Update org record FIRST (make Marketplace the billing channel)
    # This is the atomic switch -- after this, the org is on Marketplace billing
    update_org(org_id,
        billing_channel='marketplace',
        marketplace_customer_id=marketplace_customer_id,
        tier='enterprise',
        limits=contract_details.get('limits', ENTERPRISE_DEFAULT_LIMITS),
        features=ENTERPRISE_FEATURES,
        retention_days=contract_details.get('retention_days', -1),
        migrated_from_stripe_at=now_iso8601(),
        stripe_subscription_id_archived=org['stripe_subscription_id']
    )
    
    # Step 2: Invalidate all caches
    invalidate_org_cache(org_id)
    
    # Step 3: Cancel Stripe subscription (at period end to avoid proration issues)
    if org.get('stripe_subscription_id'):
        stripe.Subscription.modify(
            org['stripe_subscription_id'],
            cancel_at_period_end=True,
            metadata={
                'agentmail_migrated_to': 'marketplace',
                'agentmail_migration_date': now_iso8601()
            }
        )
    
    # Step 4: Start Marketplace metering for this org
    # From this point forward, usage is reported via BatchMeterUsage
    enable_marketplace_metering(org_id, marketplace_customer_id)
    
    # Step 5: Unlock enterprise features
    update_cognito_user_tier(org_id, 'enterprise')
    
    # Step 6: Send migration confirmation
    send_email(
        to=get_org_owner_email(org_id),
        template='marketplace-migration-complete',
        data={
            'org_name': org['name'],
            'marketplace_customer_id': marketplace_customer_id,
            'new_features': ['SSO/SAML', 'Audit Logs', 'Custom SLA', 'Priority Support'],
            'stripe_final_invoice_date': get_stripe_period_end(org['stripe_subscription_id'])
        }
    )
    
    # Step 7: Emit analytics event
    emit_event('org.migrated_to_marketplace', {
        'org_id': org_id,
        'previous_tier': org['tier'],
        'previous_billing': 'stripe',
        'marketplace_customer_id': marketplace_customer_id
    })
    
    return {
        'status': 'success',
        'org_id': org_id,
        'new_billing_channel': 'marketplace',
        'new_tier': 'enterprise'
    }
```

### Proactive Migration Triggers

```python
# Lambda: marketplace-migration-detector
# EventBridge: runs daily at 09:00 UTC

def handler(event, context):
    """Identify orgs that should be contacted about Marketplace migration."""
    
    scale_orgs = query_orgs_by_tier('scale')
    
    for org in scale_orgs:
        usage = get_org_usage(org['org_id'])
        limits = TIER_LIMITS['scale']
        
        signals = []
        
        # Signal 1: Approaching inbox limit
        if usage.get('inboxes', 0) >= limits['inboxes'] * 0.8:
            signals.append(f"inboxes at {usage['inboxes']}/{limits['inboxes']}")
        
        # Signal 2: Approaching email limit
        if usage.get('emails_per_month', 0) >= limits['emails_per_month'] * 0.8:
            signals.append(f"emails at {usage['emails_per_month']}/{limits['emails_per_month']}")
        
        # Signal 3: High AI usage
        ai_usage = (
            usage.get('semantic_searches_per_month', 0) +
            usage.get('ai_categorizations_per_month', 0) +
            usage.get('ai_extractions_per_month', 0)
        )
        ai_limit = (
            limits['semantic_searches_per_month'] +
            limits['ai_categorizations_per_month'] +
            limits['ai_extractions_per_month']
        )
        if ai_usage >= ai_limit * 0.7:
            signals.append(f"AI usage at {int(ai_usage/ai_limit*100)}%")
        
        # Signal 4: Long-term Scale customer (> 3 months)
        if months_on_scale(org) >= 3:
            signals.append(f"on Scale tier for {months_on_scale(org)} months")
        
        if len(signals) >= 2:
            # Create sales lead
            create_sales_lead(
                org_id=org['org_id'],
                contact_email=org['owner_email'],
                org_name=org['name'],
                signals=signals,
                recommended_action='marketplace_migration_outreach'
            )
```

---

## 10. Platform Operations

### Unified Infrastructure Model

The single most important architectural decision for the SaaS platform: **direct SaaS customers and Marketplace customers run on the same infrastructure.** There is no separate deployment, no separate DynamoDB table, no separate Lambda functions, no separate SES configuration.

```
┌─────────────────────────────────────────────────────────────────┐
│                     AgentMail Infrastructure                     │
│                        (us-east-1)                               │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                      API Gateway                             │ │
│  │  Routes: /v1/* (REST), /ws (WebSocket), /mcp (MCP)         │ │
│  │  Auth: Cognito (console) + API Key (programmatic)          │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
│                              │                                    │
│  ┌──────────────────────────▼──────────────────────────────────┐ │
│  │                    Lambda Functions                           │ │
│  │  Feature gate checks tier regardless of billing_channel     │ │
│  │  Same code path for free, pro, business, scale, enterprise  │ │
│  └──────────────────────────┬──────────────────────────────────┘ │
│                              │                                    │
│  ┌──────────────────────────▼──────────────────────────────────┐ │
│  │                    DynamoDB (agentmail-main)                  │ │
│  │                                                               │ │
│  │  ORG#org_free_001  │ tier: free    │ billing: none           │ │
│  │  ORG#org_pro_042   │ tier: pro     │ billing: stripe         │ │
│  │  ORG#org_biz_017   │ tier: business│ billing: stripe         │ │
│  │  ORG#org_scale_003 │ tier: scale   │ billing: stripe         │ │
│  │  ORG#org_ent_001   │ tier: enterprise│ billing: marketplace  │ │
│  │                                                               │ │
│  │  All share the same table. Isolation via PK prefix.          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌──────────────────────┐  ┌──────────────────────┐             │
│  │ SES (shared account) │  │ Redis (shared cluster)│             │
│  │ All orgs share SES   │  │ Rate limits, caching  │             │
│  │ IP pools per tier    │  │ Key prefix: {org_id}: │             │
│  └──────────────────────┘  └──────────────────────┘             │
│                                                                   │
│  ┌──────────────────────┐  ┌──────────────────────┐             │
│  │ S3 (email storage)   │  │ Kinesis (events)     │             │
│  │ Prefix: {org_id}/    │  │ Partition: {org_id}  │             │
│  └──────────────────────┘  └──────────────────────┘             │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### Why Shared Infrastructure

**Cost efficiency:** Shared infrastructure means fixed costs (Redis cluster, Kinesis shards, NAT gateway, VPC endpoints) are amortized across all customers. A Redis cluster that costs $300/month serves 100,000 free users and 500 enterprise users simultaneously. If free users had a separate Redis cluster, we would pay $300/month for free users generating zero revenue.

**Simplicity:** One deployment pipeline. One set of CloudWatch dashboards. One set of Lambda functions. One DynamoDB table. One SES account (with per-org configuration sets for reputation isolation). Changes ship once, not twice.

**Tenant isolation is already enforced at the data layer:** The multi-tenancy architecture (Section 09) already ensures complete data isolation via DynamoDB partition key prefixes, S3 object key prefixes, IAM conditions, and Redis key prefixes. The isolation mechanism does not care whether the org is free or enterprise -- it enforces the same boundary regardless.

### The Only Differences Between Billing Channels

| Aspect | `billing_channel: "none"` | `billing_channel: "stripe"` | `billing_channel: "marketplace"` |
|--------|---------------------------|-----------------------------|---------------------------------|
| Tier | `free` | `pro` / `business` / `scale` | `enterprise` (or custom) |
| Payment | No payment method | Stripe credit card | AWS consolidated billing |
| Usage reporting | Internal only | Stripe Metered Billing (overage) | BatchMeterUsage (hourly to Marketplace) |
| Overage policy | Hard block | 10% grace then block | Consumption-based (no hard block) |
| Feature flags | Free tier set | Tier-appropriate set | Custom per contract |
| Support channel | Email (48h) | Email/chat (tier-dependent) | Priority + named engineer |
| SES IP pool | `shared-free` | `shared-paid` | `dedicated-{org_id}` (optional) |

**Note on SES IP pools:** Free-tier users send from a shared IP pool with strict rate limits. Paid users send from a separate shared pool with better reputation (because paid users are less likely to spam). Enterprise users can optionally get dedicated IPs for maximum reputation control.

### DynamoDB Org Record Schema (Complete)

This is the complete schema for an organization record, showing all fields relevant to the SaaS platform:

```json
{
  "PK": "ORG#org_abc123",
  "SK": "METADATA",
  "org_id": "org_abc123",
  "name": "Acme Corp",
  "created_at": "2026-01-15T10:00:00Z",
  "updated_at": "2026-04-10T12:00:00Z",
  
  "owner_email": "developer@acme.com",
  "owner_cognito_sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  
  "tier": "business",
  "billing_channel": "stripe",
  
  "stripe_customer_id": "cus_Oabcdefgh12345",
  "stripe_subscription_id": "sub_1Nabcdefgh12345",
  "stripe_subscription_status": "active",
  "stripe_current_period_end": "2026-05-15T10:00:00Z",
  
  "marketplace_customer_id": null,
  "marketplace_product_code": null,
  
  "limits": {
    "inboxes": 100,
    "emails_per_month": 50000,
    "custom_domains": 10,
    "api_rate_limit_per_second": 200,
    "webhook_endpoints": 25,
    "websocket_connections": 25,
    "storage_bytes": 10737418240,
    "api_keys": 25,
    "pods": 10,
    "semantic_searches_per_month": 5000,
    "ai_categorizations_per_month": 20000,
    "ai_extractions_per_month": 5000
  },
  
  "features": {
    "rest_api": true,
    "mcp_server": true,
    "websocket": true,
    "otp_extraction": true,
    "long_poll": true,
    "webhooks": true,
    "semantic_search": true,
    "ai_categorization": true,
    "ai_extraction": true,
    "imap_smtp": true,
    "custom_domains": true,
    "audit_logs": false,
    "sso_saml": false,
    "dedicated_ips": false
  },
  
  "retention_days": 365,
  "overage_policy": "grace_then_block",
  "overage_grace_percent": 10,
  "support_channel": "email_and_chat",
  "support_sla_hours": 4,
  
  "ses_configuration_set": "agentmail-business-pool",
  "ses_ip_pool": "shared-paid",
  
  "sending_suspended": false,
  "suspension_reason": null,
  
  "flags": {
    "abuse_flagged": false,
    "marketplace_migration_eligible": false,
    "beta_features_enabled": false
  },

  "usage_current_month": "2026-04",
  
  "GSI1PK": "BILLING#stripe",
  "GSI1SK": "TIER#business#ORG#org_abc123",
  
  "GSI2PK": "EMAIL#developer@acme.com",
  "GSI2SK": "ORG#org_abc123"
}
```

### GSI Design for SaaS Operations

```
GSI1: Billing Channel Index
  PK: BILLING#{billing_channel}
  SK: TIER#{tier}#ORG#{org_id}
  
  Purpose:
  - Query all Stripe customers: PK = "BILLING#stripe"
  - Query all free users: PK = "BILLING#none"
  - Query all Marketplace customers: PK = "BILLING#marketplace"
  - Query Stripe customers by tier: PK = "BILLING#stripe", SK begins_with "TIER#pro"

GSI2: Email Lookup Index
  PK: EMAIL#{email}
  SK: ORG#{org_id}
  
  Purpose:
  - Find org by owner email (for Marketplace migration matching)
  - Prevent duplicate registrations with same email

GSI3: Stripe Customer Index
  PK: STRIPE#cus_{customer_id}
  SK: ORG#{org_id}
  
  Purpose:
  - Resolve Stripe customer to org (for webhook processing)
  - Critical for payment event handling
```

### Monthly Usage Reset

Usage counters are stored per billing month. On each billing cycle renewal, the system starts a fresh usage record:

```python
# Lambda: monthly-usage-reset
# Triggered by: Stripe invoice.paid webhook (for Stripe customers)
#               First-of-month EventBridge rule (for free customers)

def reset_monthly_usage(org_id):
    """Create a fresh usage record for the new billing month."""
    new_month = current_month()  # e.g., "2026-05"
    
    # Archive previous month's usage
    previous_usage = get_usage_record(org_id, previous_month())
    if previous_usage:
        archive_usage(org_id, previous_month(), previous_usage)
    
    # Create new month's usage record
    dynamodb.put_item(
        TableName='agentmail-main',
        Item={
            'PK': {'S': f'ORG#{org_id}'},
            'SK': {'S': f'USAGE#{new_month}'},
            'emails_sent': {'N': '0'},
            'emails_received': {'N': '0'},
            'semantic_searches': {'N': '0'},
            'ai_categorizations': {'N': '0'},
            'ai_extractions': {'N': '0'},
            'storage_bytes': {'N': str(calculate_current_storage(org_id))},
            'period_start': {'S': first_of_month(new_month)},
            'period_end': {'S': last_of_month(new_month)}
        }
    )
    
    # Update org record to reference new usage month
    update_org(org_id, usage_current_month=new_month)
    
    # Invalidate Redis cache
    invalidate_usage_cache(org_id)
```

### Monitoring and Alerting

**SaaS-specific CloudWatch dashboards:**

```json
{
  "DashboardName": "agentmail-saas-overview",
  "Widgets": [
    {
      "type": "metric",
      "properties": {
        "title": "Active Organizations by Tier",
        "metrics": [
          ["AgentMail/SaaS", "ActiveOrgs", "Tier", "free"],
          ["AgentMail/SaaS", "ActiveOrgs", "Tier", "pro"],
          ["AgentMail/SaaS", "ActiveOrgs", "Tier", "business"],
          ["AgentMail/SaaS", "ActiveOrgs", "Tier", "scale"],
          ["AgentMail/SaaS", "ActiveOrgs", "Tier", "enterprise"]
        ],
        "period": 86400,
        "stat": "Maximum"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Daily Signups",
        "metrics": [
          ["AgentMail/SaaS", "Signups", "Channel", "email"],
          ["AgentMail/SaaS", "Signups", "Channel", "google"],
          ["AgentMail/SaaS", "Signups", "Channel", "github"]
        ],
        "period": 86400,
        "stat": "Sum"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Tier Conversions",
        "metrics": [
          ["AgentMail/SaaS", "TierConversion", "From", "free", "To", "pro"],
          ["AgentMail/SaaS", "TierConversion", "From", "pro", "To", "business"],
          ["AgentMail/SaaS", "TierConversion", "From", "business", "To", "scale"],
          ["AgentMail/SaaS", "TierConversion", "From", "scale", "To", "enterprise"]
        ],
        "period": 86400,
        "stat": "Sum"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Feature Gate Blocks (429/403)",
        "metrics": [
          ["AgentMail/SaaS", "FeatureGateBlock", "Reason", "quota_exceeded"],
          ["AgentMail/SaaS", "FeatureGateBlock", "Reason", "feature_not_available"],
          ["AgentMail/SaaS", "FeatureGateBlock", "Reason", "rate_limit_exceeded"]
        ],
        "period": 3600,
        "stat": "Sum"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Stripe Revenue (MRR)",
        "metrics": [
          ["AgentMail/SaaS", "MonthlyRecurringRevenue", "Channel", "stripe"]
        ],
        "period": 86400,
        "stat": "Maximum"
      }
    },
    {
      "type": "metric",
      "properties": {
        "title": "Free Tier Aggregate Cost Estimate",
        "metrics": [
          ["AgentMail/SaaS", "FreeTierEstimatedMonthlyCost"]
        ],
        "period": 86400,
        "stat": "Maximum"
      }
    }
  ]
}
```

**Critical alarms:**

| Alarm | Threshold | Action |
|-------|-----------|--------|
| Free tier aggregate cost | > $25,000/month | SNS to ops-critical |
| Signup rate anomaly | > 500 signups/hour | SNS to ops-warning (possible bot attack) |
| Payment failure rate | > 10% of renewals | SNS to business-critical |
| Feature gate 429 rate | > 1000/hour for a single org | SNS to ops-warning (possible abuse) |
| Stripe webhook processing lag | > 5 minutes | SNS to ops-critical (billing events stuck) |
| Cognito sign-up errors | > 50/hour | SNS to ops-critical |
| Free-to-paid conversion rate | < 2% (30-day trailing) | SNS to business-warning |

### Deployment Considerations

**Single region (us-east-1):**
The SaaS platform deploys in us-east-1 alongside all existing AgentMail infrastructure. There is no multi-region deployment for the SaaS layer in the initial release. Multi-region is a Phase 4+ consideration that would involve DynamoDB Global Tables, CloudFront origin failover, and SES multi-region sending.

**CDK/CloudFormation stack structure:**
```
agentmail-saas-auth        (Cognito User Pool, identity providers)
agentmail-saas-console     (S3 bucket, CloudFront distribution)
agentmail-saas-billing     (Stripe webhook Lambda, billing Lambdas)
agentmail-saas-features    (Feature gate middleware, usage counter Lambda)
agentmail-saas-domains     (Domain verification Lambda, EventBridge rules)
agentmail-saas-cleanup     (Message retention Lambda, abuse detection Lambda)
agentmail-saas-monitoring  (CloudWatch dashboards, alarms, SNS topics)
```

Each stack is independently deployable. The feature gate middleware is packaged as a Lambda Layer shared across all API Lambda functions.

---

## Appendix A: Complete Tier Limits Reference (Machine-Readable)

```json
{
  "tiers": {
    "free": {
      "display_name": "Free",
      "price_monthly_usd": 0,
      "price_annual_usd": 0,
      "limits": {
        "inboxes": 5,
        "emails_per_month": 1000,
        "custom_domains": 1,
        "api_rate_limit_per_second": 5,
        "webhook_endpoints": 3,
        "websocket_connections": 1,
        "storage_bytes": 104857600,
        "api_keys": 1,
        "pods": 1,
        "semantic_searches_per_month": 0,
        "ai_categorizations_per_month": 0,
        "ai_extractions_per_month": 0
      },
      "features": {
        "rest_api": true,
        "mcp_server": true,
        "websocket": true,
        "otp_extraction": true,
        "long_poll": true,
        "webhooks": true,
        "semantic_search": false,
        "ai_categorization": false,
        "ai_extraction": false,
        "imap_smtp": false,
        "audit_logs": false,
        "sso_saml": false,
        "dedicated_ips": false
      },
      "retention_days": 30,
      "overage_policy": "hard_block",
      "support_channel": "email",
      "support_sla_hours": 48,
      "sla_uptime_percent": null
    },
    "pro": {
      "display_name": "Pro",
      "price_monthly_usd": 29,
      "price_annual_usd": 278.40,
      "limits": {
        "inboxes": 25,
        "emails_per_month": 10000,
        "custom_domains": 3,
        "api_rate_limit_per_second": 50,
        "webhook_endpoints": 10,
        "websocket_connections": 5,
        "storage_bytes": 1073741824,
        "api_keys": 5,
        "pods": 3,
        "semantic_searches_per_month": 500,
        "ai_categorizations_per_month": 2000,
        "ai_extractions_per_month": 500
      },
      "features": {
        "rest_api": true,
        "mcp_server": true,
        "websocket": true,
        "otp_extraction": true,
        "long_poll": true,
        "webhooks": true,
        "semantic_search": true,
        "ai_categorization": true,
        "ai_extraction": true,
        "imap_smtp": false,
        "audit_logs": false,
        "sso_saml": false,
        "dedicated_ips": false
      },
      "retention_days": 90,
      "overage_policy": "grace_then_block",
      "overage_grace_percent": 10,
      "support_channel": "email",
      "support_sla_hours": 24,
      "sla_uptime_percent": 99.5
    },
    "business": {
      "display_name": "Business",
      "price_monthly_usd": 99,
      "price_annual_usd": 950.40,
      "limits": {
        "inboxes": 100,
        "emails_per_month": 50000,
        "custom_domains": 10,
        "api_rate_limit_per_second": 200,
        "webhook_endpoints": 25,
        "websocket_connections": 25,
        "storage_bytes": 10737418240,
        "api_keys": 25,
        "pods": 10,
        "semantic_searches_per_month": 5000,
        "ai_categorizations_per_month": 20000,
        "ai_extractions_per_month": 5000
      },
      "features": {
        "rest_api": true,
        "mcp_server": true,
        "websocket": true,
        "otp_extraction": true,
        "long_poll": true,
        "webhooks": true,
        "semantic_search": true,
        "ai_categorization": true,
        "ai_extraction": true,
        "imap_smtp": true,
        "audit_logs": false,
        "sso_saml": false,
        "dedicated_ips": false
      },
      "retention_days": 365,
      "overage_policy": "grace_then_block",
      "overage_grace_percent": 10,
      "support_channel": "email_and_chat",
      "support_sla_hours": 4,
      "sla_uptime_percent": 99.9
    },
    "scale": {
      "display_name": "Scale",
      "price_monthly_usd": 299,
      "price_annual_usd": 2870.40,
      "limits": {
        "inboxes": 500,
        "emails_per_month": 200000,
        "custom_domains": -1,
        "api_rate_limit_per_second": 500,
        "webhook_endpoints": 100,
        "websocket_connections": 100,
        "storage_bytes": 107374182400,
        "api_keys": -1,
        "pods": -1,
        "semantic_searches_per_month": 50000,
        "ai_categorizations_per_month": 200000,
        "ai_extractions_per_month": 50000
      },
      "features": {
        "rest_api": true,
        "mcp_server": true,
        "websocket": true,
        "otp_extraction": true,
        "long_poll": true,
        "webhooks": true,
        "semantic_search": true,
        "ai_categorization": true,
        "ai_extraction": true,
        "imap_smtp": true,
        "audit_logs": true,
        "sso_saml": false,
        "dedicated_ips": true
      },
      "retention_days": -1,
      "overage_policy": "grace_then_block",
      "overage_grace_percent": 10,
      "support_channel": "priority",
      "support_sla_hours": 1,
      "sla_uptime_percent": 99.95
    },
    "enterprise": {
      "display_name": "Enterprise",
      "price_monthly_usd": null,
      "price_annual_usd": null,
      "limits": "custom",
      "features": {
        "rest_api": true,
        "mcp_server": true,
        "websocket": true,
        "otp_extraction": true,
        "long_poll": true,
        "webhooks": true,
        "semantic_search": true,
        "ai_categorization": true,
        "ai_extraction": true,
        "imap_smtp": true,
        "audit_logs": true,
        "sso_saml": true,
        "dedicated_ips": true
      },
      "retention_days": "custom",
      "overage_policy": "consumption",
      "support_channel": "dedicated",
      "support_sla_hours": "custom",
      "sla_uptime_percent": "custom (up to 99.99)"
    }
  },
  "overage_rates": {
    "email_per_unit_usd": 0.05,
    "semantic_search_per_unit_usd": 0.02,
    "ai_categorization_per_unit_usd": 0.01,
    "ai_extraction_per_unit_usd": 0.03
  }
}
```

---

## Appendix B: API Endpoints Added for SaaS Platform

These endpoints are added to the existing REST API (Section 03) to support the SaaS platform:

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| POST | `/v1/auth/signup` | Create account (email/password) | None |
| POST | `/v1/auth/verify` | Verify email OTP | None |
| POST | `/v1/auth/login` | Login (returns JWT) | None |
| POST | `/v1/auth/refresh` | Refresh JWT | Refresh token |
| POST | `/v1/auth/forgot-password` | Initiate password reset | None |
| POST | `/v1/auth/reset-password` | Complete password reset | Reset token |
| GET | `/v1/account` | Get current account info | JWT or API key |
| PUT | `/v1/account` | Update account settings | JWT |
| DELETE | `/v1/account` | Delete account (30-day grace) | JWT |
| GET | `/v1/account/usage` | Get current usage stats | JWT or API key |
| GET | `/v1/account/usage/history` | Get historical usage | JWT or API key |
| GET | `/v1/billing/subscription` | Get subscription details | JWT |
| POST | `/v1/billing/checkout` | Create Stripe Checkout session | JWT |
| POST | `/v1/billing/portal` | Create Stripe Portal session | JWT |
| GET | `/v1/billing/invoices` | List invoices | JWT |
| POST | `/v1/billing/change-tier` | Change subscription tier | JWT |
| POST | `/v1/billing/marketplace-migrate` | Initiate Marketplace migration | JWT |
| POST | `/v1/domains` | Add custom domain | JWT or API key |
| GET | `/v1/domains` | List domains | JWT or API key |
| GET | `/v1/domains/{id}` | Get domain details + DNS status | JWT or API key |
| POST | `/v1/domains/{id}/verify` | Trigger DNS verification check | JWT or API key |
| DELETE | `/v1/domains/{id}` | Remove domain | JWT or API key |
| POST | `/v1/api-keys` | Create API key | JWT |
| GET | `/v1/api-keys` | List API keys (masked) | JWT |
| DELETE | `/v1/api-keys/{id}` | Revoke API key | JWT |
| POST | `/webhooks/stripe` | Stripe webhook receiver | Stripe signature |

**Note:** Most existing endpoints (inboxes, messages, threads, pods, etc.) continue to work exactly as before, using API key authentication. The new endpoints use JWT authentication because they involve account-level operations that require a human user context, not just an API key.

---

## Appendix C: Environment Variables and Secrets

```
# Cognito
COGNITO_USER_POOL_ID=us-east-1_aBcDeFgHi
COGNITO_APP_CLIENT_ID=1a2b3c4d5e6f7g8h9i0j
COGNITO_DOMAIN=auth.agentmail.to

# Stripe (stored in AWS Secrets Manager)
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Stripe Price IDs
STRIPE_PRICE_PRO_MONTHLY=price_...
STRIPE_PRICE_PRO_ANNUAL=price_...
STRIPE_PRICE_BUSINESS_MONTHLY=price_...
STRIPE_PRICE_BUSINESS_ANNUAL=price_...
STRIPE_PRICE_SCALE_MONTHLY=price_...
STRIPE_PRICE_SCALE_ANNUAL=price_...
STRIPE_PRICE_OVERAGE_EMAIL=price_...
STRIPE_PRICE_OVERAGE_SEARCH=price_...
STRIPE_PRICE_OVERAGE_CATEGORIZE=price_...
STRIPE_PRICE_OVERAGE_EXTRACT=price_...

# Stripe Portal Configuration
STRIPE_PORTAL_CONFIG_ID=bpc_...

# SaaS Console
CONSOLE_CLOUDFRONT_DISTRIBUTION_ID=E1ABCDEF2GHIJK
CONSOLE_S3_BUCKET=agentmail-console

# Feature Flags (for gradual rollouts)
FEATURE_FLAG_GITHUB_OAUTH=true
FEATURE_FLAG_ANNUAL_BILLING=true
FEATURE_FLAG_MARKETPLACE_MIGRATION_WIZARD=true
```

---

## Appendix D: Decision Log

| Decision | Options Considered | Chosen | Rationale |
|----------|-------------------|--------|-----------|
| User auth | Cognito vs Auth0 vs custom | **Cognito** | Already in AWS, native integration with API Gateway, cost-effective at scale ($0.0025/MAU after 50K) |
| Billing | Stripe vs Paddle vs custom | **Stripe** | Best API for subscription + metered billing, developer-friendly, handles PCI compliance |
| Console hosting | S3+CloudFront vs Amplify Hosting vs Vercel | **S3+CloudFront** | Full control, no vendor dependency, direct CloudFront configuration for SPA routing |
| Console framework | React vs Next.js vs Vue | **React SPA** | No SSR needed (console is behind auth), smaller bundle, simpler deployment to S3 |
| Feature gating | Application-level vs API Gateway level vs middleware | **Lambda middleware** | Needs access to DynamoDB/Redis for usage checks, API Gateway usage plans too coarse for per-feature gating |
| Usage counters | DynamoDB atomic vs Redis vs CloudWatch metrics | **DynamoDB atomic + Redis cache** | DynamoDB is source of truth (durable), Redis is read cache (fast). Cannot lose usage data. |
| Free tier AI | None vs limited vs separate model | **None** | Bedrock costs cannot be amortized at zero revenue. Even small per-invocation costs multiply dangerously at 100K users. |
| Overage billing | Soft limit + overage vs hard limit | **Hard (free) + grace (paid)** | Free must be hard to contain cost. Paid gets 10% grace to avoid surprise disruptions, billed as overage. |
| Domain verification | Polling vs push vs manual | **Polling (5 min) + manual trigger** | DNS propagation is async and unpredictable. Polling catches it automatically. Manual trigger satisfies impatient users. |
| Marketplace migration | New org vs migrate existing | **Migrate existing** | Zero-downtime, zero data loss. Creating a new org would force customers to recreate everything. |
