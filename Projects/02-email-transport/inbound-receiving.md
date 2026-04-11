# Inbound Email Receiving

## Overview

Every email sent to an AgentMail-managed address (whether on the platform domain `agentmail.dev` or a customer's custom domain) flows through the same inbound pipeline: SES receives the message via SMTP, stores the raw MIME in S3, and invokes a Lambda function that parses, routes, stores, and publishes the message. This document covers every component of that pipeline in detail.

---

## Table of Contents

- [MX Record Configuration](#mx-record-configuration)
- [Receipt Rule Sets and Receipt Rules](#receipt-rule-sets-and-receipt-rules)
- [The Full Inbound Pipeline](#the-full-inbound-pipeline)
- [Lambda Router Function](#lambda-router-function)
- [SES Inbound Limits](#ses-inbound-limits)
- [SES Verdicts](#ses-verdicts)
- [Address Scheme Design](#address-scheme-design)

---

## MX Record Configuration

For SES to receive email for a domain, that domain's MX record must point to the SES inbound SMTP endpoint for the region. SES inbound is only available in three regions.

### Platform Domain

```dns
; agentmail.dev zone file (Route 53)
agentmail.dev.    IN  MX  10  inbound-smtp.us-east-1.amazonaws.com.
```

### Customer Custom Domains

When a customer verifies `acme.com` for inbound receiving, we instruct them to add:

```dns
; acme.com zone file (customer's DNS provider)
acme.com.         IN  MX  10  inbound-smtp.us-east-1.amazonaws.com.
```

### Regional MX Endpoints

| Region | MX Endpoint |
|---|---|
| `us-east-1` (N. Virginia) | `inbound-smtp.us-east-1.amazonaws.com` |
| `us-west-2` (Oregon) | `inbound-smtp.us-west-2.amazonaws.com` |
| `eu-west-1` (Ireland) | `inbound-smtp.eu-west-1.amazonaws.com` |

We default to `us-east-1`. Customers with EU data residency requirements can be directed to `eu-west-1`, but this requires a separate SES inbound configuration in that region.

### MX Priority and Failover

MX records support priority-based failover, but SES inbound endpoints are regional and do not fail over to other regions. If `us-east-1` inbound is down, mail queues at the sending server and retries per SMTP standards (typically up to 5 days).

For critical customers, we can set up dual-region inbound:

```dns
acme.com.    IN  MX  10  inbound-smtp.us-east-1.amazonaws.com.
acme.com.    IN  MX  20  inbound-smtp.us-west-2.amazonaws.com.
```

This requires duplicate Receipt Rule Sets in both regions and deduplication logic in the router Lambda.

---

## Receipt Rule Sets and Receipt Rules

SES organizes inbound email processing into Receipt Rule Sets (containers) and Receipt Rules (per-domain or per-address matching with ordered actions).

### Architecture: Catch-All

SES inbound does not have an "inbox" concept. It matches incoming email against Receipt Rules in order, and each rule can trigger actions. We use a single catch-all rule per domain that routes everything to our Lambda router, which handles virtual inbox resolution.

### Rule Set Configuration

```python
import boto3

ses_v1 = boto3.client('ses', region_name='us-east-1')  # Receipt rules use SES v1 API

def setup_inbound_rules():
    """Set up SES inbound receipt rules for AgentMail."""

    # 1. Create the rule set (only one can be active per account per region)
    ses_v1.create_receipt_rule_set(
        RuleSetName='agentmail-inbound'
    )

    # 2. Create catch-all rule for the platform domain
    ses_v1.create_receipt_rule(
        RuleSetName='agentmail-inbound',
        Rule={
            'Name': 'agentmail-dev-catchall',
            'Enabled': True,
            'TlsPolicy': 'Optional',  # Accept non-TLS for max deliverability
            'Recipients': [
                'agentmail.dev'  # Matches ALL addresses @agentmail.dev
            ],
            'Actions': [
                # Action 1: Store raw MIME in S3
                {
                    'S3Action': {
                        'BucketName': 'agentmail-raw-email',
                        'ObjectKeyPrefix': 'inbound/',
                        'TopicArn': '',  # No separate SNS notification needed
                        'KmsKeyArn': 'arn:aws:kms:us-east-1:123456789012:key/xxx'
                    }
                },
                # Action 2: Invoke Lambda router (asynchronous)
                {
                    'LambdaAction': {
                        'FunctionArn': 'arn:aws:lambda:us-east-1:123456789012:function:inbound-router',
                        'InvocationType': 'Event',  # Async -- don't block SMTP
                        'TopicArn': ''
                    }
                }
            ],
            'ScanEnabled': True  # Enable spam/virus scanning
        }
    )

    # 3. Activate the rule set
    ses_v1.set_active_receipt_rule_set(
        RuleSetName='agentmail-inbound'
    )
```

### Adding Custom Domain Rules

When a customer verifies a custom domain and enables inbound receiving, we add a new rule:

```python
def add_domain_inbound_rule(domain: str, org_id: str):
    """Add a receipt rule for a customer's verified domain."""

    ses_v1.create_receipt_rule(
        RuleSetName='agentmail-inbound',
        After='agentmail-dev-catchall',  # Insert after platform rule
        Rule={
            'Name': f'domain-{domain.replace(".", "-")}',
            'Enabled': True,
            'TlsPolicy': 'Optional',
            'Recipients': [domain],  # Catch-all for this domain
            'Actions': [
                {
                    'S3Action': {
                        'BucketName': 'agentmail-raw-email',
                        'ObjectKeyPrefix': f'inbound/',
                        'KmsKeyArn': 'arn:aws:kms:us-east-1:123456789012:key/xxx'
                    }
                },
                {
                    'LambdaAction': {
                        'FunctionArn': 'arn:aws:lambda:us-east-1:123456789012:function:inbound-router',
                        'InvocationType': 'Event'
                    }
                }
            ],
            'ScanEnabled': True
        }
    )
```

### Rule Ordering

SES evaluates rules in order and stops at the first match. Order matters:

1. **Specific address rules** (if any): For special handling of `postmaster@`, `abuse@`, `bounce@`
2. **Platform domain catch-all**: `agentmail.dev`
3. **Customer domain catch-alls**: One per verified domain, in order of creation

### Rule Set Limits

| Limit | Value |
|---|---|
| Active rule sets per account per region | 1 |
| Rules per rule set | 200 |
| Recipients per rule | 100 |
| Actions per rule | 5 |

At 200 rules max, we can support ~198 customer domains per region (keeping 2 slots for platform rules). For scale beyond that, we use a single catch-all rule that matches all domains and let the Lambda router handle domain validation.

**Scaling approach for 200+ domains:**

```python
# Instead of per-domain rules, use a single wildcard rule
ses_v1.create_receipt_rule(
    RuleSetName='agentmail-inbound',
    Rule={
        'Name': 'agentmail-global-catchall',
        'Enabled': True,
        'Recipients': [],  # Empty = matches ALL recipients
        'Actions': [
            {'S3Action': {'BucketName': 'agentmail-raw-email', 'ObjectKeyPrefix': 'inbound/'}},
            {'LambdaAction': {
                'FunctionArn': 'arn:aws:lambda:us-east-1:123456789012:function:inbound-router',
                'InvocationType': 'Event'
            }}
        ],
        'ScanEnabled': True
    }
)
```

With an empty `Recipients` list, SES forwards everything. The Lambda router validates that the recipient domain is actually managed by AgentMail and bounces anything else.

---

## The Full Inbound Pipeline

```
Internet (sender's mail server)
         │
         │  SMTP connection to inbound-smtp.us-east-1.amazonaws.com
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│  SES Inbound SMTP Endpoint                              │
│                                                         │
│  1. Accept SMTP connection                              │
│  2. Receive MAIL FROM, RCPT TO, DATA                    │
│  3. Run spam/virus/SPF/DKIM/DMARC checks               │
│  4. Match recipient against Receipt Rules               │
│  5. Execute matched rule's actions (in order):          │
│     a. S3Action: store raw MIME                         │
│     b. LambdaAction: invoke router (async)              │
│  6. Return 250 OK to sending server                     │
│                                                         │
│  Total SMTP transaction time: typically 200-500ms       │
└────────┬────────────────────────────┬───────────────────┘
         │                            │
         ▼                            ▼
┌──────────────────┐    ┌──────────────────────────────────┐
│  S3 Bucket        │    │  Lambda: inbound-router           │
│  agentmail-raw-   │    │  (invoked asynchronously)         │
│  email/inbound/   │    │                                   │
│  {ses-message-id} │    │  Input: SES notification JSON     │
│                    │    │  containing mail headers,         │
│  Raw MIME stored   │    │  recipients, verdicts, and S3     │
│  encrypted at      │    │  location of raw MIME             │
│  rest (KMS)        │    │                                   │
└──────────────────┘    └──────────┬───────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    │              │              │
                    ▼              ▼              ▼
              ┌──────────┐  ┌──────────┐  ┌──────────┐
              │ DynamoDB  │  │    S3     │  │ Kinesis  │
              │           │  │           │  │          │
              │ Message   │  │ Attach-   │  │ Events:  │
              │ metadata  │  │ ments     │  │ message  │
              │ Thread    │  │           │  │ .received│
              │ updates   │  │           │  │          │
              └──────────┘  └──────────┘  └──────────┘
```

---

## Lambda Router Function

This is the core of inbound email processing. The function receives an SES notification, fetches the raw MIME from S3, parses it, resolves the recipient inbox, stores the message, and publishes events.

### SES Notification Format

When SES invokes the Lambda, it passes a notification with this structure:

```json
{
  "Records": [
    {
      "eventVersion": "1.0",
      "eventSource": "aws:ses",
      "ses": {
        "mail": {
          "timestamp": "2026-04-10T14:30:00.000Z",
          "source": "sender@example.com",
          "messageId": "o3vrnil0e2ic28tr",
          "destination": [
            "agent-42@acme.agentmail.dev"
          ],
          "headersTruncated": false,
          "headers": [
            {"name": "From", "value": "Alice <sender@example.com>"},
            {"name": "To", "value": "agent-42@acme.agentmail.dev"},
            {"name": "Subject", "value": "Re: Order #12345 status"},
            {"name": "Date", "value": "Thu, 10 Apr 2026 14:30:00 +0000"},
            {"name": "Message-ID", "value": "<abc123@example.com>"},
            {"name": "In-Reply-To", "value": "<msg_xxx@acme.agentmail.dev>"},
            {"name": "References", "value": "<msg_yyy@acme.agentmail.dev> <msg_xxx@acme.agentmail.dev>"},
            {"name": "MIME-Version", "value": "1.0"},
            {"name": "Content-Type", "value": "multipart/mixed; boundary=\"----=_Part_123\""}
          ],
          "commonHeaders": {
            "returnPath": "sender@example.com",
            "from": ["Alice <sender@example.com>"],
            "date": "Thu, 10 Apr 2026 14:30:00 +0000",
            "to": ["agent-42@acme.agentmail.dev"],
            "messageId": "<abc123@example.com>",
            "subject": "Re: Order #12345 status"
          }
        },
        "receipt": {
          "timestamp": "2026-04-10T14:30:00.500Z",
          "processingTimeMillis": 500,
          "recipients": ["agent-42@acme.agentmail.dev"],
          "spamVerdict": {"status": "PASS"},
          "virusVerdict": {"status": "PASS"},
          "spfVerdict": {"status": "PASS"},
          "dkimVerdict": {"status": "PASS"},
          "dmarcVerdict": {"status": "PASS"},
          "dmarcPolicy": "reject",
          "action": {
            "type": "Lambda",
            "functionArn": "arn:aws:lambda:us-east-1:123456789012:function:inbound-router",
            "invocationType": "Event"
          }
        }
      }
    }
  ]
}
```

### Complete Lambda Router Implementation

```python
"""
Lambda: inbound-router
Triggered by: SES Receipt Rule (LambdaAction, async)
Memory: 1024 MB
Timeout: 120 seconds
"""

import json
import email
import email.policy
import hashlib
import re
import time
import uuid
from email import message_from_bytes
from email.utils import parseaddr, getaddresses
from typing import Optional
import logging

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS clients
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')
ses_v1 = boto3.client('ses', region_name='us-east-1')
kinesis = boto3.client('kinesis', region_name='us-east-1')
redis_client = None  # Initialized lazily from ElastiCache

TABLE_NAME = 'agentmail'
RAW_EMAIL_BUCKET = 'agentmail-raw-email'
ATTACHMENTS_BUCKET = 'agentmail-attachments'
BODIES_BUCKET = 'agentmail-bodies'
KINESIS_STREAM = 'agentmail-events'

# Constants
MAX_BODY_PREVIEW_BYTES = 4096
MAX_ATTACHMENT_SIZE = 25 * 1024 * 1024  # 25 MB
THREAD_MAX_MESSAGES = 100


def handler(event, context):
    """
    Main entry point for inbound email processing.

    Processes each SES record (typically one per invocation).
    """
    table = dynamodb.Table(TABLE_NAME)

    for record in event['Records']:
        ses_event = record['ses']
        mail = ses_event['mail']
        receipt = ses_event['receipt']
        ses_message_id = mail['messageId']

        logger.info(f'Processing inbound message: {ses_message_id}')

        try:
            # ── Phase 1: Parse SES notification ──────────────────────
            sender = mail['source']
            recipients = receipt['recipients']  # Only recipients that matched this rule
            subject = mail['commonHeaders'].get('subject', '(no subject)')
            rfc_message_id = mail['commonHeaders'].get('messageId', '')
            timestamp = mail['timestamp']

            # Extract threading headers from the full headers list
            headers_dict = {h['name'].lower(): h['value'] for h in mail['headers']}
            in_reply_to = headers_dict.get('in-reply-to', '')
            references_raw = headers_dict.get('references', '')
            references = references_raw.split() if references_raw else []

            # ── Phase 2: Check verdicts ──────────────────────────────
            verdict_result = _check_verdicts(receipt)
            if verdict_result['action'] == 'reject':
                logger.warning(
                    f'Message {ses_message_id} rejected by verdicts: {verdict_result["reasons"]}'
                )
                # Optionally bounce back to sender
                if verdict_result.get('bounce', False):
                    _send_bounce(ses_message_id, sender, verdict_result['reasons'])
                continue

            # ── Phase 3: Fetch raw MIME from S3 ──────────────────────
            s3_key = f'inbound/{ses_message_id}'
            raw_mime_response = s3.get_object(
                Bucket=RAW_EMAIL_BUCKET,
                Key=s3_key
            )
            raw_mime_bytes = raw_mime_response['Body'].read()
            raw_mime_size = len(raw_mime_bytes)

            # ── Phase 4: Resolve recipients to inboxes ───────────────
            for recipient_address in recipients:
                recipient_lower = recipient_address.lower()

                inbox = _resolve_inbox(table, recipient_lower)
                if inbox is None:
                    logger.info(f'No inbox found for {recipient_lower}, bouncing')
                    _send_bounce_unknown_inbox(ses_message_id, sender, recipient_lower)
                    continue

                inbox_id = inbox['inbox_id']
                org_id = inbox['org_id']
                domain_id = inbox.get('domain_id')

                # Check allow/block lists
                list_decision = _check_allow_block_list(table, inbox_id, sender)
                if list_decision == 'block':
                    logger.info(f'Sender {sender} blocked for inbox {inbox_id}')
                    continue  # Silently drop (or bounce, depending on config)

                # ── Phase 5: Parse MIME message ──────────────────────
                parsed = _parse_mime(raw_mime_bytes)

                # ── Phase 6: Compute thread ──────────────────────────
                thread_id = _resolve_thread(
                    table=table,
                    inbox_id=inbox_id,
                    in_reply_to=in_reply_to,
                    references=references,
                    subject=subject
                )

                # ── Phase 7: Generate IDs and timestamps ─────────────
                message_id = f'msg_{uuid.uuid4().hex[:20]}'
                now_ms = int(time.time() * 1000)

                # ── Phase 8: Store attachments in S3 ─────────────────
                attachment_records = []
                for att in parsed['attachments']:
                    att_id = f'att_{uuid.uuid4().hex[:16]}'
                    att_s3_key = f'{org_id}/{message_id}/{att_id}/{att["filename"]}'

                    s3.put_object(
                        Bucket=ATTACHMENTS_BUCKET,
                        Key=att_s3_key,
                        Body=att['data'],
                        ContentType=att['content_type'],
                        ServerSideEncryption='aws:kms',
                        Metadata={
                            'org_id': org_id,
                            'message_id': message_id,
                            'original_filename': att['filename']
                        }
                    )

                    attachment_records.append({
                        'PK': f'MSG#{message_id}',
                        'SK': f'ATT#{att_id}',
                        'attachment_id': att_id,
                        'filename': att['filename'],
                        'content_type': att['content_type'],
                        'size': len(att['data']),
                        's3_key': att_s3_key,
                        's3_bucket': ATTACHMENTS_BUCKET,
                        'created_at': now_ms
                    })

                # ── Phase 9: Store large HTML body in S3 ─────────────
                html_s3_key = None
                html_body = parsed.get('html_body', '')
                text_body = parsed.get('text_body', '')

                if html_body and len(html_body.encode('utf-8')) > MAX_BODY_PREVIEW_BYTES:
                    html_s3_key = f'{org_id}/{message_id}/body.html'
                    s3.put_object(
                        Bucket=BODIES_BUCKET,
                        Key=html_s3_key,
                        Body=html_body.encode('utf-8'),
                        ContentType='text/html; charset=utf-8',
                        ServerSideEncryption='aws:kms'
                    )

                # ── Phase 10: Build body preview ─────────────────────
                body_preview = text_body[:MAX_BODY_PREVIEW_BYTES] if text_body else ''
                if not body_preview and html_body:
                    # Strip HTML tags for preview
                    body_preview = re.sub(r'<[^>]+>', '', html_body)[:MAX_BODY_PREVIEW_BYTES]

                # ── Phase 11: Write message to DynamoDB ──────────────
                message_item = {
                    'PK': f'INB#{inbox_id}',
                    'SK': f'MSG#{now_ms}#{message_id}',
                    'message_id': message_id,
                    'inbox_id': inbox_id,
                    'org_id': org_id,
                    'thread_id': thread_id,
                    'direction': 'inbound',
                    'status': 'received',

                    # Envelope
                    'from_address': sender,
                    'from_display': parsed['from_display'],
                    'to': recipients,
                    'cc': parsed.get('cc', []),
                    'subject': subject,

                    # Body
                    'body_preview': body_preview,
                    'text_body': text_body[:MAX_BODY_PREVIEW_BYTES] if text_body else None,
                    'html_s3_key': html_s3_key,
                    'has_html': bool(html_body),
                    'has_attachments': len(attachment_records) > 0,
                    'attachment_count': len(attachment_records),
                    'attachment_ids': [a['attachment_id'] for a in attachment_records],

                    # Threading headers (stored for future thread computation)
                    'rfc_message_id': rfc_message_id,
                    'in_reply_to': in_reply_to or None,
                    'references': references if references else None,

                    # SES metadata
                    'ses_message_id': ses_message_id,
                    'raw_mime_s3_key': s3_key,
                    'raw_mime_s3_bucket': RAW_EMAIL_BUCKET,
                    'raw_mime_size': raw_mime_size,

                    # Verdicts
                    'spam_verdict': receipt['spamVerdict']['status'],
                    'virus_verdict': receipt['virusVerdict']['status'],
                    'spf_verdict': receipt['spfVerdict']['status'],
                    'dkim_verdict': receipt['dkimVerdict']['status'],
                    'dmarc_verdict': receipt['dmarcVerdict']['status'],

                    # Timestamps
                    'received_at': now_ms,
                    'created_at': now_ms,

                    # GSI keys
                    'GSI5_PK': f'MSGID#{rfc_message_id}' if rfc_message_id else None,
                    'GSI5_SK': f'MSG#{message_id}',
                }

                # Remove None values (DynamoDB doesn't accept None)
                message_item = {k: v for k, v in message_item.items() if v is not None}

                # Write message
                table.put_item(Item=message_item)

                # Write attachment records
                for att_record in attachment_records:
                    table.put_item(Item=att_record)

                # ── Phase 12: Update thread ──────────────────────────
                _update_thread(table, inbox_id, thread_id, message_id, subject, sender, now_ms)

                # ── Phase 13: Update inbox counters ──────────────────
                table.update_item(
                    Key={
                        'PK': f'ORG#{org_id}',
                        'SK': f'INB#{inbox_id}'
                    },
                    UpdateExpression=(
                        'ADD total_messages :one, unread_messages :one '
                        'SET last_message_at = :now'
                    ),
                    ExpressionAttributeValues={
                        ':one': 1,
                        ':now': now_ms
                    }
                )

                # ── Phase 14: Publish event to Kinesis ───────────────
                event_payload = {
                    'eventId': f'evt_{uuid.uuid4().hex[:20]}',
                    'eventType': 'message.received',
                    'eventVersion': '1.0',
                    'timestamp': now_ms,
                    'orgId': org_id,
                    'podId': inbox.get('pod_id'),
                    'inboxId': inbox_id,
                    'data': {
                        'messageId': message_id,
                        'threadId': thread_id,
                        'from': sender,
                        'to': recipients,
                        'subject': subject,
                        'hasAttachments': len(attachment_records) > 0,
                        'attachmentCount': len(attachment_records),
                        'bodyPreview': body_preview[:200],
                        'verdicts': {
                            'spam': receipt['spamVerdict']['status'],
                            'virus': receipt['virusVerdict']['status'],
                            'spf': receipt['spfVerdict']['status'],
                            'dkim': receipt['dkimVerdict']['status'],
                            'dmarc': receipt['dmarcVerdict']['status'],
                        }
                    }
                }

                kinesis.put_record(
                    StreamName=KINESIS_STREAM,
                    Data=json.dumps(event_payload),
                    PartitionKey=inbox_id
                )

                logger.info(
                    f'Stored inbound message {message_id} in inbox {inbox_id}, '
                    f'thread {thread_id}, {len(attachment_records)} attachments'
                )

        except Exception as e:
            logger.exception(f'Error processing inbound message {ses_message_id}: {e}')
            # Store the failed message reference for manual review
            _store_processing_failure(ses_message_id, str(e))
            raise  # Let Lambda retry (up to 2 async retries)


# ═══════════════════════════════════════════════════════════════════════
# VERDICT CHECKING
# ═══════════════════════════════════════════════════════════════════════

def _check_verdicts(receipt: dict) -> dict:
    """
    Evaluate SES verdicts and decide whether to accept, flag, or reject.

    Returns: {'action': 'accept'|'flag'|'reject', 'reasons': [...], 'bounce': bool}
    """
    verdicts = {
        'spam': receipt['spamVerdict']['status'],
        'virus': receipt['virusVerdict']['status'],
        'spf': receipt['spfVerdict']['status'],
        'dkim': receipt['dkimVerdict']['status'],
        'dmarc': receipt['dmarcVerdict']['status'],
    }

    reasons = []

    # Hard reject: virus detected
    if verdicts['virus'] == 'FAIL':
        return {'action': 'reject', 'reasons': ['virus_detected'], 'bounce': False}

    # Hard reject: spam with high confidence
    if verdicts['spam'] == 'FAIL':
        reasons.append('spam_detected')
        # We still accept but flag -- AI agents may want to see spam
        # Override per inbox: some inboxes may want hard reject

    # SPF/DKIM/DMARC failures -- flag but accept
    if verdicts['spf'] == 'FAIL':
        reasons.append('spf_fail')
    if verdicts['dkim'] == 'FAIL':
        reasons.append('dkim_fail')
    if verdicts['dmarc'] == 'FAIL':
        reasons.append('dmarc_fail')
        # Check DMARC policy
        dmarc_policy = receipt.get('dmarcPolicy', 'none')
        if dmarc_policy == 'reject':
            return {'action': 'reject', 'reasons': reasons, 'bounce': True}

    if reasons:
        return {'action': 'flag', 'reasons': reasons, 'bounce': False}

    return {'action': 'accept', 'reasons': [], 'bounce': False}


# ═══════════════════════════════════════════════════════════════════════
# RECIPIENT RESOLUTION
# ═══════════════════════════════════════════════════════════════════════

def _resolve_inbox(table, recipient_address: str) -> Optional[dict]:
    """
    Resolve a recipient email address to an AgentMail inbox.

    Uses GSI2: PK=ADDR#{email_address}, SK=INB#{inbox_id}

    Returns inbox dict with inbox_id, org_id, pod_id, domain_id
    or None if no inbox matches.
    """
    # 1. Try exact address match (GSI2)
    response = table.query(
        IndexName='GSI2',
        KeyConditionExpression=Key('GSI2_PK').eq(f'ADDR#{recipient_address}'),
        Limit=1
    )

    if response['Items']:
        item = response['Items'][0]
        return {
            'inbox_id': item['inbox_id'],
            'org_id': item['org_id'],
            'pod_id': item.get('pod_id'),
            'domain_id': item.get('domain_id')
        }

    # 2. Try Redis cache (for high-throughput inboxes)
    if redis_client:
        cached = redis_client.hgetall(f'inbox:addr:{recipient_address}')
        if cached:
            return {
                'inbox_id': cached['inbox_id'],
                'org_id': cached['org_id'],
                'pod_id': cached.get('pod_id'),
                'domain_id': cached.get('domain_id')
            }

    # 3. Try catch-all for the domain
    domain = recipient_address.split('@')[1]
    response = table.query(
        IndexName='GSI6',
        KeyConditionExpression=Key('GSI6_PK').eq(f'DOMAIN#{domain}'),
        Limit=1
    )

    if response['Items']:
        domain_item = response['Items'][0]
        # Check if domain has a catch-all inbox configured
        if domain_item.get('catch_all_inbox_id'):
            org_id = domain_item['org_id']
            catch_all_id = domain_item['catch_all_inbox_id']
            return {
                'inbox_id': catch_all_id,
                'org_id': org_id,
                'pod_id': domain_item.get('pod_id'),
                'domain_id': domain_item.get('domain_id')
            }

    # 4. No match found
    return None


def _check_allow_block_list(table, inbox_id: str, sender_address: str) -> str:
    """
    Check if sender is on inbox's allow or block list.

    Returns 'allow', 'block', or 'neutral'.
    """
    sender_lower = sender_address.lower()
    sender_domain = sender_lower.split('@')[1]

    # Check exact address block
    block_response = table.get_item(
        Key={
            'PK': f'INB#{inbox_id}',
            'SK': f'LST#block#{sender_lower}'
        }
    )
    if 'Item' in block_response:
        return 'block'

    # Check domain-level block
    block_response = table.get_item(
        Key={
            'PK': f'INB#{inbox_id}',
            'SK': f'LST#block#@{sender_domain}'
        }
    )
    if 'Item' in block_response:
        return 'block'

    # Check exact address allow
    allow_response = table.get_item(
        Key={
            'PK': f'INB#{inbox_id}',
            'SK': f'LST#allow#{sender_lower}'
        }
    )
    if 'Item' in allow_response:
        return 'allow'

    return 'neutral'


# ═══════════════════════════════════════════════════════════════════════
# MIME PARSING
# ═══════════════════════════════════════════════════════════════════════

def _parse_mime(raw_bytes: bytes) -> dict:
    """
    Parse a raw MIME message into structured components.

    Returns:
    {
        'from_display': str,       # Display name of sender
        'cc': list[str],           # CC addresses
        'text_body': str,          # Plain text body
        'html_body': str,          # HTML body
        'attachments': [           # List of attachments
            {
                'filename': str,
                'content_type': str,
                'data': bytes,
                'size': int,
                'content_id': str | None,  # For inline images
            }
        ]
    }
    """
    msg = message_from_bytes(raw_bytes, policy=email.policy.default)

    # Extract sender display name
    from_header = msg.get('From', '')
    from_display, from_addr = parseaddr(from_header)

    # Extract CC
    cc_header = msg.get('Cc', '')
    cc_addresses = [addr for name, addr in getaddresses([cc_header]) if addr]

    text_body = ''
    html_body = ''
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get('Content-Disposition', ''))

            # Skip multipart containers
            if part.get_content_maintype() == 'multipart':
                continue

            # Attachments (explicit attachment disposition or non-text types)
            if 'attachment' in content_disposition or (
                content_type not in ('text/plain', 'text/html') and
                'inline' not in content_disposition
            ):
                filename = part.get_filename()
                if not filename:
                    # Generate filename from content type
                    ext = content_type.split('/')[-1]
                    filename = f'attachment.{ext}'

                data = part.get_payload(decode=True)
                if data and len(data) <= MAX_ATTACHMENT_SIZE:
                    attachments.append({
                        'filename': _sanitize_filename(filename),
                        'content_type': content_type,
                        'data': data,
                        'size': len(data),
                        'content_id': part.get('Content-ID', '').strip('<>') or None
                    })

            # Inline images (for multipart/related)
            elif 'inline' in content_disposition and content_type.startswith('image/'):
                filename = part.get_filename() or 'inline_image'
                data = part.get_payload(decode=True)
                if data and len(data) <= MAX_ATTACHMENT_SIZE:
                    attachments.append({
                        'filename': _sanitize_filename(filename),
                        'content_type': content_type,
                        'data': data,
                        'size': len(data),
                        'content_id': part.get('Content-ID', '').strip('<>') or None
                    })

            # Text body
            elif content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        text_body += payload.decode(charset)
                    except (UnicodeDecodeError, LookupError):
                        text_body += payload.decode('utf-8', errors='replace')

            # HTML body
            elif content_type == 'text/html':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        html_body += payload.decode(charset)
                    except (UnicodeDecodeError, LookupError):
                        html_body += payload.decode('utf-8', errors='replace')

    else:
        # Non-multipart message
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            try:
                decoded = payload.decode(charset)
            except (UnicodeDecodeError, LookupError):
                decoded = payload.decode('utf-8', errors='replace')

            if content_type == 'text/html':
                html_body = decoded
            else:
                text_body = decoded

    return {
        'from_display': from_display,
        'cc': cc_addresses,
        'text_body': text_body,
        'html_body': html_body,
        'attachments': attachments,
    }


def _sanitize_filename(filename: str) -> str:
    """Remove or replace dangerous characters in attachment filenames."""
    # Remove path traversal
    filename = filename.replace('/', '_').replace('\\', '_')
    # Remove null bytes
    filename = filename.replace('\x00', '')
    # Limit length
    if len(filename) > 255:
        name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
        filename = name[:250] + ('.' + ext if ext else '')
    return filename


# ═══════════════════════════════════════════════════════════════════════
# THREAD COMPUTATION
# ═══════════════════════════════════════════════════════════════════════

def _resolve_thread(
    table,
    inbox_id: str,
    in_reply_to: str,
    references: list[str],
    subject: str
) -> str:
    """
    Resolve which thread this message belongs to.

    Algorithm (in priority order):
    1. In-Reply-To header → look up parent message by RFC Message-ID (GSI5)
    2. References header → look up thread root (first reference)
    3. Subject normalization → match existing thread by normalized subject
    4. No match → create new thread

    Returns: thread_id (existing or newly created)
    """

    # ── Strategy 1: In-Reply-To lookup ───────────────────────────────
    if in_reply_to:
        parent_msg = _lookup_message_by_rfc_id(table, in_reply_to)
        if parent_msg and parent_msg.get('thread_id'):
            thread_id = parent_msg['thread_id']
            # Verify thread is not at max capacity
            if _get_thread_message_count(table, inbox_id, thread_id) < THREAD_MAX_MESSAGES:
                return thread_id

    # ── Strategy 2: References chain lookup ──────────────────────────
    if references:
        # First reference is typically the thread root
        for ref in references:
            ref_msg = _lookup_message_by_rfc_id(table, ref)
            if ref_msg and ref_msg.get('thread_id'):
                thread_id = ref_msg['thread_id']
                if _get_thread_message_count(table, inbox_id, thread_id) < THREAD_MAX_MESSAGES:
                    return thread_id

    # ── Strategy 3: Subject normalization fallback ───────────────────
    normalized = _normalize_subject(subject)
    if normalized:
        # Look for recent threads in this inbox with matching normalized subject
        # Query the inbox's threads, sorted by last_message_at descending
        response = table.query(
            KeyConditionExpression=(
                Key('PK').eq(f'INB#{inbox_id}') &
                Key('SK').begins_with('THR#')
            ),
            ScanIndexForward=False,  # Most recent first
            Limit=20
        )

        for thread_item in response.get('Items', []):
            thread_normalized = _normalize_subject(thread_item.get('subject', ''))
            if thread_normalized == normalized:
                # Found a matching thread -- check recency (within 30 days)
                thread_age_ms = int(time.time() * 1000) - thread_item.get('last_message_at', 0)
                if thread_age_ms < 30 * 24 * 60 * 60 * 1000:  # 30 days in ms
                    thread_id = thread_item['thread_id']
                    if _get_thread_message_count(table, inbox_id, thread_id) < THREAD_MAX_MESSAGES:
                        return thread_id

    # ── Strategy 4: Create new thread ────────────────────────────────
    thread_id = f'thr_{uuid.uuid4().hex[:20]}'
    return thread_id


def _lookup_message_by_rfc_id(table, rfc_message_id: str) -> Optional[dict]:
    """Look up a message by its RFC Message-ID header using GSI5."""
    response = table.query(
        IndexName='GSI5',
        KeyConditionExpression=Key('GSI5_PK').eq(f'MSGID#{rfc_message_id}'),
        Limit=1
    )
    if response['Items']:
        return response['Items'][0]
    return None


def _get_thread_message_count(table, inbox_id: str, thread_id: str) -> int:
    """Get current message count for a thread."""
    response = table.get_item(
        Key={
            'PK': f'INB#{inbox_id}',
            'SK': f'THR#{thread_id}'
        },
        ProjectionExpression='message_count'
    )
    if 'Item' in response:
        return response['Item'].get('message_count', 0)
    return 0


def _normalize_subject(subject: str) -> str:
    """
    Normalize a subject line for thread matching.

    Strips Re:, Fwd:, Fw:, and similar prefixes.
    Case-insensitive.
    Collapses whitespace.
    """
    if not subject:
        return ''
    # Strip common prefixes (RFC 5256 compatible)
    normalized = re.sub(
        r'^(\s*(Re|Fwd|Fw|Aw|Sv|Vs|Ref)\s*(\[\d+\])?\s*:\s*)+',
        '',
        subject,
        flags=re.IGNORECASE
    )
    # Collapse whitespace and strip
    normalized = re.sub(r'\s+', ' ', normalized).strip().lower()
    return normalized


# ═══════════════════════════════════════════════════════════════════════
# THREAD STATE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════

def _update_thread(
    table,
    inbox_id: str,
    thread_id: str,
    message_id: str,
    subject: str,
    sender: str,
    timestamp_ms: int
):
    """
    Create or update a thread record.

    Uses atomic operations to safely handle concurrent message arrivals.
    """
    try:
        table.update_item(
            Key={
                'PK': f'INB#{inbox_id}',
                'SK': f'THR#{thread_id}'
            },
            UpdateExpression=(
                'SET thread_id = :tid, '
                'subject = if_not_exists(subject, :subject), '
                'last_message_at = :now, '
                'updated_at = :now, '
                'inbox_id = :inbox_id, '
                'GSI4_PK = :gsi4_pk, '
                'GSI4_SK = :gsi4_sk '
                'ADD message_count :one, '
                'participants :sender_set, '
                'message_ids :msg_set'
            ),
            ExpressionAttributeValues={
                ':tid': thread_id,
                ':subject': subject,
                ':now': timestamp_ms,
                ':inbox_id': inbox_id,
                ':one': 1,
                ':sender_set': {sender},
                ':msg_set': {message_id},
                ':gsi4_pk': f'THR#{thread_id}',
                ':gsi4_sk': f'MSG#{timestamp_ms}#{message_id}',
            }
        )
    except Exception as e:
        logger.error(f'Failed to update thread {thread_id}: {e}')
        raise


# ═══════════════════════════════════════════════════════════════════════
# BOUNCE HANDLING
# ═══════════════════════════════════════════════════════════════════════

def _send_bounce_unknown_inbox(ses_message_id: str, sender: str, recipient: str):
    """
    Send an SMTP bounce notification for an unknown inbox address.

    This tells the sending mail server that the address doesn't exist,
    which is important for preventing indefinite retry loops.
    """
    try:
        ses_v1.send_bounce(
            OriginalMessageId=ses_message_id,
            BounceSender=f'mailer-daemon@agentmail.dev',
            MessageDsn={
                'ReportingMta': 'dns; agentmail.dev',
                'ArrivalDate': time.strftime('%a, %d %b %Y %H:%M:%S %z'),
            },
            BouncedRecipientInfoList=[
                {
                    'Recipient': sender,
                    'RecipientArn': '',
                    'BounceType': 'DoesNotExist',
                    'RecipientDsnFields': {
                        'FinalRecipient': recipient,
                        'Action': 'failed',
                        'Status': '5.1.1',  # Mailbox does not exist
                        'DiagnosticCode': f'smtp; 550 5.1.1 The email account {recipient} does not exist.',
                    }
                }
            ]
        )
        logger.info(f'Sent bounce for unknown inbox {recipient} to {sender}')
    except Exception as e:
        logger.error(f'Failed to send bounce for {recipient}: {e}')


def _send_bounce(ses_message_id: str, sender: str, reasons: list[str]):
    """Send a bounce for rejected messages (virus, DMARC policy, etc.)."""
    try:
        ses_v1.send_bounce(
            OriginalMessageId=ses_message_id,
            BounceSender='mailer-daemon@agentmail.dev',
            MessageDsn={
                'ReportingMta': 'dns; agentmail.dev',
                'ArrivalDate': time.strftime('%a, %d %b %Y %H:%M:%S %z'),
            },
            BouncedRecipientInfoList=[
                {
                    'Recipient': sender,
                    'BounceType': 'ContentRejected',
                    'RecipientDsnFields': {
                        'FinalRecipient': sender,
                        'Action': 'failed',
                        'Status': '5.7.1',
                        'DiagnosticCode': f'smtp; 550 5.7.1 Message rejected: {", ".join(reasons)}',
                    }
                }
            ]
        )
    except Exception as e:
        logger.error(f'Failed to send bounce to {sender}: {e}')


def _store_processing_failure(ses_message_id: str, error: str):
    """Store a record of failed processing for manual review."""
    table = dynamodb.Table(TABLE_NAME)
    table.put_item(Item={
        'PK': 'PROCESSING_FAILURES',
        'SK': f'FAIL#{int(time.time() * 1000)}#{ses_message_id}',
        'ses_message_id': ses_message_id,
        'error': error[:1000],
        'raw_mime_s3_key': f'inbound/{ses_message_id}',
        'created_at': int(time.time() * 1000),
        'ttl': int(time.time()) + (30 * 86400)  # Auto-delete after 30 days
    })
```

---

## SES Inbound Limits

### Message Size Limits

| Limit | Value |
|---|---|
| Maximum inbound message size | 40 MB (including all MIME parts) |
| Maximum message size after S3 storage | 40 MB |
| Lambda payload limit (notification only, not full message) | 256 KB |
| S3 object size (raw MIME) | Up to 40 MB |

The Lambda notification itself is small (just headers and metadata). The full MIME body is always read from S3, not from the Lambda event payload.

### Regional Availability

SES inbound receiving is only available in three regions:

| Region | Location | Endpoint |
|---|---|---|
| `us-east-1` | N. Virginia | `inbound-smtp.us-east-1.amazonaws.com` |
| `us-west-2` | Oregon | `inbound-smtp.us-west-2.amazonaws.com` |
| `eu-west-1` | Ireland | `inbound-smtp.eu-west-1.amazonaws.com` |

This is a hard AWS limitation. Outbound SES is available in many more regions, but inbound SMTP receiving is restricted to these three.

### Receipt Rule Limits

| Resource | Limit |
|---|---|
| Active rule sets per region | 1 |
| Rules per rule set | 200 |
| Recipients per rule | 100 |
| Actions per rule | 5 |
| S3 actions per rule | 1 |
| Lambda actions per rule | 1 |
| SNS actions per rule | 1 |

### Throughput

SES inbound does not publish explicit throughput limits for message receiving. In practice:

- SES inbound can handle thousands of messages per second
- The bottleneck is typically the Lambda invocation concurrency (default 1,000 concurrent, requestable to 10,000+)
- S3 put throughput is effectively unlimited (3,500 PUT/second per prefix, partitioned automatically)
- The Lambda router should complete within 5-10 seconds per message (including S3 reads, DynamoDB writes, and Kinesis puts)

### Lambda Concurrency Planning

```
Expected inbound volume: 1M messages/day
Average processing time: 3 seconds per message
Messages per second: ~12 msg/sec (average), ~50 msg/sec (peak)
Required concurrent Lambdas: 12 * 3 = 36 (average), 50 * 3 = 150 (peak)
Reserved concurrency: 200 (with headroom)
```

---

## SES Verdicts

SES automatically evaluates every inbound message against five checks. The verdicts are included in the SES notification passed to the Lambda.

### Verdict Types

| Verdict | What It Checks | Possible Values |
|---|---|---|
| `spamVerdict` | Content-based spam scoring (similar to SpamAssassin) | `PASS`, `FAIL`, `GRAY`, `PROCESSING_FAILED`, `DISABLED` |
| `virusVerdict` | ClamAV virus scanning of message and attachments | `PASS`, `FAIL`, `GRAY`, `PROCESSING_FAILED`, `DISABLED` |
| `spfVerdict` | SPF record validation (is the sender authorized by the domain?) | `PASS`, `FAIL`, `GRAY`, `PROCESSING_FAILED`, `DISABLED`, `NONE` |
| `dkimVerdict` | DKIM signature validation (is the message signed correctly?) | `PASS`, `FAIL`, `GRAY`, `PROCESSING_FAILED`, `DISABLED`, `NONE` |
| `dmarcVerdict` | DMARC policy validation (does the message pass SPF or DKIM alignment?) | `PASS`, `FAIL`, `GRAY`, `PROCESSING_FAILED`, `DISABLED`, `NONE` |

### Verdict Values Explained

| Value | Meaning |
|---|---|
| `PASS` | The check passed successfully |
| `FAIL` | The check failed (message is suspicious or forged) |
| `GRAY` | The check returned a gray/neutral result (e.g., SPF softfail) |
| `NONE` | No record exists for this check (e.g., domain has no SPF record) |
| `PROCESSING_FAILED` | SES could not perform the check (internal error) |
| `DISABLED` | The check was disabled (ScanEnabled=false in receipt rule) |

### AgentMail Verdict Policy

```python
VERDICT_POLICY = {
    # Virus: always reject (never deliver malware to AI agents)
    'virus': {
        'FAIL': 'reject',
        'GRAY': 'flag',
        'PROCESSING_FAILED': 'accept',  # Don't block on SES internal errors
    },

    # Spam: accept but flag (AI agents may want to see spam patterns)
    'spam': {
        'FAIL': 'flag',
        'GRAY': 'accept',
        'PROCESSING_FAILED': 'accept',
    },

    # SPF: accept but flag (many legitimate senders have broken SPF)
    'spf': {
        'FAIL': 'flag',
        'GRAY': 'accept',
        'NONE': 'accept',
        'PROCESSING_FAILED': 'accept',
    },

    # DKIM: accept but flag
    'dkim': {
        'FAIL': 'flag',
        'GRAY': 'accept',
        'NONE': 'accept',
        'PROCESSING_FAILED': 'accept',
    },

    # DMARC: honor the domain's published policy
    'dmarc': {
        'FAIL': 'check_policy',  # Reject if domain policy is "reject"
        'GRAY': 'accept',
        'NONE': 'accept',
        'PROCESSING_FAILED': 'accept',
    },
}
```

For AI agents, we default to a permissive policy: accept almost everything, flag suspicious messages with verdict metadata, and let the agent (or the agent's owner) decide what to do. The only hard rejections are virus detections and DMARC `reject` policy violations.

---

## Address Scheme Design

AgentMail needs to map incoming email addresses to virtual inboxes. There are two approaches, and we support both.

### Approach 1: Encoded Inbox ID in Local Part

The platform domain uses a predictable address format that embeds the inbox ID:

```
Format: {inbox_id}@agentmail.dev
Example: inbox_a1b2c3d4e5@agentmail.dev

Alternatively with a prefix:
Format: {prefix}-{inbox_id}@agentmail.dev
Example: agent-inbox_a1b2c3d4e5@agentmail.dev
```

**Advantages:**
- No database lookup needed to resolve (parse the address to extract inbox ID)
- Guaranteed unique (inbox IDs are globally unique)
- Infinite inboxes per domain with zero configuration

**Disadvantages:**
- Ugly addresses (not human-friendly)
- Exposes internal IDs in the address
- Can't change inbox ID without changing address

**Resolution logic:**

```python
def resolve_from_encoded_address(address: str) -> Optional[str]:
    """Extract inbox_id from an encoded address."""
    local_part = address.split('@')[0]

    # Direct inbox ID
    if local_part.startswith('inbox_'):
        return local_part  # "inbox_a1b2c3d4e5"

    # Prefixed format
    if '-inbox_' in local_part:
        return local_part.split('-', 1)[1]  # "agent-inbox_a1b2c3d4e5" → "inbox_a1b2c3d4e5"

    return None
```

### Approach 2: Custom Aliases

Customers on custom domains (and optionally on the platform domain) can assign human-readable addresses to inboxes:

```
Alias: support@acme.com → inbox_a1b2c3d4e5
Alias: sales@acme.com → inbox_f6g7h8i9j0
Alias: agent-42@agentmail.dev → inbox_k1l2m3n4o5
```

**Advantages:**
- Human-friendly addresses
- Multiple aliases per inbox
- Address is decoupled from inbox ID

**Disadvantages:**
- Requires database lookup on every inbound message (GSI2)
- Must validate uniqueness when creating aliases
- Slightly higher inbound latency (but DynamoDB single-digit ms makes this negligible)

**Resolution logic:**

```python
def resolve_from_alias(table, address: str) -> Optional[dict]:
    """Look up inbox by alias address using GSI2."""
    response = table.query(
        IndexName='GSI2',
        KeyConditionExpression=Key('GSI2_PK').eq(f'ADDR#{address.lower()}'),
        Limit=1
    )
    if response['Items']:
        return response['Items'][0]
    return None
```

### Combined Resolution Strategy

The router Lambda tries both approaches in order:

```python
def resolve_recipient(table, address: str) -> Optional[dict]:
    """
    Resolve a recipient address to an inbox.

    Order:
    1. Try encoded inbox ID extraction (fast, no DB)
    2. Try alias lookup (GSI2)
    3. Try domain catch-all
    4. Give up and bounce
    """
    address = address.lower().strip()
    local_part, domain = address.split('@', 1)

    # 1. Encoded inbox ID (platform domain only)
    if domain == 'agentmail.dev':
        inbox_id = resolve_from_encoded_address(address)
        if inbox_id:
            # Still need to verify inbox exists
            response = table.query(
                IndexName='GSI2',
                KeyConditionExpression=Key('GSI2_PK').eq(f'ADDR#{address}'),
                Limit=1
            )
            if response['Items']:
                return response['Items'][0]

    # 2. Alias lookup
    inbox = resolve_from_alias(table, address)
    if inbox:
        return inbox

    # 3. Domain catch-all
    response = table.query(
        IndexName='GSI6',
        KeyConditionExpression=Key('GSI6_PK').eq(f'DOMAIN#{domain}'),
        Limit=1
    )
    if response['Items'] and response['Items'][0].get('catch_all_inbox_id'):
        item = response['Items'][0]
        return {
            'inbox_id': item['catch_all_inbox_id'],
            'org_id': item['org_id'],
            'pod_id': item.get('pod_id'),
            'domain_id': item.get('domain_id'),
        }

    # 4. No match
    return None
```

### Sub-Addressing (Plus Addressing)

We support plus addressing (`inbox+tag@domain.com`) for message routing and filtering:

```python
def normalize_address(address: str) -> tuple[str, Optional[str]]:
    """
    Normalize address and extract sub-address tag.

    inbox+tag@domain.com → (inbox@domain.com, tag)
    inbox@domain.com → (inbox@domain.com, None)
    """
    local_part, domain = address.lower().split('@', 1)

    tag = None
    if '+' in local_part:
        local_part, tag = local_part.split('+', 1)

    return f'{local_part}@{domain}', tag
```

The tag is stored as metadata on the message and can be used by agents for routing (e.g., `support+billing@acme.com` routes to the `support` inbox with a `billing` tag).
