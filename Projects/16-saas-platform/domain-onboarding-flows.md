# Domain Onboarding Flows

This document provides detailed, step-by-step domain onboarding instructions for every supported configuration. Each flow includes the user experience in the console, the API calls made behind the scenes, the DNS records required, verification timelines, and troubleshooting guidance.

These flows are referenced from the main [SaaS Platform README](./README.md) Section 8 (Self-Service Domain Onboarding) and from the [Email Transport Section 06](../02-email-transport/domain-coexistence.md) (Domain Coexistence).

---

## Table of Contents

- [Flow 1: New Domain (No Existing Provider)](#flow-1-new-domain-no-existing-provider)
- [Flow 2: Subdomain with Google Workspace](#flow-2-subdomain-with-google-workspace)
- [Flow 3: Subdomain with Microsoft 365](#flow-3-subdomain-with-microsoft-365)
- [Flow 4: Transport Rule Routing (Google Workspace)](#flow-4-transport-rule-routing-google-workspace)
- [Flow 5: Transport Rule Routing (Microsoft 365)](#flow-5-transport-rule-routing-microsoft-365)
- [Flow 6: Outbound-Only Domain](#flow-6-outbound-only-domain)
- [Common DNS Provider Guides](#common-dns-provider-guides)
- [Troubleshooting](#troubleshooting)

---

## Flow 1: New Domain (No Existing Provider)

**Use case:** The customer owns a domain that is not currently used for email, or they are willing to move all email to AgentMail. This is the simplest setup because all MX records point directly to SES.

**Example:** Customer owns `newstartup.io` and wants all email handled by AgentMail.

### Prerequisites

- Customer owns the domain and has access to DNS management
- Domain is not currently receiving email through another provider (or customer accepts that existing email routing will change)
- Customer's AgentMail tier allows at least one custom domain

### Step-by-Step Flow

**Step 1: User clicks "Add Domain" in the console**

Console displays a form:
```
Domain name: [newstartup.io________________]
Email provider: (x) None / new domain
                ( ) Google Workspace
                ( ) Microsoft 365
                ( ) Other
```

**Step 2: Console calls the API**

```
POST /v1/domains
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "domain": "newstartup.io",
  "mode": "standalone",
  "existing_provider": null,
  "receive_email": true,
  "send_email": true
}
```

**Step 3: Backend processing**

The Lambda handler executes the following:

```python
def create_domain(org_id, domain, mode, options):
    # 1. Validate domain format
    if not is_valid_domain(domain):
        raise ValidationError("Invalid domain format")
    
    # 2. Check domain is not already registered by another org
    existing = query_domain_by_name(domain)
    if existing and existing['org_id'] != org_id:
        raise ConflictError("Domain is already registered to another organization")
    
    # 3. Check tier limits
    current_count = count_org_domains(org_id)
    limit = get_org_limits(org_id)['custom_domains']
    if current_count >= limit:
        raise QuotaExceededError(f"Domain limit reached ({current_count}/{limit})")
    
    # 4. Create SES email identity
    ses_response = ses_client.create_email_identity(
        EmailIdentity=domain,
        DkimSigningAttributes={
            'DomainSigningAttributesOrigin': 'AWS_SES'  # Easy DKIM
        },
        ConfigurationSetName=f'agentmail-org-{org_id}',
        Tags=[
            {'Key': 'org_id', 'Value': org_id},
            {'Key': 'environment', 'Value': 'production'}
        ]
    )
    
    # 5. Extract DKIM tokens from SES response
    dkim_tokens = ses_response['DkimAttributes']['Tokens']
    # Typically 3 tokens like: ['abcdefg1234567', 'hijklmn8901234', 'opqrstu5678901']
    
    # 6. Build DNS records list
    dns_records = build_dns_records(domain, dkim_tokens, mode, options)
    
    # 7. Store domain record in DynamoDB
    domain_id = generate_ulid()
    dynamodb.put_item(
        TableName='agentmail-main',
        Item={
            'PK': f'ORG#{org_id}',
            'SK': f'DOMAIN#{domain_id}',
            'domain_id': domain_id,
            'domain': domain,
            'mode': mode,
            'status': 'pending_verification',
            'dns_records': dns_records,
            'ses_identity_arn': f'arn:aws:ses:us-east-1:{ACCOUNT_ID}:identity/{domain}',
            'created_at': now_iso8601(),
            'verified_at': None,
            'org_id': org_id,
            # GSI for domain lookup
            'GSI_DOMAIN_PK': f'DOMAIN#{domain}',
            'GSI_DOMAIN_SK': f'ORG#{org_id}'
        }
    )
    
    # 8. Add SES receipt rule for this domain (for inbound email)
    add_ses_receipt_rule(domain, org_id)
    
    return {
        'domain_id': domain_id,
        'domain': domain,
        'status': 'pending_verification',
        'dns_records': dns_records
    }
```

**Step 4: API returns DNS records**

```json
{
  "domain_id": "dom_01HYX5K9M2N3P4Q5R6S7T8U9V0",
  "domain": "newstartup.io",
  "mode": "standalone",
  "status": "pending_verification",
  "dns_records": [
    {
      "id": "rec_001",
      "type": "MX",
      "name": "newstartup.io",
      "value": "10 inbound-smtp.us-east-1.amazonaws.com",
      "purpose": "Routes incoming email to AgentMail",
      "required": true,
      "status": "pending"
    },
    {
      "id": "rec_002",
      "type": "TXT",
      "name": "newstartup.io",
      "value": "v=spf1 include:amazonses.com ~all",
      "purpose": "SPF -- Authorizes AgentMail to send email from your domain",
      "required": true,
      "status": "pending"
    },
    {
      "id": "rec_003",
      "type": "CNAME",
      "name": "abcdefg1234567._domainkey.newstartup.io",
      "value": "abcdefg1234567.dkim.amazonses.com",
      "purpose": "DKIM signature key 1 of 3",
      "required": true,
      "status": "pending"
    },
    {
      "id": "rec_004",
      "type": "CNAME",
      "name": "hijklmn8901234._domainkey.newstartup.io",
      "value": "hijklmn8901234.dkim.amazonses.com",
      "purpose": "DKIM signature key 2 of 3",
      "required": true,
      "status": "pending"
    },
    {
      "id": "rec_005",
      "type": "CNAME",
      "name": "opqrstu5678901._domainkey.newstartup.io",
      "value": "opqrstu5678901.dkim.amazonses.com",
      "purpose": "DKIM signature key 3 of 3",
      "required": true,
      "status": "pending"
    },
    {
      "id": "rec_006",
      "type": "TXT",
      "name": "_dmarc.newstartup.io",
      "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.to; pct=100",
      "purpose": "DMARC policy -- Protects your domain from email spoofing",
      "required": false,
      "status": "pending",
      "note": "Recommended but optional. If you already have a DMARC record, add our reporting address to your existing rua= tag."
    }
  ],
  "created_at": "2026-04-10T14:00:00Z"
}
```

**Step 5: Console displays DNS records**

The console renders each record with:
- Record type badge (MX, TXT, CNAME)
- Name field with copy button
- Value field with copy button
- Required/optional label
- Current status (pending/verified)
- Registrar-specific help links

**Step 6: User adds DNS records at their registrar**

The user opens their domain registrar (Cloudflare, GoDaddy, Namecheap, Route 53, etc.) and adds the records.

**Step 7: User clicks "Check DNS" (or waits for auto-check)**

```
POST /v1/domains/dom_01HYX5K9M2N3P4Q5R6S7T8U9V0/verify
Authorization: Bearer <jwt_token>
```

The backend performs DNS lookups for each record (see the `check_dns_records` function in the main README).

**Step 8: Verification completes**

When all required records are verified:
- Domain status changes to `verified`
- Webhook `domain.verified` fires
- Email notification sent to org owner
- Console shows green checkmarks on all records
- "Create inbox" button appears

**Step 9: First inbox creation**

```
POST /v1/inboxes
Authorization: Bearer <api_key>
Content-Type: application/json

{
  "email": "support@newstartup.io",
  "display_name": "Support Bot",
  "pod_id": "pod_default"
}
```

### DNS Records Summary (Standalone)

| Type | Name | Value | Required | TTL |
|------|------|-------|----------|-----|
| MX | `newstartup.io` | `10 inbound-smtp.us-east-1.amazonaws.com` | Yes | 3600 |
| TXT | `newstartup.io` | `v=spf1 include:amazonses.com ~all` | Yes | 3600 |
| CNAME | `{token1}._domainkey.newstartup.io` | `{token1}.dkim.amazonses.com` | Yes | 3600 |
| CNAME | `{token2}._domainkey.newstartup.io` | `{token2}.dkim.amazonses.com` | Yes | 3600 |
| CNAME | `{token3}._domainkey.newstartup.io` | `{token3}.dkim.amazonses.com` | Yes | 3600 |
| TXT | `_dmarc.newstartup.io` | `v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.to; pct=100` | No | 3600 |

### Verification Timeline

- **MX and TXT records:** Usually propagate within 5-15 minutes
- **CNAME records (DKIM):** Can take 15-60 minutes, sometimes up to 24 hours with some registrars
- **SES DKIM verification:** SES checks independently and may take up to 72 hours in rare cases, though typically completes within 1 hour after DNS propagation
- **Total expected time:** 15-60 minutes for most registrars

### Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| MX record shows pending after 1 hour | DNS propagation delay or incorrect value | Verify the value includes the priority number (`10`). Some registrars have a separate priority field. |
| DKIM CNAMEs not verifying | Registrar adding `.newstartup.io` suffix automatically | Enter only the subdomain part (e.g., `abcdefg1234567._domainkey`) and let the registrar append the domain. |
| SPF record conflict | Existing SPF record for the domain | Merge the records: `v=spf1 include:amazonses.com include:_spf.google.com ~all` |
| DMARC record conflict | Existing DMARC record | Add `rua=mailto:dmarc-reports@agentmail.to` to the existing record. Do not create a second DMARC record. |
| SES shows "Pending" even after DNS is correct | SES internal propagation delay | Wait up to 72 hours. Use the "Check DNS" button to force a re-check. |

---

## Flow 2: Subdomain with Google Workspace

**Use case:** The customer uses Google Workspace for `company.com` and wants AgentMail to handle email for a subdomain like `agents.company.com`. This is the **recommended approach** for coexistence because it has zero impact on existing Google email.

**Example:** Customer has Google Workspace on `company.com`. They want `support-bot@agents.company.com`, `sales-ai@agents.company.com`, etc.

### Prerequisites

- Customer uses Google Workspace on the apex domain (`company.com`)
- Customer has DNS access to add records for a subdomain
- Customer does NOT need Google Workspace admin access (subdomain approach is DNS-only)

### Step-by-Step Flow

**Step 1: User selects Google Workspace as existing provider**

Console shows:
```
Domain name: [company.com___________________]
Email provider: ( ) None / new domain
                (x) Google Workspace
                ( ) Microsoft 365
                ( ) Other
```

**Step 2: Console recommends subdomain approach**

```
Since you use Google Workspace on company.com, we recommend using
a subdomain for AgentMail. This ensures your existing email is
completely unaffected.

  (x) Use a subdomain (Recommended)
      Subdomain prefix: [agents______]
      Your agents will have addresses like:
        support-bot@agents.company.com
        sales-ai@agents.company.com

  ( ) Use transport rules (Advanced)
      Route specific addresses from company.com to AgentMail.
      Requires Google Workspace admin access.

  ( ) Outbound only
      Send from @company.com addresses but receive on @agentmail.to
```

**Step 3: Console calls the API with subdomain mode**

```
POST /v1/domains
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
  "domain": "company.com",
  "mode": "subdomain",
  "subdomain_prefix": "agents",
  "existing_provider": "google_workspace",
  "receive_email": true,
  "send_email": true
}
```

**Step 4: Backend processes the subdomain setup**

```python
def create_subdomain(org_id, apex_domain, subdomain_prefix, provider):
    full_domain = f"{subdomain_prefix}.{apex_domain}"
    # e.g., "agents.company.com"
    
    # Create SES identity for the SUBDOMAIN, not the apex
    ses_response = ses_client.create_email_identity(
        EmailIdentity=full_domain,
        DkimSigningAttributes={
            'DomainSigningAttributesOrigin': 'AWS_SES'
        },
        ConfigurationSetName=f'agentmail-org-{org_id}'
    )
    
    dkim_tokens = ses_response['DkimAttributes']['Tokens']
    
    # Build DNS records for the subdomain
    dns_records = [
        {
            "type": "MX",
            "name": full_domain,
            "value": "10 inbound-smtp.us-east-1.amazonaws.com",
            "purpose": f"Routes email to @{full_domain} addresses through AgentMail",
            "required": True,
            "note": "This MX record is for the subdomain only. Your Google Workspace MX records on company.com are not affected."
        },
        {
            "type": "TXT",
            "name": full_domain,
            "value": "v=spf1 include:amazonses.com ~all",
            "purpose": f"SPF for {full_domain} -- separate from your company.com SPF",
            "required": True,
            "note": "This is a NEW SPF record on the subdomain. Do not modify your existing company.com SPF record."
        }
    ]
    
    # DKIM records for the subdomain
    for token in dkim_tokens:
        dns_records.append({
            "type": "CNAME",
            "name": f"{token}._domainkey.{full_domain}",
            "value": f"{token}.dkim.amazonses.com",
            "purpose": "DKIM signature key",
            "required": True
        })
    
    # DMARC for the subdomain
    dns_records.append({
        "type": "TXT",
        "name": f"_dmarc.{full_domain}",
        "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.to; pct=100",
        "purpose": f"DMARC policy for {full_domain}",
        "required": False,
        "note": "Subdomain DMARC is independent of your company.com DMARC policy."
    })
    
    # Store with mode=subdomain and the apex domain reference
    store_domain_record(org_id, full_domain, dns_records, 
                        mode='subdomain', 
                        apex_domain=apex_domain,
                        existing_provider=provider)
    
    return dns_records
```

**Step 5: API returns subdomain-specific DNS records**

```json
{
  "domain_id": "dom_02ABC...",
  "domain": "agents.company.com",
  "apex_domain": "company.com",
  "mode": "subdomain",
  "existing_provider": "google_workspace",
  "status": "pending_verification",
  "dns_records": [
    {
      "type": "MX",
      "name": "agents.company.com",
      "value": "10 inbound-smtp.us-east-1.amazonaws.com",
      "required": true,
      "status": "pending",
      "note": "Only affects the agents.company.com subdomain. Google Workspace email on company.com is not affected."
    },
    {
      "type": "TXT",
      "name": "agents.company.com",
      "value": "v=spf1 include:amazonses.com ~all",
      "required": true,
      "status": "pending",
      "note": "New SPF record for the subdomain. Do NOT modify your existing company.com SPF record."
    },
    {
      "type": "CNAME",
      "name": "abc123._domainkey.agents.company.com",
      "value": "abc123.dkim.amazonses.com",
      "required": true,
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "def456._domainkey.agents.company.com",
      "value": "def456.dkim.amazonses.com",
      "required": true,
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "ghi789._domainkey.agents.company.com",
      "value": "ghi789.dkim.amazonses.com",
      "required": true,
      "status": "pending"
    },
    {
      "type": "TXT",
      "name": "_dmarc.agents.company.com",
      "value": "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.to; pct=100",
      "required": false,
      "status": "pending"
    }
  ]
}
```

**Step 6: Console displays records with Google-specific guidance**

The console shows an informational banner:

```
Important: These DNS records are for the subdomain agents.company.com only.
Your Google Workspace email on company.com will not be affected.

If you manage DNS in Google Domains, Cloudflare, or another registrar,
add these records as new entries. Do NOT modify existing records for
company.com.
```

**Step 7: Verification and first inbox**

Verification proceeds identically to Flow 1. After verification:

```
POST /v1/inboxes
{
  "email": "support-bot@agents.company.com",
  "display_name": "Support Bot"
}
```

### What Happens to Existing Google Email

Nothing. Because the MX record is on `agents.company.com` (not `company.com`), Google's MX records on the apex domain are untouched. Email to `user@company.com` continues routing to Google Workspace. Email to `support-bot@agents.company.com` routes to AgentMail.

```
user@company.com          → Google Workspace (MX: aspmx.l.google.com)
support-bot@agents.company.com → AgentMail (MX: inbound-smtp.us-east-1.amazonaws.com)
```

The two systems are completely independent at the DNS level.

### DNS Records Summary (Subdomain with Google)

| Type | Name | Value | Required | Affects Google? |
|------|------|-------|----------|-----------------|
| MX | `agents.company.com` | `10 inbound-smtp.us-east-1.amazonaws.com` | Yes | No |
| TXT | `agents.company.com` | `v=spf1 include:amazonses.com ~all` | Yes | No |
| CNAME | `{token}._domainkey.agents.company.com` (x3) | `{token}.dkim.amazonses.com` | Yes | No |
| TXT | `_dmarc.agents.company.com` | `v=DMARC1; p=quarantine; ...` | No | No |

### Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| Google receiving agent emails | MX record not set or not propagated | Verify MX record exists specifically on `agents.company.com`, not on `company.com` |
| SPF failures when sending from subdomain | Missing or incorrect SPF on subdomain | Confirm `v=spf1 include:amazonses.com ~all` is on `agents.company.com` (not the apex) |
| DMARC alignment failures | DMARC on apex rejecting subdomain email | Add a DMARC record on the subdomain. If apex has `sp=reject`, subdomain DMARC overrides it. |
| Cannot add subdomain records | DNS provider does not support subdomain records | Most providers support this. For Google Domains, add records using the full name `agents.company.com`. For Cloudflare, add records with name `agents`. |

---

## Flow 3: Subdomain with Microsoft 365

**Use case:** The customer uses Microsoft 365 (Exchange Online) for `company.com` and wants AgentMail on a subdomain like `bots.company.com`.

**Example:** Customer has Microsoft 365 on `company.com`. They want `agent-1@bots.company.com`, `agent-2@bots.company.com`.

### Prerequisites

- Customer uses Microsoft 365 / Exchange Online on `company.com`
- Customer has DNS access to add subdomain records
- No Microsoft 365 admin access needed for subdomain approach

### Differences from Google Workspace Flow

The setup is nearly identical to Flow 2. The differences are:

1. **SPF record:** The same SPF record is used (`v=spf1 include:amazonses.com ~all` on the subdomain). Microsoft 365's SPF (`include:spf.protection.outlook.com`) is only on the apex domain.

2. **DMARC consideration:** If the customer's apex DMARC record has `sp=reject` (subdomain policy = reject), the subdomain needs its own DMARC record to override. Microsoft's default DMARC does not usually set `sp=`, but it should be checked.

3. **Console guidance:** The informational text references Microsoft 365 instead of Google Workspace.

### Step-by-Step Flow

**Step 1-2:** Identical to Flow 2, but user selects "Microsoft 365" as existing provider.

**Step 3: API call**

```
POST /v1/domains
{
  "domain": "company.com",
  "mode": "subdomain",
  "subdomain_prefix": "bots",
  "existing_provider": "microsoft_365",
  "receive_email": true,
  "send_email": true
}
```

**Step 4-8:** Identical to Flow 2. The DNS records are the same structure, just with `bots.company.com` instead of `agents.company.com`.

### DNS Records Summary (Subdomain with MS365)

| Type | Name | Value | Required | Affects MS365? |
|------|------|-------|----------|----------------|
| MX | `bots.company.com` | `10 inbound-smtp.us-east-1.amazonaws.com` | Yes | No |
| TXT | `bots.company.com` | `v=spf1 include:amazonses.com ~all` | Yes | No |
| CNAME | `{token}._domainkey.bots.company.com` (x3) | `{token}.dkim.amazonses.com` | Yes | No |
| TXT | `_dmarc.bots.company.com` | `v=DMARC1; p=quarantine; ...` | No | No |

### Microsoft-Specific Considerations

1. **Autodiscover:** Microsoft 365 uses `autodiscover.company.com` for client configuration. A subdomain like `bots.company.com` does not interfere with Autodiscover.

2. **Accepted domains in Exchange:** The subdomain `bots.company.com` should NOT be added as an accepted domain in Exchange Admin Center. It is managed entirely outside Microsoft.

3. **Azure AD:** If the customer has Azure AD with the domain `company.com` verified, the subdomain `bots.company.com` does not need separate Azure AD verification.

### Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| Microsoft trying to route subdomain email | `bots.company.com` added as accepted domain in Exchange | Remove the subdomain from Exchange Admin Center > Mail flow > Accepted domains |
| DKIM failures | CNAME records not propagated | Some MS-managed DNS zones have slower propagation. Wait up to 4 hours. |
| Cannot create subdomain in Azure DNS | Permissions issue | Ensure the user has DNS Zone Contributor role on the Azure DNS zone |

---

## Flow 4: Transport Rule Routing (Google Workspace)

**Use case:** The customer wants agent email addresses on their apex domain (`agent@company.com`, not `agent@agents.company.com`). They use Google Workspace and want to route specific addresses to AgentMail while keeping all other email on Google.

**Example:** Customer has Google Workspace on `company.com`. They want `support-bot@company.com` and `sales-ai@company.com` to go to AgentMail, while `alice@company.com` and `bob@company.com` stay on Google.

### Prerequisites

- Customer has **Google Workspace Admin access** (Super Admin or Groups Admin)
- Customer has DNS access to add/modify TXT and CNAME records
- Customer understands this is more complex than the subdomain approach

### Important Warnings

```
⚠ Transport rule routing is an advanced configuration.
  - Requires Google Workspace admin access
  - Mis-configuration can disrupt email for all users
  - Changes to Google Workspace routing rules take 24-48 hours to propagate
  - We recommend the subdomain approach unless apex-domain addresses are required
```

### Step-by-Step Flow

**Step 1: User selects transport rule approach in console**

```
Since you use Google Workspace on company.com, we recommend using
a subdomain. However, if you need addresses like agent@company.com:

  ( ) Use a subdomain (Recommended)
  (x) Use transport rules (Advanced)
      Route specific @company.com addresses to AgentMail.
      Requires Google Workspace Super Admin access.
```

**Step 2: Console calls the API**

```
POST /v1/domains
{
  "domain": "company.com",
  "mode": "transport_rule",
  "existing_provider": "google_workspace",
  "receive_email": true,
  "send_email": true
}
```

**Step 3: API returns DNS records + routing instructions**

For transport rule mode, the MX records do NOT change (they stay pointing to Google). Instead, we need:
- DKIM records for SES (for outbound sending from AgentMail)
- SPF record update (add `include:amazonses.com` to existing SPF)
- Google Workspace routing rule configuration

```json
{
  "domain_id": "dom_03DEF...",
  "domain": "company.com",
  "mode": "transport_rule",
  "status": "pending_verification",
  "dns_records": [
    {
      "type": "TXT",
      "name": "company.com",
      "value": "v=spf1 include:_spf.google.com include:amazonses.com ~all",
      "purpose": "Updated SPF -- adds AgentMail alongside Google",
      "required": true,
      "status": "pending",
      "note": "MODIFY your existing SPF record. Do NOT create a second SPF record. Add 'include:amazonses.com' to your existing SPF."
    },
    {
      "type": "CNAME",
      "name": "abc123._domainkey.company.com",
      "value": "abc123.dkim.amazonses.com",
      "purpose": "DKIM signature key 1 of 3 (for AgentMail outbound)",
      "required": true,
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "def456._domainkey.company.com",
      "value": "def456.dkim.amazonses.com",
      "purpose": "DKIM signature key 2 of 3",
      "required": true,
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "ghi789._domainkey.company.com",
      "value": "ghi789.dkim.amazonses.com",
      "purpose": "DKIM signature key 3 of 3",
      "required": true,
      "status": "pending"
    }
  ],
  "routing_instructions": {
    "provider": "google_workspace",
    "steps": "See Google Workspace Admin Console instructions below"
  }
}
```

**Note:** No MX record change. MX stays pointing to Google (`aspmx.l.google.com`). Google receives ALL email for `company.com` and then routes agent-addressed email to AgentMail via a routing rule.

**Step 4: Console shows DNS changes AND Google Admin instructions**

The console displays two sections:

**Section A: DNS Changes**

```
Step 1: Update your SPF record

Your current SPF record on company.com is probably:
  v=spf1 include:_spf.google.com ~all

Change it to:
  v=spf1 include:_spf.google.com include:amazonses.com ~all

Important: Do NOT create a second TXT record with "v=spf1".
Only one SPF record is allowed per domain.

Step 2: Add DKIM CNAME records

Add these 3 CNAME records (same as other flows):
  [records listed with copy buttons]
```

**Section B: Google Workspace Routing Rule**

```
Step 3: Configure routing in Google Workspace Admin Console

1. Open Google Workspace Admin Console
   https://admin.google.com

2. Navigate to:
   Apps > Google Workspace > Gmail > Routing

3. Click "Add another rule" under "Routing"

4. Configure the rule:

   Name: AgentMail Routing
   
   Email messages to affect:
   ☑ Inbound
   ☐ Outbound
   ☐ Internal - sending
   ☐ Internal - receiving
   
   For the above types of messages, do the following:
   
   a. Under "Envelope filter", select:
      "Only affect specific envelope recipients"
      
      Pattern match:
      ┌─────────────────────────────────────────┐
      │ Regexp: ^(support-bot|sales-ai)@company\.com$  │
      └─────────────────────────────────────────┘
      
      OR use Group-based routing (recommended):
      Create a Google Group: agentmail-addresses@company.com
      Add members: support-bot@company.com, sales-ai@company.com
      Then select "Only affect specific envelope recipients" > Group
   
   b. Under "Route", select:
      "Change route"
      
      Add route:
      ┌──────────────────────────────────────────┐
      │ Route name: AgentMail                     │
      │ SMTP host: inbound-smtp.us-east-1.amazonaws.com  │
      │ Port: 25                                  │
      │ Require TLS: ☑ Yes                        │
      └──────────────────────────────────────────┘
   
   c. Under "Options":
      ☑ Perform this action on non-recognized and recognized addresses
      ☑ Skip spam filter for this message
   
5. Click "Add Setting"

6. Click "Save" at the bottom of the Gmail settings page

Note: Changes may take 24-48 hours to propagate across Google's infrastructure.
```

**Step 5: User completes DNS + Google Admin configuration**

**Step 6: Testing the routing**

After DNS verification succeeds and Google's routing rule propagates (24-48h):

```
Console shows a "Test Routing" button:

1. Console creates a test inbox: test-verify-{random}@company.com
2. Console sends a test email to that address from an external address
3. Waits up to 60 seconds for the email to arrive in AgentMail
4. If received: ✅ Routing is working!
5. If not received: ⚠ Routing may not be propagated yet. Try again in 24 hours.
```

### Verification Timeline

- **DNS changes (SPF, DKIM):** 15-60 minutes
- **Google Workspace routing rule propagation:** 24-48 hours
- **Total expected time:** 24-48 hours

### Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| Email to agent addresses stays in Google | Routing rule not propagated | Wait 48 hours. Check rule is enabled in Admin Console. |
| Email to agent addresses bounces | SPF/DKIM not configured | Ensure DKIM CNAMEs are added. Ensure SPF includes `amazonses.com`. |
| Email to regular users affected | Routing rule too broad | Check the regex pattern. Use group-based routing to be explicit about which addresses route to AgentMail. |
| Google rejects outbound from AgentMail | SPF check failure | The updated SPF record (`include:amazonses.com`) must be in place before AgentMail sends email. |
| "Too many SPF lookups" error | SPF record exceeds 10 DNS lookups | Google's `include:_spf.google.com` uses several lookups. Adding `amazonses.com` might push over the limit. Solution: use SPF flattening service or switch to subdomain approach. |
| DMARC failures on AgentMail-sent email | DKIM alignment | Ensure SES is signing with `d=company.com`. The DKIM CNAME records enable this. Check the outbound email headers for `DKIM-Signature: ... d=company.com`. |

---

## Flow 5: Transport Rule Routing (Microsoft 365)

**Use case:** Same as Flow 4, but with Microsoft 365 / Exchange Online instead of Google Workspace. Customer wants `agent@company.com` addresses on AgentMail while keeping human email on Microsoft 365.

### Prerequisites

- Customer has **Exchange Online admin access** (Exchange Administrator or Global Administrator role in Entra ID)
- Customer has DNS access to modify TXT and add CNAME records
- Customer understands this is more complex than the subdomain approach

### Step-by-Step Flow

**Steps 1-3:** Similar to Flow 4, but with `"existing_provider": "microsoft_365"`.

**Step 4: Console shows DNS changes AND Exchange Online instructions**

**Section A: DNS Changes**

```
Step 1: Update your SPF record

Your current SPF record on company.com is probably:
  v=spf1 include:spf.protection.outlook.com ~all

Change it to:
  v=spf1 include:spf.protection.outlook.com include:amazonses.com ~all

Step 2: Add DKIM CNAME records
  [Same 3 CNAME records as other flows]
```

**Section B: Exchange Online Connector + Transport Rule**

```
Step 3: Create an Outbound Connector in Exchange Admin Center

Option A: Exchange Admin Center (GUI)

1. Open Exchange Admin Center:
   https://admin.exchange.microsoft.com

2. Navigate to: Mail flow > Connectors

3. Click "Add a connector"

4. Connection from: "Office 365"
   Connection to: "Partner organization"

5. Connector name: "AgentMail Outbound Connector"
   Description: "Routes agent email addresses to AgentMail"

6. Use of connector:
   ○ Only when I have a transport rule set up that redirects
     messages to this connector
   (Select this option)

7. Routing:
   ○ Route email through these smart hosts
   Add: inbound-smtp.us-east-1.amazonaws.com

8. Security restrictions:
   ☑ Always use Transport Layer Security (TLS)
   ☑ Issued by a trusted certificate authority (CA)

9. Validation email:
   Enter: test@inbound-smtp.us-east-1.amazonaws.com
   Click "Validate" (this checks connectivity)

10. Review and click "Create connector"


Step 4: Create a Transport Rule

1. In Exchange Admin Center, navigate to:
   Mail flow > Rules

2. Click "Add a rule" > "Create a new rule"

3. Rule name: "Route AgentMail addresses"

4. Apply this rule if...
   "The recipient address includes..."
   Add each agent address:
   - support-bot@company.com
   - sales-ai@company.com

   OR use a distribution group:
   "The recipient is a member of..."
   Create a mail-enabled security group: "AgentMail Recipients"
   Add members: support-bot@company.com, sales-ai@company.com

5. Do the following...
   "Redirect the message to..."
   Select: "The following connector"
   Choose: "AgentMail Outbound Connector" (created in Step 3)

6. Except if...
   (Leave blank unless you need exceptions)

7. Rule mode: "Enforce"
   Severity: "Not specified"

8. Click "Save"


Step 5 (Alternative): PowerShell Setup

If you prefer PowerShell, connect to Exchange Online and run:

# Connect to Exchange Online
Connect-ExchangeOnline -UserPrincipalName admin@company.com

# Create the outbound connector
New-OutboundConnector `
  -Name "AgentMail Outbound Connector" `
  -RecipientDomains "company.com" `
  -SmartHosts "inbound-smtp.us-east-1.amazonaws.com" `
  -TlsSettings "CertificateValidation" `
  -UseMXRecord $false `
  -IsTransportRuleScoped $true `
  -Enabled $true

# Create the transport rule
New-TransportRule `
  -Name "Route AgentMail addresses" `
  -RecipientAddressContainsWords @("support-bot@company.com", "sales-ai@company.com") `
  -RouteMessageOutboundConnector "AgentMail Outbound Connector" `
  -Enabled $true

# Verify
Get-OutboundConnector -Identity "AgentMail Outbound Connector" | Format-List
Get-TransportRule -Identity "Route AgentMail addresses" | Format-List

# Disconnect
Disconnect-ExchangeOnline -Confirm:$false
```

**Step 5: Testing**

```
After the connector and transport rule are created:

1. Send an email from an external address to support-bot@company.com
2. Check AgentMail for the received email
3. If not received within 5 minutes, check:
   - Exchange Admin Center > Mail flow > Message trace
   - Look for the agent address and verify it was redirected
   - The connector status should show "Enabled"
   - The transport rule should show as "Active"
```

### Verification Timeline

- **DNS changes (SPF, DKIM):** 15-60 minutes
- **Exchange Online connector activation:** Usually within 30 minutes
- **Transport rule propagation:** Usually within 30 minutes
- **Total expected time:** 1-2 hours (faster than Google Workspace)

### Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| Email stays in Exchange mailbox | Transport rule not active or wrong scope | Check rule status in Exchange Admin Center. Ensure addresses match exactly. |
| Connector validation fails | Firewall or DNS issue | Ensure `inbound-smtp.us-east-1.amazonaws.com` is reachable on port 25 from Microsoft's IP ranges. |
| NDR (bounce) for agent addresses | Agent addresses exist as Exchange mailboxes | Remove or disable the mailbox in Exchange. If a mailbox exists, Exchange delivers locally before checking transport rules. |
| TLS handshake failure | Certificate mismatch | SES uses a valid Amazon-issued TLS certificate. Ensure the connector requires "Issued by a trusted certificate authority", not a specific certificate. |
| Duplicate delivery (both Exchange and AgentMail) | Mailbox exists AND transport rule routes | The agent address must NOT have an active Exchange mailbox. Remove the mailbox or convert it to a mail-enabled contact. |
| SPF failures on outbound | SPF not updated | Confirm `include:amazonses.com` is in the SPF record. Run `nslookup -type=txt company.com` to verify. |
| PowerShell connection fails | MFA or Conditional Access | Use `Connect-ExchangeOnline` with the `-Device` flag for device-code authentication, or use an app password. |

---

## Flow 6: Outbound-Only Domain

**Use case:** The customer only wants to SEND email from their domain addresses. They do not want to receive email through AgentMail -- their existing provider handles all inbound. This is the simplest setup because no MX records are changed.

**Example:** Customer wants their AI agent to send emails as `notifications@company.com` but does not need to receive replies at that address (or replies go to their existing email system).

### Prerequisites

- Customer has DNS access to add TXT and CNAME records
- Customer does NOT need admin access to any email provider
- Customer understands that replies to emails sent from AgentMail will route to their existing MX (Google/MS/etc.), NOT to AgentMail

### Step-by-Step Flow

**Step 1: User selects outbound-only mode**

```
Domain name: [company.com___________________]
Setup mode:
  ( ) Full setup (send and receive)
  ( ) Subdomain (send and receive on subdomain)
  (x) Outbound only (send from @company.com, receive elsewhere)
      
      Replies to emails sent from AgentMail will go to your
      existing email provider (Google Workspace, Microsoft 365, etc.)
```

**Step 2: API call**

```
POST /v1/domains
{
  "domain": "company.com",
  "mode": "outbound_only",
  "existing_provider": "google_workspace",
  "receive_email": false,
  "send_email": true
}
```

**Step 3: API returns DNS records (no MX)**

```json
{
  "domain_id": "dom_06JKL...",
  "domain": "company.com",
  "mode": "outbound_only",
  "status": "pending_verification",
  "dns_records": [
    {
      "type": "TXT",
      "name": "company.com",
      "value": "v=spf1 include:_spf.google.com include:amazonses.com ~all",
      "purpose": "Updated SPF -- adds AgentMail as authorized sender",
      "required": true,
      "status": "pending",
      "note": "Add 'include:amazonses.com' to your EXISTING SPF record."
    },
    {
      "type": "CNAME",
      "name": "abc123._domainkey.company.com",
      "value": "abc123.dkim.amazonses.com",
      "purpose": "DKIM signature key 1 of 3",
      "required": true,
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "def456._domainkey.company.com",
      "value": "def456.dkim.amazonses.com",
      "purpose": "DKIM signature key 2 of 3",
      "required": true,
      "status": "pending"
    },
    {
      "type": "CNAME",
      "name": "ghi789._domainkey.company.com",
      "value": "ghi789.dkim.amazonses.com",
      "purpose": "DKIM signature key 3 of 3",
      "required": true,
      "status": "pending"
    }
  ],
  "notes": [
    "No MX record change required for outbound-only mode.",
    "Replies to emails sent from AgentMail will be delivered to your existing email provider.",
    "Inboxes created on this domain can SEND email but will NOT receive inbound email through AgentMail."
  ]
}
```

**Step 4: DNS setup (simplest of all flows)**

Only 4 records to add/modify:
1. Modify existing SPF to include `amazonses.com`
2. Add 3 DKIM CNAME records

No MX change. No routing rules. No admin console access needed.

**Step 5: Verification**

The domain-verification-poller checks SPF and DKIM only (no MX check for outbound-only domains):

```python
def verify_outbound_only_domain(domain_record):
    domain = domain_record['domain']
    
    # Check SPF
    spf_verified = check_spf_includes(domain, 'amazonses.com')
    
    # Check DKIM via SES API
    ses_identity = ses_client.get_email_identity(EmailIdentity=domain)
    dkim_verified = ses_identity['DkimAttributes']['Status'] == 'SUCCESS'
    
    return spf_verified and dkim_verified
```

**Step 6: Using the domain**

After verification, inboxes on this domain can send but not receive:

```
POST /v1/inboxes
{
  "email": "notifications@company.com",
  "display_name": "Notification Bot",
  "capabilities": ["send"]  // receive is disabled for outbound-only domains
}

POST /v1/inboxes/inbox_abc123/messages
{
  "to": ["customer@example.com"],
  "subject": "Your order has shipped",
  "body_text": "Your order #12345 has been shipped..."
}
```

Attempting to check for inbound messages will return an empty list with a note:

```json
{
  "messages": [],
  "note": "This inbox is on an outbound-only domain. Inbound email is handled by your existing email provider."
}
```

### DNS Records Summary (Outbound-Only)

| Type | Name | Value | Required | Notes |
|------|------|-------|----------|-------|
| TXT | `company.com` | `v=spf1 ... include:amazonses.com ~all` | Yes | MODIFY existing record |
| CNAME | `{token}._domainkey.company.com` (x3) | `{token}.dkim.amazonses.com` | Yes | New records |

No MX record changes.

### Verification Timeline

- **SPF record update:** 15-30 minutes
- **DKIM CNAME propagation:** 15-60 minutes
- **SES DKIM verification:** Usually within 1 hour after DNS propagation
- **Total expected time:** 30 minutes to 2 hours

### Troubleshooting

| Issue | Cause | Resolution |
|-------|-------|------------|
| SES rejects send request | DKIM not yet verified by SES | Wait for SES to verify DKIM. Check SES console > Verified identities. |
| Email goes to spam | SPF not updated | Verify `amazonses.com` is in the SPF record. Check with: `dig TXT company.com` |
| Replies not appearing in AgentMail | Expected behavior for outbound-only | Replies go to existing provider's MX. Switch to subdomain or transport rule mode if reply handling is needed. |
| "Sender identity not verified" error | SES identity not in verified state | Check SES console. The domain must show "Verified" status. |

---

## Common DNS Provider Guides

### Cloudflare

1. Log in to Cloudflare Dashboard
2. Select the domain
3. Go to DNS > Records
4. Click "Add record"
5. Select record type (MX, TXT, CNAME)
6. For CNAME records: enter only the subdomain part (Cloudflare auto-appends the domain)
   - Name: `abc123._domainkey` (not the full `abc123._domainkey.company.com`)
   - Target: `abc123.dkim.amazonses.com`
7. For MX records: Cloudflare has a separate Priority field
   - Name: `@` (or subdomain like `agents`)
   - Mail server: `inbound-smtp.us-east-1.amazonaws.com`
   - Priority: `10`
8. **Important:** Set proxy status to "DNS only" (gray cloud) for MX and CNAME records. Cloudflare's HTTP proxy breaks email routing.
9. TTL: Auto (or 3600)

### AWS Route 53

1. Open Route 53 Console
2. Go to Hosted zones > select domain
3. Click "Create record"
4. For simple routing:
   - Record name: leave blank for apex, or enter subdomain
   - Record type: MX, TXT, or CNAME
   - Value: enter the full value
5. For MX records: enter as `10 inbound-smtp.us-east-1.amazonaws.com`
6. TTL: 300 (Route 53 default) or 3600
7. Routing policy: Simple routing

**Route 53 bonus:** If the customer uses Route 53, AgentMail can potentially auto-configure DNS records using the Route 53 API (future feature, requires customer granting cross-account IAM role).

### GoDaddy

1. Log in to GoDaddy
2. Go to My Products > DNS > Manage
3. Click "Add" under the appropriate record type section
4. For CNAME records:
   - Host: `abc123._domainkey` (GoDaddy auto-appends the domain)
   - Points to: `abc123.dkim.amazonses.com`
   - TTL: 1 Hour
5. For MX records:
   - Host: `@` (or subdomain)
   - Points to: `inbound-smtp.us-east-1.amazonaws.com`
   - Priority: `10`
   - TTL: 1 Hour
6. For TXT records:
   - Host: `@` (or subdomain)
   - TXT Value: paste the full value
   - TTL: 1 Hour

**GoDaddy caveat:** GoDaddy sometimes adds a trailing period to CNAME targets. This is correct DNS behavior but can look confusing in their UI.

### Namecheap

1. Log in to Namecheap
2. Go to Domain List > Manage > Advanced DNS
3. Click "Add New Record"
4. For CNAME records:
   - Type: CNAME Record
   - Host: `abc123._domainkey` (Namecheap auto-appends domain)
   - Value: `abc123.dkim.amazonses.com`
   - TTL: Automatic
5. For MX records:
   - Type: MX Record
   - Host: `@` (or subdomain)
   - Value: `inbound-smtp.us-east-1.amazonaws.com`
   - Priority: `10`
   - TTL: Automatic
6. For TXT records:
   - Type: TXT Record
   - Host: `@` (or subdomain)
   - Value: paste the full value (no quotes needed -- Namecheap adds them)
   - TTL: Automatic

### Google Domains / Google Cloud DNS

1. Go to Google Domains > DNS or Google Cloud Console > Cloud DNS
2. For Google Domains: Manage > DNS > Custom records
3. Click "Create new record"
4. For CNAME records:
   - Host name: `abc123._domainkey.company.com` (enter full name in Google Cloud DNS) or just `abc123._domainkey` (in Google Domains)
   - Type: CNAME
   - Data: `abc123.dkim.amazonses.com.` (trailing period required in Cloud DNS)
   - TTL: 3600
5. Similar for MX and TXT records

---

## Troubleshooting

### Universal Troubleshooting Steps

**DNS not propagating:**
1. Check that you are editing DNS at the authoritative nameserver (not a cached copy)
2. Use an external DNS checker: `dig +trace MX company.com @8.8.8.8`
3. Clear your local DNS cache: `sudo dscacheutil -flushcache` (macOS) or `ipconfig /flushdns` (Windows)
4. Wait. Some registrars take up to 48 hours for DNS propagation, though most are under 1 hour.

**SPF record too long (> 10 DNS lookups):**
The SPF RFC limits the number of DNS lookups to 10. A typical Google Workspace SPF record uses 4-5 lookups. Adding `amazonses.com` adds 1-2 more. If you are near the limit:
1. Use an SPF flattening service (e.g., dmarcian, AutoSPF)
2. Or use the subdomain approach (separate SPF on the subdomain avoids the apex SPF entirely)

**Multiple SPF records:**
Only ONE TXT record starting with `v=spf1` is allowed per domain. If you have multiple, email authentication will fail. Merge them into one record.

**DKIM key rotation:**
SES rotates DKIM keys automatically with Easy DKIM. The CNAME records point to SES-managed keys, and SES handles rotation transparently. No customer action needed after initial setup.

**SES sandbox mode:**
New SES identities start in sandbox mode. AgentMail's production SES account is already out of sandbox, so customer domains added through AgentMail are automatically in production mode. However, new SES identities may have initial sending limits that ramp up over time.

### Verification Status API

Customers can check verification status programmatically:

```
GET /v1/domains/{domain_id}
Authorization: Bearer <api_key>
```

Response:
```json
{
  "domain_id": "dom_abc123",
  "domain": "agents.company.com",
  "mode": "subdomain",
  "status": "pending_verification",
  "dns_records": [
    {"type": "MX", "status": "verified", "verified_at": "2026-04-10T14:15:00Z"},
    {"type": "TXT", "status": "verified", "verified_at": "2026-04-10T14:15:00Z"},
    {"type": "CNAME", "name": "abc123._domainkey...", "status": "pending"},
    {"type": "CNAME", "name": "def456._domainkey...", "status": "pending"},
    {"type": "CNAME", "name": "ghi789._domainkey...", "status": "verified", "verified_at": "2026-04-10T14:20:00Z"},
    {"type": "TXT", "name": "_dmarc...", "status": "pending"}
  ],
  "created_at": "2026-04-10T14:00:00Z",
  "last_checked_at": "2026-04-10T14:20:00Z",
  "next_check_at": "2026-04-10T14:25:00Z"
}
```

### Webhook Events for Domain Lifecycle

| Event | Fired When | Payload |
|-------|-----------|---------|
| `domain.created` | Domain added via API | `{domain_id, domain, mode}` |
| `domain.record_verified` | Individual DNS record verified | `{domain_id, domain, record_type, record_name}` |
| `domain.verified` | All required DNS records verified | `{domain_id, domain, verified_at}` |
| `domain.verification_failed` | Domain pending > 7 days, reminder sent | `{domain_id, domain, days_pending, missing_records}` |
| `domain.deleted` | Domain removed from org | `{domain_id, domain}` |
| `domain.inactive` | DNS records removed/changed, domain no longer functional | `{domain_id, domain, failed_records}` |
