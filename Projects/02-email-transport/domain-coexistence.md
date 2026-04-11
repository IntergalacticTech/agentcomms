# Domain Coexistence: Running Alongside Google Workspace, Microsoft 365, and Other Providers

## Overview

This document addresses the most critical enterprise adoption challenge for AgentMail: enabling customers who already use Google Workspace, Microsoft 365, or another email provider for their human employees to also use AgentMail for AI agent inboxes on the **same domain**. Without domain coexistence, any company that already has email infrastructure (which is virtually every company) would be unable to use AgentMail with their corporate domain -- a dealbreaker for enterprise adoption.

The fundamental problem is that **MX records are domain-wide and can only point to one provider at a time.** If `company.com` has its MX records pointed at Google (`aspmx.l.google.com`), then all email sent to any `@company.com` address is delivered to Google. Our SES inbound endpoint never sees it. There is no native DNS mechanism to say "deliver `agent@company.com` to SES but deliver `john@company.com` to Google."

This document presents six approaches to solving this problem, each with different tradeoffs in complexity, risk, and user experience. The right approach depends on the customer's existing infrastructure, technical sophistication, and requirements.

---

## Table of Contents

- [Approach 1: Subdomain Strategy](#approach-1-subdomain-strategy)
- [Approach 2: Inbound Gateway / Transport Rules (Google Workspace)](#approach-2-inbound-gateway--transport-rules-google-workspace)
- [Approach 3: Transport Rules (Microsoft 365)](#approach-3-transport-rules-microsoft-365)
- [Approach 4: Dual-Delivery via MX Priority](#approach-4-dual-delivery-via-mx-priority)
- [Approach 5: Custom MX Proxy / Smart Router](#approach-5-custom-mx-proxy--smart-router)
- [Approach 6: Sending-Only Mode (Outbound Only)](#approach-6-sending-only-mode-outbound-only)
- [DNS Configuration Guide](#dns-configuration-guide)
- [Recommendation Matrix](#recommendation-matrix)
- [Implementation in Our Platform](#implementation-in-our-platform)
- [Customer Onboarding Guides](#customer-onboarding-guides)

---

## Approach 1: Subdomain Strategy

**Recommended for most customers. Lowest risk, simplest setup.**

### Concept

Instead of sharing the apex domain (`company.com`) between two email providers, the customer creates a dedicated subdomain for AI agent inboxes. Common choices:

- `agents.company.com`
- `ai.company.com`
- `mail.company.com`
- `bot.company.com`
- `auto.company.com`

Agent inboxes get addresses like `support-bot@agents.company.com` or `intake@ai.company.com`. Human employees continue using `john@company.com` through Google Workspace or Microsoft 365 with zero changes to their existing configuration.

### How It Works

```
DNS for company.com (unchanged -- stays with Google/Microsoft):
  MX 1   aspmx.l.google.com           (or microsoft MX)
  MX 5   alt1.aspmx.l.google.com
  MX 10  alt2.aspmx.l.google.com
  TXT    "v=spf1 include:_spf.google.com ~all"
  CNAME  google._domainkey → (Google DKIM)

DNS for agents.company.com (new -- points to AgentMail/SES):
  MX 10  inbound-smtp.us-east-1.amazonaws.com
  TXT    "v=spf1 include:amazonses.com ~all"
  CNAME  abcdef._domainkey.agents.company.com → abcdef.dkim.amazonses.com
  CNAME  ghijkl._domainkey.agents.company.com → ghijkl.dkim.amazonses.com
  CNAME  mnopqr._domainkey.agents.company.com → mnopqr.dkim.amazonses.com
  TXT    _dmarc.agents.company.com "v=DMARC1; p=quarantine; rua=mailto:dmarc@agents.company.com"
```

### DNS Setup Step by Step

1. **Customer decides on subdomain** (e.g., `agents.company.com`). Our platform can suggest a default.
2. **Customer calls `POST /v1/domains`** with `{"domain": "agents.company.com"}`. Our API creates the SES identity for the subdomain.
3. **We return DNS records.** The customer adds them at their DNS provider (Cloudflare, Route 53, GoDaddy, etc.). Because these are subdomain records, they do not conflict with any existing apex domain records.
4. **DKIM verification proceeds** via SES polling -- identical to our standard domain verification flow.
5. **MX record verification.** We verify that `agents.company.com` MX points to SES inbound. This is independent of the apex domain MX.
6. **Domain goes active.** Agent inboxes can now send and receive on `agents.company.com`.

### SES Configuration

SES treats the subdomain as a completely separate email identity. From SES's perspective, `agents.company.com` is an independent domain -- it has its own DKIM keys, its own verification status, and its own inbound receipt rules. There is no interaction with the apex domain's email configuration.

The SES Receipt Rule Set needs a rule matching `agents.company.com`:

```python
# Receipt Rule for the subdomain
{
    "Name": "agents-company-com-catchall",
    "Enabled": True,
    "Recipients": [],  # Catch-all for the verified domain
    "Actions": [
        {
            "S3Action": {
                "BucketName": "agentmail-inbound-{region}",
                "ObjectKeyPrefix": "raw/"
            }
        },
        {
            "LambdaAction": {
                "FunctionArn": "arn:aws:lambda:{region}:{account}:function:inbound-router",
                "InvocationType": "Event"
            }
        }
    ]
}
```

Because SES matches verified domains to receipt rules automatically, adding the subdomain identity is sufficient -- SES will route inbound mail for `*@agents.company.com` through our receipt rule set as long as the MX record points to SES.

### DKIM, SPF, and DMARC for Subdomains

**DKIM:** SES generates three CNAME records for the subdomain. These are entirely independent of the parent domain's DKIM records. Google's DKIM selector (`google._domainkey.company.com`) and SES's DKIM selectors (`xxxxx._domainkey.agents.company.com`) live in different parts of the DNS tree and do not conflict.

**SPF:** The SPF record for `agents.company.com` is independent of the SPF record for `company.com`. Each domain/subdomain has its own SPF TXT record. There is no inheritance or conflict.

**DMARC:** DMARC has an inheritance model -- if `agents.company.com` does not have its own `_dmarc.agents.company.com` record, receiving servers will look up `_dmarc.company.com`. This is usually fine, but we recommend setting an explicit DMARC record on the subdomain so the customer has independent control over the agent email DMARC policy. The subdomain DMARC can have its own `rua` (aggregate report) and `ruf` (forensic report) addresses, which are useful for monitoring agent email reputation separately.

### Forwarding Between Apex and Subdomain

A common need: a human at `john@company.com` sends an email to `support-bot@agents.company.com`. This works natively -- the subdomain is just another email domain. Google/Microsoft will deliver outbound mail to any address, and our SES inbound will receive it.

The reverse also works: when an agent at `support-bot@agents.company.com` sends email to `john@company.com`, SES sends it outbound, and Google/Microsoft receives it inbound. No special configuration needed.

For customers who want external senders to reach an agent using the apex domain address (e.g., `support@company.com`), the customer can set up a forwarding rule or alias in Google Workspace / Microsoft 365 that forwards `support@company.com` to `support@agents.company.com`. This is a one-time setup in the existing email admin console.

### Pros

- **Zero risk to human email.** The apex domain MX records are never touched. Google/Microsoft configuration is unchanged.
- **Simple setup.** Only subdomain DNS records need to be added. No admin console configuration in Google or Microsoft.
- **Independent failure domains.** If AgentMail has an outage, human email is unaffected. If Google has an outage, agent email is unaffected.
- **Clear organizational separation.** Agent addresses are visually distinct from human addresses, which can be a feature for compliance and audit purposes.
- **Works with any email provider.** Not specific to Google or Microsoft -- works with Zoho, Fastmail, ProtonMail, on-premises Exchange, or any provider.

### Cons

- **Different domain suffix.** Agent addresses are `@agents.company.com` instead of `@company.com`. Some customers may find this less professional or less seamless.
- **Forwarding required for apex-domain addresses.** If the customer wants `support@company.com` to reach an agent, they need to configure forwarding in their email provider.
- **Brand perception.** Some enterprises want all email to come from `@company.com` for brand consistency.

---

## Approach 2: Inbound Gateway / Transport Rules (Google Workspace)

**Recommended for Google Workspace customers who need agent inboxes on the apex domain.**

### Concept

Google Workspace supports routing rules that can forward email for specific recipients to an external SMTP server. The MX records stay pointed at Google, but Google acts as a smart forwarder: it inspects the recipient address and, if it matches an agent inbox pattern, forwards the message to our inbound endpoint instead of delivering it to a Google mailbox.

### How It Works

```
Internet Sender
      │
      ▼
MX Record → Google Workspace (aspmx.l.google.com)
      │
      ▼
Google receives the message
      │
      ├── Recipient is john@company.com?
      │   └── Deliver to John's Gmail inbox (normal Google behavior)
      │
      └── Recipient is agent-1@company.com?
          └── Routing rule matches → Forward to our SMTP endpoint
              └── Our endpoint receives the message → SES pipeline → AgentMail
```

### Google Workspace Configuration (Step by Step)

#### Option A: Recipient-Based Routing via Google Admin Console

This is the cleanest approach for a small-to-medium number of agent addresses.

**Step 1: Create a "Group" or "Routing Address" for Each Agent Inbox**

In Google Admin Console, the customer does NOT need to create actual Google Workspace user accounts for agent addresses. Instead, they use routing rules that match on recipient address patterns.

**Step 2: Configure Inbound Gateway**

1. Log into Google Admin Console (`admin.google.com`)
2. Navigate to **Apps > Google Workspace > Gmail > Routing**
3. Under **Inbound gateway**, add the IP ranges of your SMTP endpoint (if using content compliance rules, this step may not be needed -- see Option B)

**Step 3: Add a Routing Rule**

1. In **Apps > Google Workspace > Gmail > Routing**, click **Configure** or **Add another rule** under **Routing**
2. Set the rule name: e.g., "AgentMail Forwarding"
3. Under **Email messages to affect**, select **Inbound**
4. Under **For the above types of messages, do the following**:
   - Select **Change route**
   - Add a new route pointing to your SMTP endpoint host and port:
     - **Host:** `inbound.agentmail.dev` (our custom SMTP ingress -- see SMTP Endpoint section below)
     - **Port:** `25`
     - **Require TLS:** Yes
   - Under **Also deliver to**, leave unchecked (we do NOT want dual delivery -- only our endpoint should get it)
5. Under **Show options > Envelope filter**:
   - Select **Only affect specific envelope recipients**
   - Use a pattern match: e.g., `agent-.*@company\.com` (regex matching agent addresses)
   - Or use a group-based match if agent addresses are members of a specific Google Group
6. Save the rule

**Step 4: Verify the Route Works**

Send a test email to an agent address (e.g., `agent-test@company.com`). Google should route it to our SMTP endpoint. The email should appear in our inbound pipeline.

#### Option B: Content Compliance Rules

For more granular control, Google Workspace also offers **Content compliance** rules under **Apps > Google Workspace > Gmail > Compliance**:

1. Navigate to **Apps > Google Workspace > Gmail > Compliance > Content compliance**
2. Add a new rule:
   - **Email messages to affect:** Inbound
   - **Expressions:** Add an expression that matches on the envelope recipient header
     - Use "If ANY of the following match the message"
     - Metadata match: Envelope recipient matches regex `^(agent-1|support-bot|intake)@company\.com$`
   - **If the above expressions match, do the following:**
     - Change route → your AgentMail SMTP endpoint
3. Save

This approach is more flexible because you can match on multiple conditions (headers, body content, metadata) and can be combined with other compliance rules.

#### Option C: Non-Delivery Routing via Groups

An alternative pattern:

1. Create a Google Group: `agentmail-routing@company.com`
2. Add all agent addresses as members of this group (they don't need actual Google accounts)
3. Configure routing to forward messages to the group's address to your SMTP endpoint
4. This approach centralizes management: adding a new agent inbox means adding a member to the group

### Our SMTP Inbound Endpoint

Google Workspace routing rules forward via SMTP, not via HTTP webhooks. This means we need an SMTP server that can receive forwarded messages from Google. There are two options:

**Option 1: SES Inbound with Custom Domain Routing**

If the customer's domain is verified in SES and MX records point to SES (which they won't in this approach since MX points to Google), this won't work directly. However, we can set up a separate "relay" domain or use an SMTP endpoint.

**Option 2: Custom SMTP Endpoint on ECS (Recommended)**

Deploy a lightweight SMTP server (Haraka or Postfix) on ECS Fargate behind a Network Load Balancer (NLB):

```
Google Workspace Routing Rule
      │
      ▼ (SMTP on port 25)
Network Load Balancer (NLB)
      │
      ▼
ECS Fargate Task (Haraka SMTP server)
      │
      ▼
Writes to S3 + invokes Lambda inbound-router
      │
      ├── DynamoDB (metadata)
      ├── S3 (attachments)
      └── Kinesis (events)
```

The Haraka SMTP server:

```javascript
// Haraka plugin: agentmail_ingest.js
exports.hook_queue = function (next, connection) {
    var transaction = connection.transaction;
    var recipients = transaction.rcpt_to;
    var mailFrom = transaction.mail_from;

    // Extract the raw MIME message
    var rawMessage = '';
    transaction.message_stream.pipe(process.stdout); // simplified

    // For each recipient, verify it's a known agent inbox
    recipients.forEach(function(rcpt) {
        var address = rcpt.address();
        // Look up in DynamoDB or Redis cache whether this address
        // belongs to a registered agent inbox
        // If yes: store in S3, invoke inbound-router Lambda
        // If no: reject with 550 (user unknown) or accept and discard
    });

    next(OK);
};
```

The NLB must:
- Listen on port 25 (SMTP)
- Have a public IP or Elastic IP for Google to connect to
- TLS termination via a valid certificate (Google requires STARTTLS)
- Health checks on the ECS tasks
- Multi-AZ deployment for reliability

The DNS record for the SMTP endpoint:

```
inbound.agentmail.dev  A  <NLB public IP>
inbound.agentmail.dev  MX 10  inbound.agentmail.dev  (for reverse DNS/validation)
```

**Option 3: SES as SMTP Relay Endpoint**

SES can receive email on domains where it controls the MX, but in this approach the customer's MX points to Google. However, we can use a "relay domain" trick:

1. We maintain a domain like `inbound-relay.agentmail.dev` with MX pointing to SES
2. Google Workspace routes agent emails to `{original-recipient-encoded}@inbound-relay.agentmail.dev`
3. SES receives the email on the relay domain
4. Our Lambda inbound-router decodes the original recipient from the relay address and processes normally

This avoids running our own SMTP server but requires encoding/decoding the original recipient address. The Google routing rule would rewrite the envelope recipient:

```
Envelope filter: recipient matches agent-.*@company.com
Action: Change route + Rewrite envelope recipient to:
  agent-1--company-com@inbound-relay.agentmail.dev
```

Google Workspace's routing rules support envelope recipient rewriting, making this viable.

### Latency Implications

Adding Google as a hop introduces latency:

```
Without Google hop:  Internet → SES → Lambda → DynamoDB  (~1-3 seconds)
With Google hop:     Internet → Google → SMTP forward → Our endpoint → Lambda → DynamoDB  (~3-8 seconds)
```

The additional latency comes from:
- Google receiving and processing the message (spam scanning, compliance checks): 1-3 seconds
- Google establishing SMTP connection to our endpoint and transmitting: 1-2 seconds
- Additional TLS handshake overhead: ~200ms

For most agent use cases (customer support intake, form submissions, notification processing), 3-8 seconds is acceptable. For latency-critical workflows, the subdomain approach (Approach 1) or the smart router approach (Approach 5) is preferable.

### Synchronization: Keeping Google and AgentMail in Sync

When a new agent inbox is created via our API, the Google routing rule needs to be updated to include the new address. Options:

1. **Wildcard pattern:** If all agent addresses follow a naming convention (e.g., `agent-*@company.com`), the routing rule uses a regex that automatically covers new inboxes. This is the recommended approach.
2. **Google Workspace Admin API:** Programmatically update routing rules via the Google Admin SDK. This requires the customer to grant our platform OAuth access to their Google Workspace admin, which is a significant permission grant.
3. **Manual update:** The customer manually adds new addresses to the routing rule. Not scalable.

### Limitations

- Requires Google Workspace admin access (Business Standard or above -- routing rules are not available on the free/legacy tier)
- Slight delivery delay due to the Google hop
- Google applies its own spam filtering before forwarding, which may reject or quarantine messages intended for agent inboxes
- Google Workspace has daily forwarding limits (varies by plan; typically 10,000 per day for Business Standard)
- If Google Workspace experiences an outage, agent email is also affected
- Complex to debug: message flows through two systems before reaching our pipeline
- Google may modify message headers during forwarding (e.g., adding `X-Forwarded-To`, `X-Forwarded-For`), which affects our thread computation

---

## Approach 3: Transport Rules (Microsoft 365)

**Recommended for Microsoft 365 customers who need agent inboxes on the apex domain.**

### Concept

Microsoft 365 (Exchange Online) has a powerful mail flow rules engine (formerly called "transport rules") combined with outbound connectors. The pattern is the same as Approach 2: MX records stay pointed at Microsoft, and Exchange Online routes specific recipients to our endpoint via a connector.

### How It Works

```
Internet Sender
      │
      ▼
MX Record → Microsoft 365 (company-com.mail.protection.outlook.com)
      │
      ▼
Exchange Online receives the message
      │
      ├── Recipient is john@company.com?
      │   └── Deliver to John's Exchange mailbox (normal M365 behavior)
      │
      └── Recipient is agent-1@company.com?
          └── Mail flow rule matches → Route through connector to our SMTP endpoint
              └── Our endpoint receives the message → AgentMail pipeline
```

### Microsoft 365 Configuration (Step by Step)

#### Step 1: Create a Partner Connector

1. Log into **Exchange Admin Center** (`admin.exchange.microsoft.com`)
2. Navigate to **Mail flow > Connectors**
3. Click **Add a connector**
4. Connection from: **Office 365**
5. Connection to: **Partner organization**
6. Name: "AgentMail Inbound Routing"
7. Under **Use of connector**:
   - Select **Only when email messages are redirected to this connector by a transport rule** (this is critical -- we don't want all outbound mail going through our connector)
8. Under **Routing**:
   - Select **Route email through these smart hosts**
   - Add: `inbound.agentmail.dev` (our SMTP endpoint)
   - Port: 25
9. Under **Security restrictions**:
   - Check **Always use TLS**
   - Select **Issued by a trusted certificate authority (CA)**
   - Optionally add our domain to the subject name match
10. **Validate the connector** using Microsoft's built-in test (sends a test email through the connector)
11. Save

#### Step 2: Create a Mail Flow Rule (Transport Rule)

1. In **Exchange Admin Center**, navigate to **Mail flow > Rules**
2. Click **Add a rule > Create a new rule**
3. Name: "Route agent inboxes to AgentMail"
4. Apply this rule if:
   - **The recipient address includes** (option depends on EAC version):
     - Pattern: Use "matches pattern" with regex `^agent-.*@company\.com$`
     - OR: Use "is a member of" with a distribution list containing all agent addresses
     - OR: Use individual addresses if the list is small
5. Do the following:
   - **Redirect the message to** the connector created in Step 1
6. Except if:
   - (Optional) Add exceptions for internal messages if needed
7. Set priority to **0** (highest) so this rule is evaluated first
8. Mode: **Enforce**
9. Save

#### Step 3: Prevent NDR for Unknown Recipients

By default, Exchange Online will reject email to addresses that don't have a mailbox. Since agent addresses don't have Exchange mailboxes, Exchange would bounce them before the transport rule fires. To fix this:

**Option A: Create Mail-Enabled Contacts**

For each agent address, create a mail-enabled contact in Exchange pointing to an external address. The contact ensures Exchange accepts the message, and the transport rule then redirects it.

```powershell
# PowerShell: Create mail-enabled contact for each agent
New-MailContact -Name "Agent Support Bot" -ExternalEmailAddress "support-bot@inbound-relay.agentmail.dev" -Alias "support-bot"
# Set the primary address to the company domain
Set-MailContact -Identity "support-bot" -EmailAddresses @{Add="support-bot@company.com"}
```

**Option B: Shared Mailbox with Transport Rule**

Create a single shared mailbox (no license cost) that acts as a catch-all for agent addresses. The transport rule fires before delivery to the shared mailbox, redirecting to our endpoint.

**Option C: Accepted Domain + Transport Rule**

If the customer is willing, they can configure the domain as an "Internal Relay" accepted domain type instead of "Authoritative." This tells Exchange to accept mail for any address at the domain and, if no mailbox exists, apply transport rules. However, this changes behavior for ALL unmatched addresses (they would no longer bounce), so it's only suitable if the customer is comfortable with that.

#### Step 4: Validate End to End

1. Send a test email to `agent-test@company.com`
2. Check Exchange message trace (**Mail flow > Message trace**) to confirm the transport rule fired
3. Verify the message arrived at our SMTP endpoint
4. Verify it appears in our inbound pipeline (DynamoDB, S3)

### Exchange Online PowerShell Alternative

For automated or bulk configuration, customers can use Exchange Online PowerShell:

```powershell
# Connect to Exchange Online
Connect-ExchangeOnline -UserPrincipalName admin@company.com

# Create the outbound connector
New-OutboundConnector `
    -Name "AgentMail Routing" `
    -ConnectorType "Partner" `
    -SmartHosts @("inbound.agentmail.dev") `
    -TlsSettings "CertificateValidation" `
    -IsTransportRuleScoped $true `
    -Enabled $true

# Create the transport rule
New-TransportRule `
    -Name "Route Agent Inboxes to AgentMail" `
    -RecipientAddressMatchesPatterns @("^agent-.*@company\.com$") `
    -RouteMessageOutboundConnector "AgentMail Routing" `
    -Priority 0 `
    -Mode "Enforce"

# Create mail contacts to prevent NDR (for each agent inbox)
$agents = @("support-bot", "intake", "billing-agent")
foreach ($agent in $agents) {
    New-MailContact `
        -Name "AgentMail-$agent" `
        -ExternalEmailAddress "$agent@inbound-relay.agentmail.dev"
    Set-MailContact `
        -Identity "AgentMail-$agent" `
        -EmailAddresses @{Add="$agent@company.com"}
}
```

### Our SMTP Endpoint

Identical to Approach 2 -- we use the same ECS-hosted SMTP server (Haraka/Postfix behind NLB) or the SES relay domain trick. Microsoft 365 connects to our endpoint via SMTP on port 25 with STARTTLS.

One additional requirement for Microsoft: the connector validates our TLS certificate. Our SMTP endpoint must present a valid certificate for `inbound.agentmail.dev` issued by a trusted CA (Let's Encrypt, DigiCert, etc.).

### Latency Implications

Similar to Google Workspace:

```
Without M365 hop:  Internet → SES → Lambda → DynamoDB  (~1-3 seconds)
With M365 hop:     Internet → M365 → connector → Our endpoint → Lambda → DynamoDB  (~3-10 seconds)
```

Microsoft's mail flow pipeline can introduce slightly more latency than Google's, especially if multiple transport rules are evaluated or if the message undergoes compliance scanning (DLP, encryption, etc.).

### Synchronization: Keeping M365 and AgentMail in Sync

When new agent inboxes are created:

1. **Wildcard regex in transport rule:** If agent addresses follow a pattern (`agent-*@company.com`), the regex in the transport rule automatically covers new addresses. Recommended.
2. **Microsoft Graph API:** Programmatically create mail contacts and update transport rules via the Microsoft Graph API. Requires the customer to consent to the `Exchange.ManageAsApp` or `TransportRules.ReadWrite.All` permission.
3. **Manual update:** Customer manually creates mail contacts for each new agent inbox. Not scalable.

### Limitations

- Requires Exchange Online Plan 1 or above (transport rules and connectors are not available on all plans)
- Requires Exchange admin access
- Mail contacts or another recipient object must exist for each agent address to prevent NDR
- Microsoft 365 applies anti-spam/anti-malware scanning, which may quarantine messages intended for agents
- Exchange Online has connector limits (currently 100 outbound connectors per tenant, but each connector can handle unlimited addresses)
- Transport rule evaluation adds processing time
- Microsoft occasionally changes the Exchange Admin Center UI, so step-by-step instructions may need periodic updates
- If Microsoft 365 experiences an outage, agent email is also affected

---

## Approach 4: Dual-Delivery via MX Priority

**NOT recommended. Included for completeness and to explain why this doesn't work.**

### Concept (Flawed)

The idea: set the primary MX to Google/Microsoft (priority 10) and a secondary MX to our SES inbound (priority 20). The hope is that both MX servers receive mail.

```
company.com MX records:
  MX 10  aspmx.l.google.com         (Google -- primary)
  MX 20  inbound-smtp.us-east-1.amazonaws.com  (SES -- secondary)
```

### Why This Doesn't Work

**MX priority is a failover mechanism, not a load-balancing or dual-delivery mechanism.** RFC 5321 specifies that sending MTAs (mail transfer agents) MUST attempt delivery to the lowest-priority MX first. They only try higher-priority (higher number) MX records if the primary MX is unreachable or rejects the connection.

In practice:

1. An external sender tries to deliver to `agent-1@company.com`
2. Their MTA looks up the MX records and sees priority 10 (Google) and priority 20 (SES)
3. The MTA connects to Google (priority 10) first
4. Google accepts the message for `company.com` (it's the authoritative provider for this domain)
5. Google either delivers to a mailbox or bounces with "user unknown"
6. The sending MTA **never tries the secondary MX** because Google accepted the connection

The secondary MX would only be tried if:
- Google's MX servers are completely unreachable (connection timeout, all IPs down)
- Google returns a 4xx temporary error for the SMTP session itself (not a 5xx permanent rejection)

### The "Reject Unknown" Hope

Some people suggest configuring Google to reject addresses it doesn't recognize, hoping the sending MTA will then try the secondary MX. This doesn't work because:

1. Google returns `550 5.1.1 The email account that you tried to reach does not exist` -- a **permanent** (5xx) rejection
2. Per RFC 5321, the sending MTA interprets a 5xx response as a permanent failure and **generates a bounce (NDR)** instead of trying the next MX
3. The message is never delivered to the secondary MX
4. The sender receives a confusing bounce message

Some non-RFC-compliant MTAs might try the next MX after a 550, but this behavior is:
- Not guaranteed by any standard
- Unreliable across different sending MTAs (Gmail, Outlook.com, corporate mail servers, etc.)
- Getting less common as MTAs become more RFC-compliant

### When Secondary MX Does Get Tried

The only reliable scenario where secondary MX is used is genuine failover -- the primary MX is down. This makes MX priority useful for high availability but useless for dual-delivery routing.

### Verdict

**Do not offer this approach to customers.** It will result in bounced messages and confused end users. If a customer asks about this approach, explain the RFC 5321 behavior and recommend Approach 1, 2, 3, or 5 instead.

---

## Approach 5: Custom MX Proxy / Smart Router

**Maximum flexibility but highest complexity. Recommended only for customers who need seamless apex-domain coexistence and cannot use transport rules.**

### Concept

We become the MX for the customer's entire domain. All email to `company.com` hits our infrastructure first. Our SMTP proxy inspects the recipient address and makes a routing decision:

- If the recipient is a known agent inbox in our system -> route to our processing pipeline
- If the recipient is anyone else -> forward to Google/Microsoft's mail servers for delivery

```
Internet Sender
      │
      ▼
MX Record → Our SMTP Proxy (NLB → ECS)
      │
      ▼
SMTP Proxy receives connection, inspects RCPT TO
      │
      ├── RCPT TO: agent-1@company.com (known agent inbox)
      │   └── Accept → Route to our inbound pipeline (S3 + Lambda)
      │
      └── RCPT TO: john@company.com (not an agent inbox)
          └── Accept → Forward to Google/Microsoft upstream MX
              └── aspmx.l.google.com (or company-com.mail.protection.outlook.com)
```

### Architecture

```
                                    ┌─────────────────────────────────┐
                                    │          AWS Region             │
Internet                            │                                 │
  │                                 │  ┌──────────────────────────┐  │
  │   MX record                     │  │  ECS Fargate Cluster     │  │
  │   company.com → smtp.agentmail  │  │                          │  │
  │                                 │  │  ┌─────────────────┐     │  │
  ▼                                 │  │  │ Haraka/Postfix   │     │  │
┌────────────┐                      │  │  │ SMTP Proxy       │     │  │
│ Network LB │──────────────────────┤  │  │                  │     │  │
│ (port 25)  │                      │  │  │ recipient check: │     │  │
│ Multi-AZ   │                      │  │  │ is agent inbox?  │     │  │
└────────────┘                      │  │  └───────┬──────────┘     │  │
                                    │  │          │                │  │
                                    │  └──────────┼────────────────┘  │
                                    │             │                   │
                                    │     ┌───────┴────────┐          │
                                    │     │                │          │
                                    │     ▼                ▼          │
                                    │  ┌──────┐      ┌──────────┐    │
                                    │  │ S3 + │      │ Forward  │    │
                                    │  │Lambda│      │ to       │    │
                                    │  │(ours)│      │ upstream │    │
                                    │  └──────┘      │ MX       │    │
                                    │                │(Google/MS)│    │
                                    │                └──────────┘    │
                                    └─────────────────────────────────┘
```

### Haraka Implementation

Haraka is a high-performance SMTP server written in Node.js. It's well-suited for this use case because of its plugin architecture and async processing model.

**Plugin: `rcpt_to.agentmail_router.js`**

```javascript
// Haraka plugin: rcpt_to.agentmail_router.js
//
// For each RCPT TO, check if the address is a known agent inbox.
// If yes, mark for local delivery (our pipeline).
// If no, mark for upstream forwarding (Google/Microsoft).

const { DynamoDBClient, GetItemCommand } = require("@aws-sdk/client-dynamodb");
const Redis = require("ioredis");

let dynamodb;
let redis;

exports.register = function () {
    this.loginfo("Initializing AgentMail router plugin");

    dynamodb = new DynamoDBClient({ region: process.env.AWS_REGION || "us-east-1" });
    redis = new Redis(process.env.REDIS_URL);

    // Load upstream MX configuration per domain
    // This maps customer domains to their original MX provider
    // e.g., { "company.com": { provider: "google", mx: ["aspmx.l.google.com", ...] } }
    this.upstream_config = {};
    this.load_upstream_config();
};

exports.load_upstream_config = function () {
    // In production, this loads from DynamoDB or a config file
    // and refreshes periodically (every 60 seconds)
    // Each domain entry has:
    //   - upstream_mx: array of MX hosts to forward non-agent mail to
    //   - upstream_port: port (usually 25)
    //   - require_tls: boolean
};

exports.hook_rcpt = async function (next, connection, params) {
    var rcpt = params[0];
    var address = rcpt.address().toLowerCase();
    var domain = rcpt.host.toLowerCase();

    // Step 1: Check Redis cache for known agent inbox
    var cacheKey = "inbox:" + address;
    var cached = await redis.get(cacheKey);

    if (cached === "agent") {
        // Known agent inbox -- accept for local delivery
        connection.transaction.notes.agentmail_local = true;
        connection.transaction.notes.agentmail_recipients =
            connection.transaction.notes.agentmail_recipients || [];
        connection.transaction.notes.agentmail_recipients.push(address);
        this.loginfo("Agent inbox accepted: " + address);
        return next(OK);
    }

    if (cached === "forward") {
        // Known non-agent address -- mark for forwarding
        connection.transaction.notes.agentmail_forward = true;
        connection.transaction.notes.forward_recipients =
            connection.transaction.notes.forward_recipients || [];
        connection.transaction.notes.forward_recipients.push(address);
        this.loginfo("Forward to upstream: " + address);
        return next(OK);
    }

    // Step 2: Cache miss -- look up in DynamoDB
    try {
        var result = await dynamodb.send(new GetItemCommand({
            TableName: "agentmail-inboxes",
            Key: { "PK": { S: "INBOX#" + address }, "SK": { S: "META" } }
        }));

        if (result.Item) {
            // It's an agent inbox
            await redis.set(cacheKey, "agent", "EX", 300); // cache for 5 min
            connection.transaction.notes.agentmail_local = true;
            connection.transaction.notes.agentmail_recipients =
                connection.transaction.notes.agentmail_recipients || [];
            connection.transaction.notes.agentmail_recipients.push(address);
            return next(OK);
        }
    } catch (err) {
        this.logerror("DynamoDB lookup failed: " + err.message);
        // On error, default to forwarding (fail-open for human email)
        // This is a deliberate design choice: if our system is degraded,
        // human email must still flow.
    }

    // Step 3: Not an agent inbox -- forward to upstream MX
    await redis.set(cacheKey, "forward", "EX", 300);
    connection.transaction.notes.agentmail_forward = true;
    connection.transaction.notes.forward_recipients =
        connection.transaction.notes.forward_recipients || [];
    connection.transaction.notes.forward_recipients.push(address);
    this.loginfo("Forward to upstream: " + address);
    return next(OK);
};

exports.hook_queue = async function (next, connection) {
    var notes = connection.transaction.notes;

    // Handle local delivery (agent inboxes)
    if (notes.agentmail_local && notes.agentmail_recipients) {
        // Store raw MIME in S3 and invoke Lambda inbound-router
        // (same as our standard SES inbound pipeline)
        var rawMessage = await this.get_message_stream(connection.transaction);
        await this.store_and_process(rawMessage, notes.agentmail_recipients);
    }

    // Handle upstream forwarding (human inboxes)
    if (notes.agentmail_forward && notes.forward_recipients) {
        var domain = notes.forward_recipients[0].split("@")[1];
        var upstream = this.upstream_config[domain];
        if (upstream) {
            await this.forward_to_upstream(
                connection.transaction,
                notes.forward_recipients,
                upstream.mx,
                upstream.require_tls
            );
        } else {
            this.logerror("No upstream config for domain: " + domain);
            return next(DENY, "No upstream configuration for this domain");
        }
    }

    return next(OK);
};

exports.forward_to_upstream = async function (transaction, recipients, mx_hosts, require_tls) {
    // Use nodemailer or raw SMTP client to forward the message
    // to the upstream MX servers (Google/Microsoft)
    // Preserve original headers, envelope sender, etc.
    // Retry on failure with exponential backoff
    // If all upstream MX hosts are unreachable, queue for retry (Haraka's built-in queue)
};
```

**Postfix Alternative Configuration:**

```
# /etc/postfix/main.cf (key settings for smart routing)

# Accept mail for customer domains
mydestination =
relay_domains = hash:/etc/postfix/relay_domains
transport_maps = hash:/etc/postfix/transport_maps

# /etc/postfix/relay_domains
company.com  OK

# /etc/postfix/transport_maps
# Agent inboxes: deliver to our pipeline via LMTP or pipe
agent-1@company.com       lmtp:unix:/var/run/agentmail/lmtp.sock
support-bot@company.com   lmtp:unix:/var/run/agentmail/lmtp.sock

# Everything else at company.com: forward to Google
company.com               smtp:[aspmx.l.google.com]:25

# Alternatively, use recipient_canonical_maps to query a MySQL/DynamoDB backend
# for dynamic routing decisions
```

For Postfix, dynamic routing can be achieved with `transport_maps` backed by a database query (via `tcp:` or `socketmap:` table types), enabling real-time inbox lookups without reloading Postfix configuration.

### High Availability Requirements

Since our proxy sits in the critical path for ALL email to the customer's domain, high availability is paramount. If our proxy goes down, **no one at the company receives email** -- not agents, not humans.

**Multi-AZ Deployment:**

```
                    Route 53
                    (DNS failover or health-checked routing)
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
        NLB (AZ-a)   NLB (AZ-b)   NLB (AZ-c)
           │            │            │
           ▼            ▼            ▼
        ECS Task     ECS Task     ECS Task
        (Haraka)     (Haraka)     (Haraka)
```

Actually, NLB is already multi-AZ by default. A single NLB distributes across all AZs:

```
                    Route 53
                    company.com MX → smtp-proxy.agentmail.dev
                        │
                        ▼
                 Network Load Balancer
                 (spans AZ-a, AZ-b, AZ-c)
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
        ECS Task     ECS Task     ECS Task
        (AZ-a)       (AZ-b)       (AZ-c)
```

**Health Check Strategy:**

- NLB health checks: TCP health check on port 25 every 10 seconds, 2 consecutive failures = unhealthy
- ECS service: minimum 3 tasks, maximum 20 tasks, auto-scaling on CPU and connection count
- The NLB automatically routes away from unhealthy tasks
- If ALL tasks in a region are unhealthy, Route 53 health-checked DNS failover switches to a secondary region

**Fallback MX Records:**

Even with our proxy as the primary MX, we can set up fallback MX records pointing directly to Google/Microsoft as a last resort:

```
company.com MX records:
  MX 10  smtp-proxy.agentmail.dev       (our proxy -- primary)
  MX 50  aspmx.l.google.com             (Google -- fallback)
  MX 60  alt1.aspmx.l.google.com        (Google -- fallback)
```

If our proxy is completely unreachable, sending MTAs will fall back to Google's MX. In this degraded mode, agent inboxes won't receive mail (because Google doesn't route to us), but human email still works. This is an acceptable degradation: human email continues, agent email pauses until our proxy recovers.

### Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Proxy outage | All email for the domain queued/bounced | Multi-AZ, auto-scaling, fallback MX, 24/7 monitoring |
| Proxy latency spike | Email delivery slowed for all recipients | Performance monitoring, auto-scaling, connection pooling |
| DynamoDB lookup failure | Cannot determine if address is agent or human | Fail-open: forward to upstream MX (humans get mail, agents may miss) |
| Redis cache failure | Increased DynamoDB load, higher latency | DynamoDB direct lookups, cache rebuild, Redis cluster mode |
| Upstream MX unreachable | Human email cannot be delivered | Haraka retry queue, multi-MX upstream, alerting |
| Message corruption in proxy | Data integrity issues | SMTP protocol validation, message checksums, logging |
| SPF alignment issues | Messages forwarded to upstream may fail SPF | SRS (Sender Rewriting Scheme) for forwarded messages |

### SPF Considerations (SRS)

When our proxy forwards email to Google/Microsoft, the receiving MX sees the connection coming from our IP, not the original sender's IP. This can cause SPF failures because the SPF record for the original sender's domain doesn't include our proxy's IP.

Solution: **Sender Rewriting Scheme (SRS)**

SRS rewrites the envelope sender (MAIL FROM) to our domain when forwarding:

```
Original: MAIL FROM: <alice@external.com>
Rewritten: MAIL FROM: <SRS0=HHH=TT=external.com=alice@company.com>
```

This way, when Google/Microsoft receives the forwarded message, the SPF check is against `company.com` (which includes our proxy's IP), not `external.com`. The SRS-encoded address preserves the original sender information so bounces can be routed back correctly.

Haraka has an SRS plugin (`haraka-plugin-srs`). Postfix has SRS support via `postsrsd`.

### When to Recommend This Approach

- Customer needs seamless `@company.com` addresses for agents AND humans
- Customer's email provider doesn't support recipient-based routing (not Google Workspace or Microsoft 365)
- Customer has a custom/on-premises email server without transport rule capabilities
- Customer wants maximum control and is willing to accept the operational complexity
- Customer's security team approves routing all email through a third party (us)

---

## Approach 6: Sending-Only Mode (Outbound Only)

**Simplest option. No MX changes. Agent can send from `company.com` but cannot receive on `company.com`.**

### Concept

If the customer only needs agents to SEND email from their domain (e.g., an agent sends a notification from `notifications@company.com`) but does NOT need to receive inbound email on that domain, no MX changes are required at all. We only need to verify the domain in SES for sending and configure the DNS authentication records (DKIM, SPF) to include SES alongside the existing provider.

### How It Works

1. Customer verifies `company.com` in SES (DKIM verification via CNAME records)
2. Customer updates SPF to include `amazonses.com` alongside their existing provider
3. SES DKIM uses a different selector than Google/Microsoft -- no conflict
4. Agent sends email via SES using `From: agent@company.com`
5. Receiving servers verify DKIM (SES selector), SPF (includes amazonses.com), DMARC (passes alignment)
6. No MX changes needed because we're not receiving email on this domain

### DNS Configuration

```
# Existing records (Google Workspace example -- DO NOT REMOVE):
company.com  MX   1   aspmx.l.google.com
company.com  MX   5   alt1.aspmx.l.google.com
company.com  MX   10  alt2.aspmx.l.google.com
company.com  TXT  "v=spf1 include:_spf.google.com ~all"
google._domainkey.company.com  TXT  "v=DKIM1; k=rsa; p=MIGfMA0G..."

# New records to ADD (do not remove existing ones):
# SES DKIM (three CNAME records -- selectors are unique, no conflict with Google)
abcdef._domainkey.company.com  CNAME  abcdef.dkim.amazonses.com
ghijkl._domainkey.company.com  CNAME  ghijkl.dkim.amazonses.com
mnopqr._domainkey.company.com  CNAME  mnopqr.dkim.amazonses.com

# Updated SPF (add amazonses.com to existing SPF record):
company.com  TXT  "v=spf1 include:_spf.google.com include:amazonses.com ~all"

# DMARC (no change needed if already set; if not, add):
_dmarc.company.com  TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@company.com"
```

### Why DKIM and SPF Can Coexist

**DKIM:** DKIM records are stored under a selector-specific subdomain (`selector._domainkey.domain.com`). Each provider uses its own selector:

- Google Workspace: `google._domainkey.company.com`
- Microsoft 365: `selector1._domainkey.company.com` and `selector2._domainkey.company.com`
- Amazon SES: Three random selectors like `abcdef._domainkey.company.com`

These are independent DNS records under different subdomains. An unlimited number of DKIM selectors can coexist. When verifying a DKIM signature, the receiving server looks up the specific selector indicated in the `DKIM-Signature` header of the message (`s=` tag). There is no conflict.

**SPF:** An SPF record is a single TXT record on the domain that lists all authorized sending sources. Multiple `include:` mechanisms can be chained:

```
v=spf1 include:_spf.google.com include:amazonses.com include:spf.protection.outlook.com ~all
```

The SPF specification (RFC 7208) allows up to 10 DNS lookups in the SPF evaluation chain. Each `include:` counts as one lookup, and the included domain's SPF record may contain further lookups. In practice:

- `include:_spf.google.com` → resolves to ~3-4 additional lookups
- `include:amazonses.com` → resolves to ~1-2 additional lookups
- `include:spf.protection.outlook.com` → resolves to ~2-3 additional lookups

So having Google + SES is well within the 10-lookup limit (~5-6 lookups). Having Google + SES + Microsoft is tight but usually works (~8-9 lookups). If the customer has many providers, they may hit the 10-lookup limit and need to flatten their SPF record.

**DMARC:** DMARC requires either SPF or DKIM alignment (or both). Since SES aligns both DKIM (using the customer's domain as the `d=` value) and SPF (envelope sender can be set to the customer's domain), DMARC passes for SES-sent messages independently of the existing provider.

### Handling Replies

The limitation of outbound-only mode: if someone replies to an email sent by the agent (`agent@company.com`), the reply goes to `agent@company.com`, which is delivered to Google/Microsoft (since MX points there). The agent never sees the reply.

Workarounds:

1. **Set `Reply-To` to a subdomain address:** The agent sends `From: agent@company.com` with `Reply-To: agent@agents.company.com` (subdomain approach). Replies go to the subdomain, which routes to our system.
2. **Set `Reply-To` to an AgentMail address:** `Reply-To: agent@agentmail.dev`. Less professional but functional.
3. **Google/Microsoft forwarding rule:** Configure a forwarding rule in Google/Microsoft to forward replies to `agent@company.com` to our system (similar to Approach 2/3 but only for specific addresses).
4. **Accept the limitation:** For notification-only agents (no-reply use case), replies are not expected.

### Pros

- **Zero MX risk.** MX records are untouched. Human email is completely unaffected.
- **Simplest DNS setup.** Only DKIM CNAMEs and an SPF update.
- **Works with any email provider.** No provider-specific configuration.
- **No inbound SMTP endpoint needed.** Reduces infrastructure requirements.
- **Fastest to implement.** Can be set up in minutes.

### Cons

- **No inbound email.** Agents cannot receive email on `company.com`. Replies to agent-sent messages go to the existing email provider, not to our system.
- **Limited functionality.** Many agent use cases require receiving email (support intake, form processing, conversational agents).
- **Reply-To workaround is imperfect.** Using a different `Reply-To` address may confuse recipients.

---

## DNS Configuration Guide

### Multi-Provider SPF Record

SPF is the most common source of configuration errors when multiple email providers share a domain. There must be exactly ONE SPF TXT record per domain. Multiple SPF records cause failures.

**Correct: Single SPF record with multiple includes:**

```
company.com  TXT  "v=spf1 include:_spf.google.com include:amazonses.com ~all"
```

**Incorrect: Multiple SPF records (will cause validation failures):**

```
company.com  TXT  "v=spf1 include:_spf.google.com ~all"
company.com  TXT  "v=spf1 include:amazonses.com ~all"      ← WRONG: second SPF record
```

**SPF records by provider:**

| Provider | SPF Include |
|----------|------------|
| Google Workspace | `include:_spf.google.com` |
| Microsoft 365 | `include:spf.protection.outlook.com` |
| Amazon SES | `include:amazonses.com` |
| Zoho Mail | `include:zoho.com` |
| Fastmail | `include:spf.fastmail.com` |
| ProtonMail | `include:_spf.protonmail.ch` |

**Combined examples:**

```
# Google Workspace + Amazon SES (~6 DNS lookups)
v=spf1 include:_spf.google.com include:amazonses.com ~all

# Microsoft 365 + Amazon SES (~5 DNS lookups)
v=spf1 include:spf.protection.outlook.com include:amazonses.com ~all

# Google Workspace + Microsoft 365 + Amazon SES (~9 DNS lookups -- near the limit)
v=spf1 include:_spf.google.com include:spf.protection.outlook.com include:amazonses.com ~all
```

**SPF lookup limit management:**

If the customer is near the 10-lookup limit, options include:

1. **SPF flattening:** Replace `include:` with the resolved IP ranges. Tools like `dmarcian SPF surveyor` or `SPF Flattener` automate this. Downside: the flattened IPs can change when the provider updates their IP ranges, requiring periodic re-flattening.
2. **Remove unused providers:** If the customer no longer sends from a particular provider, remove its `include:`.
3. **Use SES with a dedicated envelope sender domain:** SES can use a custom MAIL FROM domain (e.g., `bounce.company.com`) which has its own SPF record, reducing the lookup burden on the apex domain.

### Multi-Provider DKIM Records

DKIM records use unique selectors and do not conflict:

```
# Google Workspace DKIM
google._domainkey.company.com  TXT  "v=DKIM1; k=rsa; p=MIGfMA0G..."

# Microsoft 365 DKIM
selector1._domainkey.company.com  CNAME  selector1-company-com._domainkey.company.onmicrosoft.com
selector2._domainkey.company.com  CNAME  selector2-company-com._domainkey.company.onmicrosoft.com

# Amazon SES DKIM (three selectors)
abcdef._domainkey.company.com    CNAME  abcdef.dkim.amazonses.com
ghijkl._domainkey.company.com    CNAME  ghijkl.dkim.amazonses.com
mnopqr._domainkey.company.com    CNAME  mnopqr.dkim.amazonses.com
```

All of these coexist without conflict. There is no limit on the number of DKIM selectors a domain can have.

### DMARC Configuration

DMARC is a single TXT record at `_dmarc.company.com`. It applies to all email sent from the domain, regardless of which provider sent it. A well-configured DMARC record for multi-provider setups:

```
_dmarc.company.com  TXT  "v=DMARC1; p=quarantine; sp=quarantine; adkim=r; aspf=r; rua=mailto:dmarc-agg@company.com; ruf=mailto:dmarc-forensic@company.com; pct=100"
```

Key fields:

- `p=quarantine`: Policy for messages that fail DMARC (quarantine = send to spam). Start with `p=none` during initial setup to monitor without enforcement, then graduate to `p=quarantine` or `p=reject`.
- `adkim=r`: DKIM alignment mode. `r` = relaxed (organizational domain match). This is important for multi-provider setups because SES may sign with `d=company.com` using its own selector, and relaxed alignment allows this.
- `aspf=r`: SPF alignment mode. `r` = relaxed. Same reasoning.
- `rua`: Aggregate report address. DMARC aggregate reports show which providers are sending on behalf of the domain and whether they pass/fail. Essential for monitoring multi-provider setups.

### Complete DNS Records by Approach

#### Approach 1: Subdomain Strategy

```
# Apex domain (NO CHANGES):
company.com                            MX  1   aspmx.l.google.com
company.com                            MX  5   alt1.aspmx.l.google.com
company.com                            TXT "v=spf1 include:_spf.google.com ~all"
google._domainkey.company.com          TXT "v=DKIM1; k=rsa; p=..."
_dmarc.company.com                     TXT "v=DMARC1; p=quarantine; ..."

# Subdomain (NEW):
agents.company.com                     MX  10  inbound-smtp.us-east-1.amazonaws.com
agents.company.com                     TXT "v=spf1 include:amazonses.com ~all"
abc._domainkey.agents.company.com      CNAME abc.dkim.amazonses.com
def._domainkey.agents.company.com      CNAME def.dkim.amazonses.com
ghi._domainkey.agents.company.com      CNAME ghi.dkim.amazonses.com
_dmarc.agents.company.com              TXT "v=DMARC1; p=quarantine; rua=mailto:dmarc@agents.company.com"
```

#### Approach 2/3: Transport Rules (Google/Microsoft)

```
# Apex domain -- MX stays with Google/Microsoft. Add SES DKIM + SPF for outbound:
company.com                            MX  1   aspmx.l.google.com
company.com                            MX  5   alt1.aspmx.l.google.com
company.com                            TXT "v=spf1 include:_spf.google.com include:amazonses.com ~all"
google._domainkey.company.com          TXT "v=DKIM1; k=rsa; p=..."
abc._domainkey.company.com             CNAME abc.dkim.amazonses.com
def._domainkey.company.com             CNAME def.dkim.amazonses.com
ghi._domainkey.company.com             CNAME ghi.dkim.amazonses.com
_dmarc.company.com                     TXT "v=DMARC1; p=quarantine; adkim=r; aspf=r; ..."

# No MX change. No subdomain needed.
# Inbound routing is handled by Google/Microsoft transport rules, not DNS.
```

#### Approach 5: Smart Router

```
# Apex domain -- MX changes to our proxy. Everything else stays for outbound auth:
company.com                            MX  10  smtp-proxy.agentmail.dev
company.com                            MX  50  aspmx.l.google.com       (fallback)
company.com                            MX  60  alt1.aspmx.l.google.com  (fallback)
company.com                            TXT "v=spf1 include:_spf.google.com include:amazonses.com ~all"
google._domainkey.company.com          TXT "v=DKIM1; k=rsa; p=..."
abc._domainkey.company.com             CNAME abc.dkim.amazonses.com
def._domainkey.company.com             CNAME def.dkim.amazonses.com
ghi._domainkey.company.com             CNAME ghi.dkim.amazonses.com
_dmarc.company.com                     TXT "v=DMARC1; p=quarantine; adkim=r; aspf=r; ..."
```

#### Approach 6: Outbound Only

```
# Apex domain -- MX unchanged. Only add SES DKIM + SPF:
company.com                            MX  1   aspmx.l.google.com
company.com                            MX  5   alt1.aspmx.l.google.com
company.com                            TXT "v=spf1 include:_spf.google.com include:amazonses.com ~all"
google._domainkey.company.com          TXT "v=DKIM1; k=rsa; p=..."
abc._domainkey.company.com             CNAME abc.dkim.amazonses.com
def._domainkey.company.com             CNAME def.dkim.amazonses.com
ghi._domainkey.company.com             CNAME ghi.dkim.amazonses.com
_dmarc.company.com                     TXT "v=DMARC1; p=quarantine; adkim=r; aspf=r; ..."

# No MX change. No subdomain.
```

---

## Recommendation Matrix

| Scenario | Recommended Approach | Complexity | Risk to Human Email | Inbound Capable | Provider-Specific |
|----------|---------------------|-----------|---------------------|-----------------|-------------------|
| Clean separation is acceptable; agents use `agents.company.com` | **Approach 1 (Subdomain)** | Low | None | Yes | No (any provider) |
| Agent only sends from `company.com`, does not receive | **Approach 6 (Outbound Only)** | Low | None | No | No (any provider) |
| Agent needs `@company.com` inbound; customer uses Google Workspace | **Approach 2 (Google Transport Rules)** | Medium | Low | Yes | Google-specific |
| Agent needs `@company.com` inbound; customer uses Microsoft 365 | **Approach 3 (M365 Transport Rules)** | Medium | Low | Yes | Microsoft-specific |
| Agent needs `@company.com` inbound; customer uses another provider without transport rules | **Approach 5 (Smart Router)** | High | Medium | Yes | No (any provider) |
| Maximum control, seamless addresses, willing to accept complexity | **Approach 5 (Smart Router)** | High | Medium | Yes | No (any provider) |
| Dual delivery via MX priority | **Approach 4 (DO NOT USE)** | N/A | High | Unreliable | N/A |

### Decision Flowchart

```
Does the agent need to RECEIVE inbound email on the customer's domain?
│
├── NO → Approach 6 (Outbound Only)
│
└── YES
    │
    Is a subdomain acceptable (e.g., agents.company.com)?
    │
    ├── YES → Approach 1 (Subdomain)
    │
    └── NO (must use apex domain)
        │
        What email provider does the customer use?
        │
        ├── Google Workspace → Approach 2 (Google Transport Rules)
        │
        ├── Microsoft 365 → Approach 3 (M365 Transport Rules)
        │
        └── Other / On-Premises / Unknown
            │
            Does the provider support recipient-based routing/forwarding?
            │
            ├── YES → Configure provider-specific forwarding (similar to Approach 2/3)
            │
            └── NO → Approach 5 (Smart Router)
```

---

## Implementation in Our Platform

### Domain Registration API Changes

The `POST /v1/domains` endpoint needs to support a `coexistence_mode` field that determines how the domain will coexist with an existing email provider.

```json
POST /v1/domains
{
    "domain": "company.com",
    "coexistence_mode": "transport_rule",
    "coexistence_config": {
        "existing_provider": "google_workspace",
        "upstream_mx": [
            "aspmx.l.google.com",
            "alt1.aspmx.l.google.com",
            "alt2.aspmx.l.google.com"
        ]
    }
}
```

**Coexistence modes:**

| Mode | Description | MX Must Point to SES | Requires SMTP Endpoint |
|------|-------------|---------------------|----------------------|
| `exclusive` | We own the domain entirely (existing behavior) | Yes | No |
| `subdomain` | Subdomain strategy (Approach 1) | Yes (subdomain only) | No |
| `transport_rule` | Google/Microsoft routes to us (Approach 2/3) | No | Yes |
| `smart_router` | Our MX proxy routes all mail (Approach 5) | No (points to our proxy) | Yes |
| `outbound_only` | Send only, no inbound (Approach 6) | No | No |

### Domain Model Changes (DynamoDB)

The domain item in DynamoDB gains new attributes:

```json
{
    "PK": "DOMAIN#company.com",
    "SK": "META",
    "domain": "company.com",
    "org_id": "org_abc123",
    "status": "verified",
    "coexistence_mode": "transport_rule",
    "existing_provider": "google_workspace",
    "upstream_mx_hosts": ["aspmx.l.google.com", "alt1.aspmx.l.google.com"],
    "inbound_endpoint": "inbound.agentmail.dev",
    "smtp_endpoint_status": "healthy",
    "ses_identity_arn": "arn:aws:ses:us-east-1:123456789:identity/company.com",
    "dkim_status": "verified",
    "spf_status": "verified",
    "mx_status": "not_applicable",
    "created_at": "2026-04-10T00:00:00Z"
}
```

### DNS Validation Per Mode

The domain verification Lambda adjusts its checks based on coexistence mode:

```python
def validate_domain_dns(domain_record):
    mode = domain_record.get("coexistence_mode", "exclusive")

    # DKIM is always required (for outbound sending)
    dkim_ok = check_dkim_cnames(domain_record["domain"])

    if mode == "exclusive":
        # Standard: MX must point to SES, SPF must include SES
        mx_ok = check_mx_points_to_ses(domain_record["domain"])
        spf_ok = check_spf_includes_ses(domain_record["domain"])
        return dkim_ok and mx_ok and spf_ok

    elif mode == "subdomain":
        # Subdomain MX must point to SES (but we check the subdomain, not apex)
        mx_ok = check_mx_points_to_ses(domain_record["domain"])  # domain is already the subdomain
        spf_ok = check_spf_includes_ses(domain_record["domain"])
        return dkim_ok and mx_ok and spf_ok

    elif mode == "transport_rule":
        # MX does NOT need to point to SES (it points to Google/Microsoft)
        # SPF must include SES (for outbound sending)
        # We cannot validate the transport rule from our side -- we rely on testing
        spf_ok = check_spf_includes_ses(domain_record["domain"])
        return dkim_ok and spf_ok
        # Note: mx_status set to "not_applicable"

    elif mode == "smart_router":
        # MX must point to our SMTP proxy (not SES directly)
        mx_ok = check_mx_points_to_proxy(domain_record["domain"])
        spf_ok = check_spf_includes_ses(domain_record["domain"])
        return dkim_ok and mx_ok and spf_ok

    elif mode == "outbound_only":
        # No MX needed, just DKIM + SPF
        spf_ok = check_spf_includes_ses(domain_record["domain"])
        return dkim_ok and spf_ok
```

### Health Monitoring

For modes that involve forwarding paths (transport_rule, smart_router), we need active health monitoring:

**Transport Rule Health Check:**

- Periodically send a test email from an external address to a test agent inbox on the customer's domain
- Verify the email arrives at our inbound endpoint within expected latency
- If test emails stop arriving, alert the customer that their transport rule may be misconfigured or disabled
- Store health check results in DynamoDB, expose via API

```json
GET /v1/domains/company.com/health
{
    "domain": "company.com",
    "coexistence_mode": "transport_rule",
    "dns_health": {
        "dkim": "pass",
        "spf": "pass",
        "mx": "not_applicable"
    },
    "forwarding_health": {
        "last_test": "2026-04-10T12:00:00Z",
        "last_test_result": "pass",
        "latency_ms": 4200,
        "last_failure": null,
        "consecutive_failures": 0
    },
    "smtp_endpoint_health": {
        "status": "healthy",
        "last_check": "2026-04-10T12:05:00Z",
        "active_connections": 12
    }
}
```

**Smart Router Health Check:**

- Monitor SMTP proxy ECS tasks via NLB health checks
- Monitor forwarding success rate (messages forwarded to upstream MX)
- Monitor agent inbox delivery success rate
- CloudWatch alarms on error rates, latency, and connection failures

### Setup Wizard API

To guide customers through the right approach, we provide a setup wizard endpoint:

```json
POST /v1/domains/setup-wizard
{
    "domain": "company.com",
    "existing_provider": "google_workspace",
    "needs_inbound": true,
    "subdomain_acceptable": false
}

Response:
{
    "recommended_approach": "transport_rule",
    "approach_name": "Google Workspace Transport Rules",
    "steps": [
        {
            "step": 1,
            "action": "api_call",
            "description": "Register domain with AgentMail",
            "endpoint": "POST /v1/domains",
            "body": {
                "domain": "company.com",
                "coexistence_mode": "transport_rule",
                "coexistence_config": {
                    "existing_provider": "google_workspace"
                }
            }
        },
        {
            "step": 2,
            "action": "dns_update",
            "description": "Add SES DKIM records to your DNS",
            "records": [
                {"type": "CNAME", "name": "abc._domainkey.company.com", "value": "abc.dkim.amazonses.com"},
                {"type": "CNAME", "name": "def._domainkey.company.com", "value": "def.dkim.amazonses.com"},
                {"type": "CNAME", "name": "ghi._domainkey.company.com", "value": "ghi.dkim.amazonses.com"}
            ]
        },
        {
            "step": 3,
            "action": "dns_update",
            "description": "Update SPF record to include Amazon SES",
            "records": [
                {"type": "TXT", "name": "company.com", "value": "v=spf1 include:_spf.google.com include:amazonses.com ~all"}
            ],
            "warning": "Modify your existing SPF record -- do not create a second one"
        },
        {
            "step": 4,
            "action": "google_admin",
            "description": "Configure routing rule in Google Admin Console",
            "guide_url": "https://docs.agentmail.dev/guides/google-workspace-routing",
            "summary": "In Google Admin > Gmail > Routing, add a rule that routes agent addresses to inbound.agentmail.dev"
        },
        {
            "step": 5,
            "action": "test",
            "description": "Send a test email to verify the setup",
            "endpoint": "POST /v1/domains/company.com/test-inbound"
        }
    ],
    "alternative_approaches": [
        {
            "approach": "subdomain",
            "reason": "Simpler setup with zero risk to human email",
            "tradeoff": "Agent addresses use @agents.company.com instead of @company.com"
        }
    ]
}
```

---

## Customer Onboarding Guides

### "I Use Google Workspace" Setup Guide

**Goal:** Enable AI agent inboxes on the customer's Google Workspace domain.

**Quick Decision:**

- Want agent addresses like `bot@agents.company.com`? -> Approach 1 (Subdomain). Setup time: ~15 minutes. No Google admin changes.
- Want agent addresses like `bot@company.com`? -> Approach 2 (Transport Rules). Setup time: ~30-45 minutes. Requires Google Workspace admin access (Business Standard or above).
- Only need agents to send, not receive? -> Approach 6 (Outbound Only). Setup time: ~10 minutes. Only DNS changes.

**Approach 2 Walkthrough (Transport Rules):**

1. Register domain via API: `POST /v1/domains { "domain": "company.com", "coexistence_mode": "transport_rule" }`
2. Add three DKIM CNAME records to DNS (provided in API response)
3. Update SPF TXT record: add `include:amazonses.com` to the existing record
4. Wait for DKIM verification (typically 5-15 minutes)
5. In Google Admin Console (`admin.google.com`):
   a. Navigate to Apps > Google Workspace > Gmail > Routing
   b. Add a routing rule:
      - Affects: Inbound messages
      - Envelope recipient matches: your agent address pattern (e.g., `agent-.*@company\.com`)
      - Action: Change route to `inbound.agentmail.dev` port 25 with TLS
6. Send a test email to an agent address
7. Verify it appears in the AgentMail API (`GET /v1/inboxes/{id}/messages`)

**Common Issues:**

- "Message bounced with 'user unknown'": The routing rule pattern doesn't match the address. Check regex syntax.
- "Message delivered to Google, not forwarded": Routing rule priority is too low, or the rule is disabled. Ensure the rule is active and evaluated before other routing rules.
- "SPF failures on outbound agent email": The SPF record has multiple TXT records instead of a single merged record. Combine into one.
- "DKIM verification taking too long": CNAME records may not have propagated. Check with `dig CNAME abc._domainkey.company.com`.

### "I Use Microsoft 365" Setup Guide

**Goal:** Enable AI agent inboxes on the customer's Microsoft 365 domain.

**Quick Decision:**

- Want agent addresses like `bot@agents.company.com`? -> Approach 1 (Subdomain). Setup time: ~15 minutes. No Exchange admin changes.
- Want agent addresses like `bot@company.com`? -> Approach 3 (Transport Rules). Setup time: ~45-60 minutes. Requires Exchange admin access.
- Only need agents to send, not receive? -> Approach 6 (Outbound Only). Setup time: ~10 minutes. Only DNS changes.

**Approach 3 Walkthrough (Transport Rules):**

1. Register domain via API: `POST /v1/domains { "domain": "company.com", "coexistence_mode": "transport_rule" }`
2. Add three DKIM CNAME records to DNS (provided in API response)
3. Update SPF TXT record: add `include:amazonses.com` to the existing record
4. Wait for DKIM verification (typically 5-15 minutes)
5. In Exchange Admin Center (`admin.exchange.microsoft.com`):
   a. Create an outbound connector:
      - From: Office 365, To: Partner organization
      - Smart host: `inbound.agentmail.dev`
      - TLS: Required
      - Scoped to transport rules only
   b. Create mail contacts for each agent address (to prevent NDR):
      ```powershell
      New-MailContact -Name "Agent-Bot" -ExternalEmailAddress "bot@inbound-relay.agentmail.dev"
      Set-MailContact -Identity "Agent-Bot" -EmailAddresses @{Add="bot@company.com"}
      ```
   c. Create a transport rule:
      - Condition: Recipient address matches `^(bot|agent-.*|intake)@company\.com$`
      - Action: Redirect to the AgentMail connector
      - Priority: 0 (highest)
6. Send a test email to an agent address
7. Check Exchange message trace to confirm the transport rule fired
8. Verify the message appears in the AgentMail API

**Common Issues:**

- "550 5.1.1 recipient rejected": Mail contact not created for the agent address. Exchange rejects unknown recipients before the transport rule fires.
- "Message stuck in queue": Connector TLS validation failed. Ensure our SMTP endpoint has a valid certificate.
- "Transport rule not firing": Rule may be in "Test" mode instead of "Enforce" mode. Check rule settings.
- "Intermittent delivery": Multiple transport rules may be conflicting. Ensure the AgentMail rule has the highest priority (0).

### "I Use Another Provider" Setup Guide

**Goal:** Enable AI agent inboxes on a domain hosted with Zoho, Fastmail, ProtonMail, on-premises Exchange, Postfix, or any other provider.

**Quick Decision:**

- Want the simplest path? -> Approach 1 (Subdomain). Works with any provider. Setup time: ~15 minutes.
- Only need agents to send? -> Approach 6 (Outbound Only). Works with any provider. Setup time: ~10 minutes.
- Need agents to receive on the apex domain?
  - Check if your provider supports recipient-based forwarding rules. If yes, configure forwarding similar to Approach 2/3 (specific steps vary by provider).
  - If your provider does NOT support recipient-based forwarding -> Approach 5 (Smart Router). Setup time: ~2-4 hours. Requires MX change. Contact our support team for guided setup.

**Provider-Specific Notes:**

| Provider | Supports Recipient-Based Routing? | Notes |
|----------|----------------------------------|-------|
| Zoho Mail | Yes (via routing rules in Zoho Admin) | Similar to Google Workspace; configure in Zoho Admin > Email Routing |
| Fastmail | Limited (server-side rules per account, not domain-wide) | Subdomain approach recommended |
| ProtonMail | No | Subdomain or Smart Router approach required |
| On-premises Exchange | Yes (transport rules, same as M365) | Configuration via Exchange Management Console or PowerShell |
| Postfix (self-hosted) | Yes (transport_maps) | Customer can configure `transport_maps` to forward agent addresses to our endpoint |
| cPanel/WHM (shared hosting) | Limited (basic forwarders per address) | Subdomain approach recommended; or manual forwarder per agent address |
| Zimbra | Yes (Postfix-based transport maps) | Configure via Zimbra Admin Console or CLI |
| Rackspace Email | No | Subdomain approach required |
| Amazon WorkMail | Yes (flow rules) | Configure inbound flow rule to forward to our endpoint |

For providers that support recipient-based routing, the general pattern is:

1. Keep MX records pointing to the existing provider
2. Configure a routing/forwarding rule in the provider's admin console to forward agent addresses to `inbound.agentmail.dev` (our SMTP endpoint) or to an encoded address on our relay domain
3. Add SES DKIM and SPF records to DNS for outbound sending
4. Test end to end

For providers that do not support routing, the subdomain approach (Approach 1) is strongly recommended over the smart router approach (Approach 5) unless the customer has a strong requirement for apex-domain agent addresses and is willing to accept the operational complexity.

---

## Appendix: SMTP Endpoint Infrastructure

For Approaches 2, 3, and 5, we need a publicly reachable SMTP server that can receive email forwarded by Google Workspace, Microsoft 365, or our own smart router. This section details the shared infrastructure.

### Architecture

```
Internet / Provider Forwarding
      │
      ▼ (port 25, STARTTLS)
┌──────────────────────────────────┐
│ Network Load Balancer            │
│ - TCP listener on port 25        │
│ - Cross-zone load balancing      │
│ - TLS passthrough (Haraka        │
│   handles STARTTLS)              │
│ - Health check: TCP port 25      │
└──────────────┬───────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│  ECS   │ │  ECS   │ │  ECS   │
│ Fargate│ │ Fargate│ │ Fargate│
│ Task   │ │ Task   │ │ Task   │
│(Haraka)│ │(Haraka)│ │(Haraka)│
│ AZ-a   │ │ AZ-b   │ │ AZ-c   │
└───┬────┘ └───┬────┘ └───┬────┘
    │          │          │
    └──────────┼──────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│  S3    │ │Lambda  │ │ Redis  │
│(raw    │ │(inbound│ │(inbox  │
│ MIME)  │ │router) │ │lookup  │
│        │ │        │ │cache)  │
└────────┘ └────────┘ └────────┘
```

### ECS Task Definition

```json
{
    "family": "agentmail-smtp-proxy",
    "networkMode": "awsvpc",
    "requiresCompatibilities": ["FARGATE"],
    "cpu": "1024",
    "memory": "2048",
    "containerDefinitions": [
        {
            "name": "haraka",
            "image": "123456789.dkr.ecr.us-east-1.amazonaws.com/agentmail-haraka:latest",
            "portMappings": [
                {
                    "containerPort": 25,
                    "protocol": "tcp"
                }
            ],
            "environment": [
                {"name": "AWS_REGION", "value": "us-east-1"},
                {"name": "REDIS_URL", "value": "redis://agentmail-cache.xxxxx.use1.cache.amazonaws.com:6379"},
                {"name": "DYNAMODB_TABLE", "value": "agentmail-main"},
                {"name": "S3_BUCKET", "value": "agentmail-inbound-us-east-1"},
                {"name": "LAMBDA_ROUTER_ARN", "value": "arn:aws:lambda:us-east-1:123456789:function:inbound-router"}
            ],
            "logConfiguration": {
                "logDriver": "awslogs",
                "options": {
                    "awslogs-group": "/ecs/agentmail-smtp-proxy",
                    "awslogs-region": "us-east-1",
                    "awslogs-stream-prefix": "haraka"
                }
            },
            "healthCheck": {
                "command": ["CMD-SHELL", "nc -z localhost 25 || exit 1"],
                "interval": 10,
                "timeout": 5,
                "retries": 3,
                "startPeriod": 30
            }
        }
    ]
}
```

### TLS Certificate

The SMTP endpoint must present a valid TLS certificate for STARTTLS. Options:

1. **ACM certificate on NLB:** If using TLS termination at the NLB (TCP+TLS listener), provision a certificate via ACM for `inbound.agentmail.dev`. This is the simplest approach.
2. **Certificate in Haraka:** If using TCP passthrough on the NLB, Haraka handles STARTTLS directly. Mount the certificate files (key + cert + chain) as ECS secrets or via an init container that fetches from ACM/Secrets Manager.

For Google Workspace and Microsoft 365, the TLS certificate must be issued by a publicly trusted CA (not self-signed). Both providers validate the certificate during the SMTP handshake.

### Auto-Scaling

```json
{
    "ServiceName": "agentmail-smtp-proxy",
    "ScalableTargetAction": {
        "MinCapacity": 3,
        "MaxCapacity": 50
    },
    "ScalingPolicies": [
        {
            "PolicyName": "cpu-scaling",
            "PolicyType": "TargetTrackingScaling",
            "TargetTrackingScalingPolicyConfiguration": {
                "TargetValue": 60.0,
                "PredefinedMetricSpecification": {
                    "PredefinedMetricType": "ECSServiceAverageCPUUtilization"
                },
                "ScaleInCooldown": 300,
                "ScaleOutCooldown": 60
            }
        },
        {
            "PolicyName": "connection-scaling",
            "PolicyType": "TargetTrackingScaling",
            "TargetTrackingScalingPolicyConfiguration": {
                "TargetValue": 100.0,
                "CustomizedMetricSpecification": {
                    "MetricName": "ActiveConnectionCount",
                    "Namespace": "AWS/NetworkELB",
                    "Statistic": "Sum"
                },
                "ScaleInCooldown": 300,
                "ScaleOutCooldown": 30
            }
        }
    ]
}
```

### Cost Estimate for SMTP Endpoint

| Component | Monthly Cost (Startup) | Monthly Cost (Scale) |
|-----------|----------------------|---------------------|
| ECS Fargate (3 tasks, 1 vCPU / 2 GB) | ~$110 | ~$550 (15 tasks) |
| Network Load Balancer | ~$23 | ~$23 |
| NLB Data Processing (1M messages, ~5 KB avg) | ~$3 | ~$30 (10M messages) |
| ElastiCache Redis (t3.small) | ~$50 | ~$200 (r6g.large) |
| CloudWatch Logs | ~$5 | ~$50 |
| **Total** | **~$191/month** | **~$853/month** |

This cost is only incurred for customers using Approaches 2, 3, or 5. Customers on Approach 1 (subdomain) or Approach 6 (outbound only) use the standard SES inbound pipeline with no additional SMTP infrastructure cost.
