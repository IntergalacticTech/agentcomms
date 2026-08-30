# Custom Domain Architecture

## Overview

Custom domains are a core feature of AgentMail. Instead of sending from `inbox_xxx@agentmail.dev`, customers can send and receive from their own domain: `support@acme.com`. This requires domain ownership verification, DNS record configuration, and ongoing monitoring. AgentMail handles the entire lifecycle through the SES v2 API, with optional automation for customers using Route 53.

---

## Table of Contents

- [Domain Verification Workflow](#domain-verification-workflow)
- [SES CreateEmailIdentity API](#ses-createemailidentity-api)
- [DNS Records Required](#dns-records-required)
- [Polling for Verification Status](#polling-for-verification-status)
- [Route 53 Auto-Setup](#route-53-auto-setup)
- [DKIM Key Rotation Strategy](#dkim-key-rotation-strategy)
- [Zone File Generation](#zone-file-generation)
- [Domain Status State Machine](#domain-status-state-machine)

---

## Domain Verification Workflow

### Step-by-Step Flow

```
Step 1: Customer calls POST /v1/domains
        Body: {"domain": "acme.com"}

Step 2: API Lambda:
        a. Validate domain format
        b. Check domain not already claimed by another org (GSI6)
        c. Call SES CreateEmailIdentity
        d. Store domain record in DynamoDB (status: "pending")
        e. Return DNS records to customer

Step 3: Customer adds DNS records at their DNS provider

Step 4: Scheduled Lambda polls GetEmailIdentity every 5 minutes
        for all domains in "pending" or "verifying" status

Step 5: SES confirms DKIM verification
        → Update status to "dkim_verified"

Step 6: Platform verifies MX record points to SES inbound
        → Update status to "verified"

Step 7: Fire domain.verified event to Kinesis
        Customer can now send and receive on this domain
```

### API Endpoint: Create Domain

```python
"""
Lambda: domains-create
Triggered by: API Gateway POST /v1/domains
"""

import json
import uuid
import time
import re
import boto3
from boto3.dynamodb.conditions import Key

ses_v2 = boto3.client('sesv2', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
kinesis = boto3.client('kinesis', region_name='us-east-1')

TABLE_NAME = 'agentmail'
KINESIS_STREAM = 'agentmail-events'
INBOUND_REGION = 'us-east-1'


def handler(event, context):
    body = json.loads(event['body'])
    org_id = event['requestContext']['authorizer']['org_id']
    domain = body['domain'].lower().strip()

    # ── Validation ───────────────────────────────────────────────────

    # Validate domain format
    if not re.match(r'^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$', domain):
        return _response(400, {'error': 'Invalid domain format'})

    # Block reserved/platform domains
    if domain in ('agentmail.dev', 'agentmail.com', 'agentmail.io'):
        return _response(400, {'error': 'This domain is reserved'})

    # Check domain not already claimed (GSI6)
    table = dynamodb.Table(TABLE_NAME)
    existing = table.query(
        IndexName='GSI6',
        KeyConditionExpression=Key('GSI6_PK').eq(f'DOMAIN#{domain}'),
        Limit=1
    )
    if existing['Items']:
        return _response(409, {'error': 'Domain already registered'})

    # ── Create SES Email Identity ────────────────────────────────────

    domain_id = f'dom_{uuid.uuid4().hex[:20]}'

    try:
        ses_response = ses_v2.create_email_identity(
            EmailIdentity=domain,
            DkimSigningAttributes={
                'DomainSigningSelector': 'agentmail',
                'NextSigningKeyLength': 'RSA_2048_BIT'
            },
            ConfigurationSetName=f'agentmail-{org_id}',
            Tags=[
                {'Key': 'org_id', 'Value': org_id},
                {'Key': 'domain_id', 'Value': domain_id},
                {'Key': 'managed_by', 'Value': 'agentmail'}
            ]
        )
    except ses_v2.exceptions.AlreadyExistsException:
        # Domain already exists in SES (maybe from a previous attempt)
        ses_response = ses_v2.get_email_identity(EmailIdentity=domain)
    except ses_v2.exceptions.LimitExceededException:
        return _response(429, {'error': 'SES identity limit reached, contact support'})

    # ── Extract DKIM tokens ──────────────────────────────────────────

    dkim_attributes = ses_response.get('DkimAttributes', {})
    dkim_tokens = dkim_attributes.get('Tokens', [])
    dkim_signing_attributes = dkim_attributes.get('SigningAttributesOrigin', 'AWS_SES')

    # ── Build DNS records for customer ───────────────────────────────

    dns_records = _build_dns_records(domain, dkim_tokens)

    # ── Store domain record in DynamoDB ──────────────────────────────

    now_ms = int(time.time() * 1000)
    domain_item = {
        'PK': f'ORG#{org_id}',
        'SK': f'DOM#{domain_id}',
        'domain_id': domain_id,
        'org_id': org_id,
        'domain_name': domain,
        'status': 'pending',
        'dkim_tokens': dkim_tokens,
        'dkim_status': 'PENDING',
        'spf_status': 'pending',
        'mx_status': 'pending',
        'dmarc_status': 'pending',
        'dns_records': dns_records,
        'created_at': now_ms,
        'updated_at': now_ms,
        'verification_started_at': now_ms,

        # GSI6: domain name → org lookup (for inbound routing and uniqueness)
        'GSI6_PK': f'DOMAIN#{domain}',
        'GSI6_SK': f'ORG#{org_id}',
    }

    table.put_item(Item=domain_item)

    # ── Return response ──────────────────────────────────────────────

    return _response(201, {
        'id': domain_id,
        'domain': domain,
        'status': 'pending',
        'dns_records': dns_records,
        'instructions': (
            'Add the following DNS records to your domain to complete verification. '
            'DKIM verification typically completes within 1-72 hours after records are added.'
        )
    })


def _build_dns_records(domain: str, dkim_tokens: list[str]) -> list[dict]:
    """Build the complete list of DNS records the customer needs to add."""
    records = []

    # ── DKIM records (3 CNAME records) ───────────────────────────────
    for token in dkim_tokens:
        records.append({
            'type': 'CNAME',
            'name': f'{token}._domainkey.{domain}',
            'value': f'{token}.dkim.amazonses.com',
            'purpose': 'DKIM signature verification',
            'required': True
        })

    # ── SPF record ───────────────────────────────────────────────────
    records.append({
        'type': 'TXT',
        'name': domain,
        'value': 'v=spf1 include:amazonses.com ~all',
        'purpose': 'SPF authorization for SES to send on behalf of this domain',
        'required': True,
        'note': (
            'If you already have an SPF record, add "include:amazonses.com" '
            'to your existing record instead of creating a new one. '
            'Example: "v=spf1 include:_spf.google.com include:amazonses.com ~all"'
        )
    })

    # ── DMARC record ─────────────────────────────────────────────────
    records.append({
        'type': 'TXT',
        'name': f'_dmarc.{domain}',
        'value': 'v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.dev; pct=100',
        'purpose': 'DMARC policy for domain authentication',
        'required': True,
        'note': (
            'If you already have a DMARC record, you do not need to change it. '
            'If not, we recommend starting with p=quarantine and moving to p=reject '
            'once you confirm all legitimate email passes DKIM/SPF.'
        )
    })

    # ── MX record (for inbound receiving) ────────────────────────────
    records.append({
        'type': 'MX',
        'name': domain,
        'value': f'10 inbound-smtp.{INBOUND_REGION}.amazonaws.com',
        'purpose': 'Route inbound email to AgentMail via SES',
        'required': True,  # Required for inbound; optional if send-only
        'note': (
            'This record directs incoming email to AgentMail. '
            'If you want to receive email on this domain through AgentMail, this is required. '
            'If you only want to send from this domain, you can skip this record. '
            'WARNING: Adding this MX record will redirect ALL email for this domain to AgentMail. '
            'If you have existing mailboxes (Gmail, Outlook, etc.), do not add this record '
            'unless you want to migrate all inbound email to AgentMail.'
        )
    })

    # ── Verification TXT record ──────────────────────────────────────
    # SES Easy DKIM doesn't require a separate verification TXT record
    # (verification is done through DKIM CNAME records).
    # But we add an ownership verification TXT for our own tracking.
    records.append({
        'type': 'TXT',
        'name': f'_agentmail.{domain}',
        'value': f'agentmail-verify=true',
        'purpose': 'AgentMail domain ownership verification',
        'required': False,
        'note': 'Optional. Helps us verify domain ownership independently of SES.'
    })

    return records
```

---

## SES CreateEmailIdentity API

### Easy DKIM (Default)

Easy DKIM is the recommended approach. SES generates the DKIM keys and provides three CNAME records for DNS configuration. SES manages key rotation automatically.

```python
# Easy DKIM with AWS-managed keys
response = ses_v2.create_email_identity(
    EmailIdentity='acme.com',
    DkimSigningAttributes={
        'NextSigningKeyLength': 'RSA_2048_BIT'  # or 'RSA_1024_BIT'
    },
    Tags=[
        {'Key': 'org_id', 'Value': 'org_xxx'},
        {'Key': 'managed_by', 'Value': 'agentmail'}
    ]
)

# Response:
{
    'IdentityType': 'DOMAIN',
    'VerifiedForSendingStatus': False,
    'DkimAttributes': {
        'SigningEnabled': True,
        'Status': 'PENDING',       # Will change to SUCCESS after DNS propagation
        'Tokens': [
            'token1abc',           # Use to build CNAME records
            'token2def',
            'token3ghi'
        ],
        'SigningAttributesOrigin': 'AWS_SES',
        'NextSigningKeyLength': 'RSA_2048_BIT',
        'CurrentSigningKeyLength': 'RSA_2048_BIT'
    }
}
```

**CNAME records generated from tokens:**

```dns
token1abc._domainkey.acme.com.  CNAME  token1abc.dkim.amazonses.com.
token2def._domainkey.acme.com.  CNAME  token2def.dkim.amazonses.com.
token3ghi._domainkey.acme.com.  CNAME  token3ghi.dkim.amazonses.com.
```

### BYODKIM (Bring Your Own DKIM)

For enterprise customers who want to control their own DKIM keys (for compliance, key management, or multi-provider scenarios):

```python
# BYODKIM with customer-provided keys
import cryptography
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

# Generate RSA 2048-bit key pair
private_key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048
)

private_key_pem = private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption()
).decode('utf-8')

public_key_pem = private_key.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode('utf-8')

# Create SES identity with BYODKIM
response = ses_v2.create_email_identity(
    EmailIdentity='acme.com',
    DkimSigningAttributes={
        'DomainSigningSelector': 'agentmail',       # The DKIM selector
        'DomainSigningPrivateKey': private_key_pem   # RSA private key
    }
)

# Customer adds a single TXT record:
# agentmail._domainkey.acme.com.  TXT  "v=DKIM1; k=rsa; p=<base64-public-key>"
```

**BYODKIM advantages:**
- Same DKIM key across all SES regions (no per-region CNAME records)
- Full control over key rotation schedule
- Key stored in customer's HSM or KMS if desired

**BYODKIM disadvantages:**
- Customer responsible for key rotation
- Must regenerate and distribute new keys manually
- Private key must be provided to SES (cannot use HSM-stored keys directly)

### Comparison

| Feature | Easy DKIM | BYODKIM |
|---|---|---|
| Key generation | AWS-managed | Customer-managed |
| DNS records | 3 CNAMEs | 1 TXT per selector |
| Key rotation | Automatic (by AWS) | Manual |
| Multi-region | Per-region CNAME records | Same key works everywhere |
| Key length | 1024 or 2048-bit RSA | 1024 or 2048-bit RSA |
| Setup complexity | Lower | Higher |
| Recommended for | Most customers | Enterprise / compliance |

---

## DNS Records Required

### Complete Record Set

A fully configured custom domain requires up to 6 DNS records:

```dns
; ═══════════════════════════════════════════════════════════════════
; DKIM Records (3 CNAME records -- required for sending)
; These allow SES to sign outbound email with a DKIM signature
; that receiving mail servers can verify.
; ═══════════════════════════════════════════════════════════════════

token1abc._domainkey.acme.com.  IN  CNAME  token1abc.dkim.amazonses.com.
token2def._domainkey.acme.com.  IN  CNAME  token2def.dkim.amazonses.com.
token3ghi._domainkey.acme.com.  IN  CNAME  token3ghi.dkim.amazonses.com.

; ═══════════════════════════════════════════════════════════════════
; SPF Record (1 TXT record -- required for sending)
; Authorizes SES to send email on behalf of this domain.
; If a TXT record already exists for the domain, MERGE the
; include:amazonses.com into the existing record.
; ═══════════════════════════════════════════════════════════════════

acme.com.  IN  TXT  "v=spf1 include:amazonses.com ~all"

; If customer already has Google Workspace:
; acme.com.  IN  TXT  "v=spf1 include:_spf.google.com include:amazonses.com ~all"

; ═══════════════════════════════════════════════════════════════════
; DMARC Record (1 TXT record -- strongly recommended)
; Tells receiving servers what to do when SPF/DKIM fails.
; Also provides aggregate reports for monitoring.
; ═══════════════════════════════════════════════════════════════════

_dmarc.acme.com.  IN  TXT  "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.dev; pct=100"

; Recommended progression:
; Week 1-4:  p=none      (monitor only, no enforcement)
; Week 5-8:  p=quarantine (suspicious mail goes to spam)
; Week 9+:   p=reject     (fail messages that don't pass)

; ═══════════════════════════════════════════════════════════════════
; MX Record (1 MX record -- required for receiving)
; Routes inbound email to SES for processing by AgentMail.
;
; WARNING: This replaces any existing MX records.
; If the domain has existing mailboxes (Gmail, Outlook), adding
; this record will break their mail delivery.
; ═══════════════════════════════════════════════════════════════════

acme.com.  IN  MX  10  inbound-smtp.us-east-1.amazonaws.com.

; ═══════════════════════════════════════════════════════════════════
; Verification TXT (1 TXT record -- optional, for AgentMail tracking)
; ═══════════════════════════════════════════════════════════════════

_agentmail.acme.com.  IN  TXT  "agentmail-verify=true"
```

### DNS Record Validation

```python
import dns.resolver

def validate_dns_records(domain: str, expected_records: list[dict]) -> dict:
    """
    Validate that all required DNS records are properly configured.

    Returns status for each record type.
    """
    results = {
        'dkim': {'status': 'missing', 'details': []},
        'spf': {'status': 'missing', 'details': ''},
        'dmarc': {'status': 'missing', 'details': ''},
        'mx': {'status': 'missing', 'details': ''},
    }

    # ── Check DKIM CNAMEs ────────────────────────────────────────────
    dkim_records = [r for r in expected_records if r['type'] == 'CNAME']
    dkim_verified = 0
    for record in dkim_records:
        try:
            answers = dns.resolver.resolve(record['name'], 'CNAME')
            for rdata in answers:
                if record['value'].rstrip('.') in str(rdata.target).rstrip('.'):
                    dkim_verified += 1
                    results['dkim']['details'].append(
                        f'{record["name"]}: OK'
                    )
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            results['dkim']['details'].append(f'{record["name"]}: NOT FOUND')

    if dkim_verified == len(dkim_records):
        results['dkim']['status'] = 'verified'
    elif dkim_verified > 0:
        results['dkim']['status'] = 'partial'

    # ── Check SPF TXT ────────────────────────────────────────────────
    try:
        answers = dns.resolver.resolve(domain, 'TXT')
        for rdata in answers:
            txt_value = str(rdata).strip('"')
            if 'v=spf1' in txt_value:
                if 'include:amazonses.com' in txt_value:
                    results['spf'] = {'status': 'verified', 'details': txt_value}
                else:
                    results['spf'] = {
                        'status': 'incomplete',
                        'details': f'SPF record found but missing amazonses.com include: {txt_value}'
                    }
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        pass

    # ── Check DMARC TXT ──────────────────────────────────────────────
    try:
        answers = dns.resolver.resolve(f'_dmarc.{domain}', 'TXT')
        for rdata in answers:
            txt_value = str(rdata).strip('"')
            if 'v=DMARC1' in txt_value:
                results['dmarc'] = {'status': 'verified', 'details': txt_value}
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        pass

    # ── Check MX ─────────────────────────────────────────────────────
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        for rdata in answers:
            if 'inbound-smtp' in str(rdata.exchange) and 'amazonaws.com' in str(rdata.exchange):
                results['mx'] = {
                    'status': 'verified',
                    'details': f'{rdata.preference} {rdata.exchange}'
                }
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        pass

    return results
```

---

## Polling for Verification Status

A scheduled Lambda runs every 5 minutes to check the verification status of all pending domains.

### Verification Poller

```python
"""
Lambda: domain-verification-poller
Triggered by: EventBridge rule (every 5 minutes)
"""

import json
import time
import boto3
from boto3.dynamodb.conditions import Attr

ses_v2 = boto3.client('sesv2', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
kinesis = boto3.client('kinesis', region_name='us-east-1')

TABLE_NAME = 'agentmail'
KINESIS_STREAM = 'agentmail-events'
VERIFICATION_TIMEOUT_HOURS = 72  # Give up after 72 hours


def handler(event, context):
    table = dynamodb.Table(TABLE_NAME)
    now_ms = int(time.time() * 1000)
    timeout_ms = VERIFICATION_TIMEOUT_HOURS * 60 * 60 * 1000

    # Scan for all domains in pending/verifying status
    # In production, use a GSI on status or a DynamoDB stream trigger
    response = table.scan(
        FilterExpression=(
            Attr('status').is_in(['pending', 'verifying']) &
            Attr('SK').begins_with('DOM#')
        ),
        ProjectionExpression=(
            'PK, SK, domain_id, org_id, domain_name, #s, '
            'dkim_tokens, verification_started_at, dns_records'
        ),
        ExpressionAttributeNames={'#s': 'status'}
    )

    for domain_item in response['Items']:
        domain_name = domain_item['domain_name']
        domain_id = domain_item['domain_id']
        org_id = domain_item['org_id']
        started_at = domain_item.get('verification_started_at', now_ms)

        # Check for timeout
        if (now_ms - started_at) > timeout_ms:
            _update_domain_status(table, domain_item, 'failed', {
                'failure_reason': 'verification_timeout',
                'message': f'DNS records not detected within {VERIFICATION_TIMEOUT_HOURS} hours'
            })
            _publish_event('domain.verification_failed', org_id, domain_id, domain_name)
            continue

        try:
            # ── Query SES for current identity status ────────────────
            ses_identity = ses_v2.get_email_identity(EmailIdentity=domain_name)

            dkim_status = ses_identity['DkimAttributes']['Status']
            # Possible: 'PENDING', 'SUCCESS', 'FAILED', 'TEMPORARY_FAILURE', 'NOT_STARTED'

            verified_for_sending = ses_identity.get('VerifiedForSendingStatus', False)

            # ── Update DKIM status ───────────────────────────────────
            updates = {
                'dkim_status': dkim_status,
                'verified_for_sending': verified_for_sending,
            }

            if dkim_status == 'SUCCESS':
                updates['dkim_verified_at'] = now_ms

                # ── Now check other DNS records ──────────────────────
                dns_results = validate_dns_records(
                    domain_name,
                    domain_item.get('dns_records', [])
                )

                updates['spf_status'] = dns_results['spf']['status']
                updates['mx_status'] = dns_results['mx']['status']
                updates['dmarc_status'] = dns_results['dmarc']['status']

                # Determine overall status
                if (dns_results['mx']['status'] == 'verified' and
                    dns_results['spf']['status'] == 'verified'):
                    # Fully verified -- ready for sending and receiving
                    _update_domain_status(table, domain_item, 'verified', updates)
                    _add_inbound_receipt_rule(domain_name, org_id)
                    _publish_event('domain.verified', org_id, domain_id, domain_name)
                elif dns_results['spf']['status'] == 'verified':
                    # DKIM + SPF verified, but no MX -- can send but not receive
                    updates['note'] = 'Domain verified for sending. Add MX record to enable receiving.'
                    _update_domain_status(table, domain_item, 'verified_send_only', updates)
                    _publish_event('domain.verified', org_id, domain_id, domain_name)
                else:
                    # DKIM verified but other records still pending
                    _update_domain_status(table, domain_item, 'verifying', updates)

            elif dkim_status == 'FAILED':
                _update_domain_status(table, domain_item, 'failed', {
                    'failure_reason': 'dkim_verification_failed',
                    'message': 'DKIM verification failed. Check that CNAME records are correct.'
                })
                _publish_event('domain.verification_failed', org_id, domain_id, domain_name)

            elif dkim_status == 'TEMPORARY_FAILURE':
                # SES will retry -- just update status and continue polling
                _update_domain_status(table, domain_item, 'verifying', {
                    'dkim_status': dkim_status,
                    'note': 'DKIM verification in progress, SES is retrying'
                })

            else:
                # Still PENDING -- update status to verifying if it was pending
                if domain_item['status'] == 'pending':
                    _update_domain_status(table, domain_item, 'verifying', updates)

        except ses_v2.exceptions.NotFoundException:
            # Identity was deleted from SES -- mark as failed
            _update_domain_status(table, domain_item, 'failed', {
                'failure_reason': 'identity_not_found',
                'message': 'SES email identity not found. Domain may have been deleted.'
            })

        except Exception as e:
            logger.error(f'Error checking domain {domain_name}: {e}')
            # Don't update status on transient errors -- will retry next poll


def _update_domain_status(table, domain_item, new_status, extra_attrs=None):
    """Update domain status and attributes in DynamoDB."""
    now_ms = int(time.time() * 1000)

    update_expr = 'SET #status = :status, updated_at = :now'
    expr_values = {':status': new_status, ':now': now_ms}
    expr_names = {'#status': 'status'}

    if extra_attrs:
        for key, value in extra_attrs.items():
            safe_key = key.replace('#', '_')  # Avoid DynamoDB reserved words
            update_expr += f', {key} = :{safe_key}'
            expr_values[f':{safe_key}'] = value

    if new_status == 'verified':
        update_expr += ', verified_at = :verified_at'
        expr_values[':verified_at'] = now_ms

    table.update_item(
        Key={'PK': domain_item['PK'], 'SK': domain_item['SK']},
        UpdateExpression=update_expr,
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values
    )


def _add_inbound_receipt_rule(domain: str, org_id: str):
    """Add a SES receipt rule for the newly verified domain."""
    ses_v1 = boto3.client('ses', region_name='us-east-1')

    try:
        ses_v1.create_receipt_rule(
            RuleSetName='agentmail-inbound',
            Rule={
                'Name': f'domain-{domain.replace(".", "-")}',
                'Enabled': True,
                'TlsPolicy': 'Optional',
                'Recipients': [domain],
                'Actions': [
                    {
                        'S3Action': {
                            'BucketName': 'agentmail-raw-email',
                            'ObjectKeyPrefix': 'inbound/',
                            'KmsKeyArn': 'arn:aws:kms:us-east-1:123456789012:key/xxx'
                        }
                    },
                    {
                        'LambdaAction': {
                            'FunctionArn': (
                                'arn:aws:lambda:us-east-1:123456789012:'
                                'function:inbound-router'
                            ),
                            'InvocationType': 'Event'
                        }
                    }
                ],
                'ScanEnabled': True
            }
        )
    except Exception as e:
        logger.error(f'Failed to create receipt rule for {domain}: {e}')
        # Non-fatal: receipt rule can be retried or handled manually


def _publish_event(event_type, org_id, domain_id, domain_name):
    """Publish domain event to Kinesis."""
    kinesis.put_record(
        StreamName=KINESIS_STREAM,
        Data=json.dumps({
            'eventId': f'evt_{domain_id}_{int(time.time())}',
            'eventType': event_type,
            'timestamp': int(time.time() * 1000),
            'orgId': org_id,
            'data': {
                'domainId': domain_id,
                'domain': domain_name
            }
        }),
        PartitionKey=org_id
    )
```

### Verification Timeline

| Step | Typical Time | Maximum Time |
|---|---|---|
| SES CreateEmailIdentity → DKIM tokens available | Immediate | Immediate |
| Customer adds DNS records | Minutes to hours | Depends on customer |
| DNS propagation | 5 minutes - 24 hours | 72 hours |
| SES detects DKIM CNAMEs | 5 minutes - 1 hour | 72 hours |
| Our poller detects SES verification | Up to 5 minutes | 5 minutes (poll interval) |
| SPF/MX/DMARC validation | Immediate after poll | Same |
| **Total (typical)** | **30 minutes - 2 hours** | **72 hours** |

---

## Route 53 Auto-Setup

For customers whose domains are hosted on Route 53, we can automatically create all required DNS records, eliminating manual configuration.

### Detection and Auto-Setup Flow

```python
"""
Optional: Auto-setup DNS records for Route 53-hosted domains
Called after POST /v1/domains if customer opts in
"""

import boto3

route53 = boto3.client('route53', region_name='us-east-1')


def auto_setup_route53(domain: str, dns_records: list[dict], org_id: str) -> dict:
    """
    Automatically configure DNS records in Route 53.

    Returns: {'success': bool, 'hosted_zone_id': str, 'records_created': int}
    """

    # ── Step 1: Find the hosted zone for this domain ─────────────────
    hosted_zone_id = _find_hosted_zone(domain)
    if not hosted_zone_id:
        return {
            'success': False,
            'error': 'No Route 53 hosted zone found for this domain'
        }

    # ── Step 2: Build change batch ───────────────────────────────────
    changes = []

    for record in dns_records:
        if record['type'] == 'CNAME':
            changes.append({
                'Action': 'UPSERT',
                'ResourceRecordSet': {
                    'Name': record['name'],
                    'Type': 'CNAME',
                    'TTL': 300,
                    'ResourceRecords': [{'Value': record['value']}]
                }
            })
        elif record['type'] == 'TXT':
            changes.append({
                'Action': 'UPSERT',
                'ResourceRecordSet': {
                    'Name': record['name'],
                    'Type': 'TXT',
                    'TTL': 300,
                    'ResourceRecords': [{'Value': f'"{record["value"]}"'}]
                }
            })
        elif record['type'] == 'MX':
            changes.append({
                'Action': 'UPSERT',
                'ResourceRecordSet': {
                    'Name': record['name'],
                    'Type': 'MX',
                    'TTL': 300,
                    'ResourceRecords': [{'Value': record['value']}]
                }
            })

    # ── Step 3: Apply changes ────────────────────────────────────────
    if not changes:
        return {'success': True, 'hosted_zone_id': hosted_zone_id, 'records_created': 0}

    response = route53.change_resource_record_sets(
        HostedZoneId=hosted_zone_id,
        ChangeBatch={
            'Comment': f'AgentMail domain setup for {domain} (org: {org_id})',
            'Changes': changes
        }
    )

    change_id = response['ChangeInfo']['Id']

    return {
        'success': True,
        'hosted_zone_id': hosted_zone_id,
        'records_created': len(changes),
        'change_id': change_id,
        'change_status': response['ChangeInfo']['Status']  # PENDING or INSYNC
    }


def _find_hosted_zone(domain: str) -> str | None:
    """Find the Route 53 hosted zone ID for a domain."""
    # Try exact match first, then parent domains
    candidates = []
    parts = domain.split('.')
    for i in range(len(parts) - 1):
        candidates.append('.'.join(parts[i:]) + '.')

    for candidate in candidates:
        response = route53.list_hosted_zones_by_name(
            DNSName=candidate,
            MaxItems='1'
        )
        for zone in response['HostedZones']:
            if zone['Name'] == candidate and not zone['Config']['PrivateZone']:
                return zone['Id'].split('/')[-1]

    return None


def check_route53_delegation(domain: str) -> bool:
    """
    Check if customer has granted AgentMail cross-account access
    to their Route 53 hosted zone.

    This requires the customer to create an IAM role in their account
    that our account can assume.
    """
    # For same-account domains (AgentMail-managed Route 53):
    # No delegation needed -- we have direct access.

    # For cross-account domains:
    # Customer creates a role like:
    #   arn:aws:iam::CUSTOMER_ACCOUNT:role/agentmail-route53-access
    # with policy allowing route53:ChangeResourceRecordSets on their hosted zone.
    # We assume this role before making Route 53 API calls.

    # Implementation depends on whether cross-account is supported.
    pass
```

### Route 53 Auto-Setup UX

```
POST /v1/domains
{
  "domain": "acme.com",
  "auto_setup": true,          // Attempt Route 53 auto-setup
  "route53_role_arn": "..."    // Optional: cross-account role ARN
}

Response (auto-setup succeeded):
{
  "id": "dom_xxx",
  "domain": "acme.com",
  "status": "verifying",
  "dns_records": [...],
  "auto_setup": {
    "success": true,
    "records_created": 6,
    "message": "All DNS records have been automatically configured in Route 53. Verification typically completes within 15 minutes."
  }
}

Response (auto-setup not available):
{
  "id": "dom_xxx",
  "domain": "acme.com",
  "status": "pending",
  "dns_records": [...],
  "auto_setup": {
    "success": false,
    "error": "No Route 53 hosted zone found for this domain",
    "message": "Please add the DNS records listed above to your DNS provider manually."
  }
}
```

---

## DKIM Key Rotation Strategy

### Easy DKIM (AWS-Managed Rotation)

With Easy DKIM, AWS rotates DKIM keys automatically. No customer action required. The CNAME records are permanent -- they point to a stable SES-managed endpoint that serves the current public key.

Key rotation happens transparently:

```
Day 0:    SES generates Key A, serves via CNAME
Day N:    SES generates Key B
Day N+1:  SES starts signing with Key B, still serves Key A for verification
Day N+7:  SES removes Key A, only serves Key B
```

Because the CNAME records point to SES-managed DNS, the rotation is seamless. No DNS changes needed.

### BYODKIM Key Rotation

For customers using BYODKIM, rotation is manual:

```python
def rotate_byodkim_key(domain: str, new_selector: str):
    """
    Rotate a BYODKIM key for a domain.

    Process:
    1. Generate new key pair
    2. Publish new public key in DNS (new selector)
    3. Update SES to use new selector + private key
    4. Wait for DNS propagation (24-48 hours)
    5. Remove old DNS record
    """

    # Step 1: Generate new key pair
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    new_private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

    new_private_pem = new_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()
    ).decode('utf-8')

    # Step 2: Customer adds new DNS record:
    # {new_selector}._domainkey.acme.com TXT "v=DKIM1; k=rsa; p=<new-public-key>"

    # Step 3: Update SES (after DNS propagation)
    ses_v2.put_email_identity_dkim_signing_attributes(
        EmailIdentity=domain,
        SigningAttributesOrigin='EXTERNAL',
        SigningAttributes={
            'DomainSigningSelector': new_selector,
            'DomainSigningPrivateKey': new_private_pem
        }
    )

    # Step 4: Wait 24-48 hours, then remove old DNS record
    # This delay ensures cached DNS entries expire

    return {
        'new_selector': new_selector,
        'dns_record': f'{new_selector}._domainkey.{domain}',
    }
```

### Recommended Rotation Schedule

| Approach | Rotation Frequency | Action Required |
|---|---|---|
| Easy DKIM | Automatic (AWS manages) | None |
| BYODKIM | Every 6-12 months | Generate new key, update DNS + SES |
| BYODKIM (high security) | Every 90 days | Same as above |

---

## Zone File Generation

Customers can retrieve a complete zone file snippet for their domain via `GET /v1/domains/{id}/zone-file`. This makes it easy to copy-paste into any DNS provider.

### Endpoint Implementation

```python
"""
Lambda: domains-zone-file
Triggered by: API Gateway GET /v1/domains/{domain_id}/zone-file
"""

def handler(event, context):
    domain_id = event['pathParameters']['domain_id']
    org_id = event['requestContext']['authorizer']['org_id']

    table = dynamodb.Table(TABLE_NAME)
    response = table.get_item(
        Key={'PK': f'ORG#{org_id}', 'SK': f'DOM#{domain_id}'}
    )

    if 'Item' not in response:
        return _response(404, {'error': 'Domain not found'})

    domain_item = response['Item']
    domain = domain_item['domain_name']
    dns_records = domain_item.get('dns_records', [])

    zone_file = _generate_zone_file(domain, dns_records, domain_item)

    return {
        'statusCode': 200,
        'headers': {
            'Content-Type': 'text/plain',
            'Content-Disposition': f'attachment; filename="{domain}-agentmail.zone"'
        },
        'body': zone_file
    }


def _generate_zone_file(domain: str, dns_records: list[dict], domain_item: dict) -> str:
    """Generate a BIND-format zone file snippet."""

    lines = []
    lines.append(f'; =====================================================')
    lines.append(f'; AgentMail DNS Records for {domain}')
    lines.append(f'; Generated: {time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())}')
    lines.append(f'; Domain ID: {domain_item["domain_id"]}')
    lines.append(f'; Status: {domain_item["status"]}')
    lines.append(f'; =====================================================')
    lines.append(f';')
    lines.append(f'; Add these records to your DNS zone for {domain}')
    lines.append(f'; TTL values can be adjusted to your preference (300 = 5 minutes)')
    lines.append(f';')
    lines.append(f'')

    # DKIM records
    dkim_records = [r for r in dns_records if r['type'] == 'CNAME']
    if dkim_records:
        lines.append(f'; --- DKIM Records (required for email signing) ---')
        for record in dkim_records:
            name = record['name']
            value = record['value']
            if not value.endswith('.'):
                value += '.'
            lines.append(f'{name}.    300    IN    CNAME    {value}')
        lines.append('')

    # SPF record
    spf_records = [r for r in dns_records if r['type'] == 'TXT' and 'spf' in r.get('purpose', '').lower()]
    if spf_records:
        lines.append(f'; --- SPF Record (required for sender authorization) ---')
        lines.append(f'; NOTE: If you already have a TXT record with "v=spf1",')
        lines.append(f'; merge "include:amazonses.com" into it instead of adding a new record.')
        for record in spf_records:
            lines.append(f'{record["name"]}.    300    IN    TXT    "{record["value"]}"')
        lines.append('')

    # DMARC record
    dmarc_records = [r for r in dns_records if r['type'] == 'TXT' and 'dmarc' in r.get('purpose', '').lower()]
    if dmarc_records:
        lines.append(f'; --- DMARC Record (recommended for authentication policy) ---')
        for record in dmarc_records:
            lines.append(f'{record["name"]}.    300    IN    TXT    "{record["value"]}"')
        lines.append('')

    # MX record
    mx_records = [r for r in dns_records if r['type'] == 'MX']
    if mx_records:
        lines.append(f'; --- MX Record (required for inbound email receiving) ---')
        lines.append(f'; WARNING: This will route ALL email for {domain} to AgentMail.')
        lines.append(f'; Only add this if you want AgentMail to handle all inbound mail.')
        for record in mx_records:
            value = record['value']
            if not value.endswith('.'):
                value += '.'
            lines.append(f'{record["name"]}.    300    IN    MX    {value}')
        lines.append('')

    # Verification TXT
    verify_records = [r for r in dns_records if r['type'] == 'TXT' and 'verification' in r.get('purpose', '').lower()]
    if verify_records:
        lines.append(f'; --- Verification Record (optional) ---')
        for record in verify_records:
            lines.append(f'{record["name"]}.    300    IN    TXT    "{record["value"]}"')
        lines.append('')

    # Status footer
    lines.append(f'; =====================================================')
    lines.append(f'; Verification Status:')
    lines.append(f';   DKIM:  {domain_item.get("dkim_status", "unknown")}')
    lines.append(f';   SPF:   {domain_item.get("spf_status", "unknown")}')
    lines.append(f';   MX:    {domain_item.get("mx_status", "unknown")}')
    lines.append(f';   DMARC: {domain_item.get("dmarc_status", "unknown")}')
    lines.append(f'; =====================================================')

    return '\n'.join(lines)
```

### Example Output

```
; =====================================================
; AgentMail DNS Records for acme.com
; Generated: 2026-04-10 14:30:00 UTC
; Domain ID: dom_a1b2c3d4e5f6g7h8i9j0
; Status: pending
; =====================================================
;
; Add these records to your DNS zone for acme.com
; TTL values can be adjusted to your preference (300 = 5 minutes)
;

; --- DKIM Records (required for email signing) ---
token1abc._domainkey.acme.com.    300    IN    CNAME    token1abc.dkim.amazonses.com.
token2def._domainkey.acme.com.    300    IN    CNAME    token2def.dkim.amazonses.com.
token3ghi._domainkey.acme.com.    300    IN    CNAME    token3ghi.dkim.amazonses.com.

; --- SPF Record (required for sender authorization) ---
; NOTE: If you already have a TXT record with "v=spf1",
; merge "include:amazonses.com" into it instead of adding a new record.
acme.com.    300    IN    TXT    "v=spf1 include:amazonses.com ~all"

; --- DMARC Record (recommended for authentication policy) ---
_dmarc.acme.com.    300    IN    TXT    "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@agentmail.dev; pct=100"

; --- MX Record (required for inbound email receiving) ---
; WARNING: This will route ALL email for acme.com to AgentMail.
; Only add this if you want AgentMail to handle all inbound mail.
acme.com.    300    IN    MX    10 inbound-smtp.us-east-1.amazonaws.com.

; --- Verification Record (optional) ---
_agentmail.acme.com.    300    IN    TXT    "agentmail-verify=true"

; =====================================================
; Verification Status:
;   DKIM:  PENDING
;   SPF:   missing
;   MX:    missing
;   DMARC: missing
; =====================================================
```

---

## Domain Status State Machine

### States

```
                    ┌─────────┐
                    │ pending  │  Initial state after POST /v1/domains
                    └────┬────┘
                         │
                    DNS records added, poller detects progress
                         │
                    ┌────▼────────┐
                    │  verifying   │  DKIM verification in progress at SES
                    └────┬────────┘
                         │
              ┌──────────┼──────────────┐
              │          │              │
         ┌────▼────┐ ┌──▼──────────┐ ┌─▼───────┐
         │verified │ │verified_    │ │ failed   │
         │         │ │send_only    │ │          │
         └────┬────┘ └──┬──────────┘ └─▼───────┘
              │          │              │
              │     MX added later      │  Can retry
              │          │              │
              │     ┌────▼────┐    ┌───▼──────┐
              │     │verified │    │ pending   │ (re-created)
              │     └─────────┘    └──────────┘
              │
         Domain deleted or
         ownership transferred
              │
         ┌────▼────┐
         │ deleted  │
         └─────────┘
```

### State Definitions

| State | Description | Transitions |
|---|---|---|
| `pending` | Domain created, waiting for customer to add DNS records | `verifying`, `failed` (timeout) |
| `verifying` | DNS records partially detected, SES verification in progress | `verified`, `verified_send_only`, `failed` |
| `verified` | All records verified: DKIM + SPF + MX. Full send and receive. | `failed` (if DNS removed), `deleted` |
| `verified_send_only` | DKIM + SPF verified but no MX record. Can send, cannot receive. | `verified` (MX added), `failed`, `deleted` |
| `failed` | Verification failed (timeout, DKIM error, DNS misconfiguration) | `pending` (re-initiate), `deleted` |
| `deleted` | Domain removed from AgentMail. SES identity deleted. | Terminal state |

### State Transition Logic

```python
VALID_TRANSITIONS = {
    'pending':           ['verifying', 'failed', 'deleted'],
    'verifying':         ['verified', 'verified_send_only', 'failed', 'deleted'],
    'verified':          ['failed', 'deleted'],
    'verified_send_only':['verified', 'failed', 'deleted'],
    'failed':            ['pending', 'deleted'],
    'deleted':           [],
}

def transition_domain_status(current: str, target: str) -> bool:
    """Validate a domain status transition."""
    return target in VALID_TRANSITIONS.get(current, [])
```

### Periodic Health Checks

After a domain is verified, we continue monitoring its DNS health:

```python
"""
Lambda: domain-health-checker
Triggered by: EventBridge rule (every 6 hours)
"""

def handler(event, context):
    """Check DNS health of all verified domains."""
    table = dynamodb.Table(TABLE_NAME)

    # Query all verified domains
    response = table.scan(
        FilterExpression=(
            Attr('status').is_in(['verified', 'verified_send_only']) &
            Attr('SK').begins_with('DOM#')
        )
    )

    for domain_item in response['Items']:
        domain = domain_item['domain_name']
        dns_results = validate_dns_records(domain, domain_item.get('dns_records', []))

        # Check for DKIM removal
        if dns_results['dkim']['status'] != 'verified':
            logger.warning(f'DKIM records missing for verified domain {domain}')
            # Notify customer but don't immediately downgrade
            _publish_event('domain.dns_warning', domain_item['org_id'],
                         domain_item['domain_id'], domain)

            # If DKIM has been missing for >24 hours, downgrade
            warning_key = f'dkim_warning_since'
            if warning_key not in domain_item:
                table.update_item(
                    Key={'PK': domain_item['PK'], 'SK': domain_item['SK']},
                    UpdateExpression=f'SET {warning_key} = :now',
                    ExpressionAttributeValues={':now': int(time.time() * 1000)}
                )
            elif (int(time.time() * 1000) - domain_item[warning_key]) > 24 * 60 * 60 * 1000:
                _update_domain_status(table, domain_item, 'failed', {
                    'failure_reason': 'dkim_records_removed',
                    'message': 'DKIM DNS records no longer detected'
                })

        # Check for MX removal (verified → verified_send_only)
        if (domain_item['status'] == 'verified' and
            dns_results['mx']['status'] != 'verified'):
            _update_domain_status(table, domain_item, 'verified_send_only', {
                'note': 'MX record no longer detected. Inbound receiving disabled.'
            })

        # Check for MX addition (verified_send_only → verified)
        if (domain_item['status'] == 'verified_send_only' and
            dns_results['mx']['status'] == 'verified'):
            _update_domain_status(table, domain_item, 'verified', {
                'note': 'MX record detected. Inbound receiving enabled.'
            })
            _add_inbound_receipt_rule(domain, domain_item['org_id'])
```
