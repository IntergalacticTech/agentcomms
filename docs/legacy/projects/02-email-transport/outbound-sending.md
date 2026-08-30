# Outbound Email Sending

## Overview

Every email sent by an AI agent through AgentMail flows through Amazon SES v2. The sending pipeline starts when an agent calls `POST /v1/inboxes/{id}/messages`, passes through a send queue for reliability and backpressure, constructs a MIME message, and calls SES. Event destinations report back on delivery success, bounces, and complaints.

---

## Table of Contents

- [Sending Flow](#sending-flow)
- [SES v2 API Operations](#ses-v2-api-operations)
- [MIME Message Construction](#mime-message-construction)
- [Configuration Sets](#configuration-sets)
- [Event Destinations](#event-destinations)
- [Sending Limits and Quotas](#sending-limits-and-quotas)
- [Burst Rate Handling](#burst-rate-handling)
- [Multi-Region Sending Strategy](#multi-region-sending-strategy)
- [Complete Code Example](#complete-code-example)
- [Error Handling](#error-handling)

---

## Sending Flow

```
Agent API Call
POST /v1/inboxes/{inbox_id}/messages
{
  "to": ["recipient@example.com"],
  "subject": "Your order has shipped",
  "text": "Plain text body...",
  "html": "<html>Rich body...</html>",
  "attachments": ["att_01H8X9ABC123"]
}
     │
     ▼
┌────────────────────────────────┐
│  API Lambda Handler            │
│  1. Validate request           │
│  2. Check inbox exists         │
│  3. Check sender is verified   │
│  4. Check rate limits (Redis)  │
│  5. Check suppression list     │
│  6. Write to DynamoDB          │
│     (status = "queued")        │
│  7. Enqueue to SQS send-queue  │
│  8. Return 202 Accepted        │
│     {message_id: "msg_xxx"}    │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  SQS: agentmail-send-queue     │
│  - FIFO queue (per inbox)      │
│  - Visibility timeout: 120s    │
│  - DLQ after 3 retries         │
│  - Max receive count: 3        │
└────────────┬───────────────────┘
             │
             ▼
┌────────────────────────────────┐
│  Lambda: send-worker           │
│  1. Read message from DynamoDB │
│  2. Fetch attachment bytes     │
│     from S3 if needed          │
│  3. Build MIME message         │
│  4. Determine config set       │
│     (org_id → config set name) │
│  5. Determine IP pool          │
│  6. Call SES SendRawEmail      │
│  7. On success:                │
│     - Update status = "sent"   │
│     - Store SES Message-ID     │
│     - Publish message.sent     │
│       to Kinesis               │
│  8. On throttle:               │
│     - Raise exception          │
│     - Message returns to SQS   │
│     - Visibility timeout       │
│       backoff: 10s, 30s, 60s   │
│  9. On permanent failure:      │
│     - Update status = "failed" │
│     - Publish message.bounced  │
│       to Kinesis               │
└────────────────────────────────┘
```

### Why SQS in the middle?

Decoupling the API response from the SES call provides three benefits:

1. **Fast API response.** The agent gets a `202 Accepted` with a `message_id` immediately. The actual send happens asynchronously.
2. **Backpressure.** If SES throttles us (burst rate exceeded or account-level throttle), messages queue up and retry automatically.
3. **Deduplication.** FIFO queue with deduplication ID prevents double-sends on Lambda retries.

---

## SES v2 API Operations

AgentMail uses three SES v2 API operations depending on the use case.

### SendEmail (Simple)

Used for messages with text and/or HTML body, no attachments, standard headers.

```python
import boto3

ses_v2 = boto3.client('sesv2', region_name='us-east-1')

response = ses_v2.send_email(
    FromEmailAddress='agent-42@acme.agentmail.dev',
    Destination={
        'ToAddresses': ['recipient@example.com'],
        'CcAddresses': [],
        'BccAddresses': []
    },
    Content={
        'Simple': {
            'Subject': {
                'Data': 'Your order has shipped',
                'Charset': 'UTF-8'
            },
            'Body': {
                'Text': {
                    'Data': 'Your order #12345 has shipped via USPS.',
                    'Charset': 'UTF-8'
                },
                'Html': {
                    'Data': '<html><body><h1>Shipped!</h1><p>Order #12345...</p></body></html>',
                    'Charset': 'UTF-8'
                }
            },
            'Headers': [
                {'Name': 'X-AgentMail-Org', 'Value': 'org_xxx'},
                {'Name': 'X-AgentMail-Inbox', 'Value': 'inbox_xxx'},
            ]
        }
    },
    ConfigurationSetName='org-acme-config',
    ListManagementOptions={
        'ContactListName': 'agentmail-global',
        'TopicName': 'transactional'
    },
    Tags=[
        {'Name': 'org_id', 'Value': 'org_xxx'},
        {'Name': 'inbox_id', 'Value': 'inbox_xxx'},
        {'Name': 'tenant_tier', 'Value': 'standard'}
    ]
)

ses_message_id = response['MessageId']
# e.g., "0100018a1b2c3d4e-f5g6h7i8-j9k0-l1m2-n3o4-p5q6r7s8t9u0-000000"
```

**When to use:** Quick sends where we control the full message body and don't need custom MIME headers or attachments.

### SendRawEmail (Full Control)

Used for messages with attachments, custom headers (`In-Reply-To`, `References` for threading), multipart MIME, or any case where we need full control over the message structure.

```python
response = ses_v2.send_email(
    FromEmailAddress='agent-42@acme.agentmail.dev',
    Destination={
        'ToAddresses': ['recipient@example.com']
    },
    Content={
        'Raw': {
            'Data': raw_mime_bytes  # Complete MIME message as bytes
        }
    },
    ConfigurationSetName='org-acme-config',
    Tags=[
        {'Name': 'org_id', 'Value': 'org_xxx'},
        {'Name': 'inbox_id', 'Value': 'inbox_xxx'}
    ]
)
```

**When to use:** Almost all AgentMail sends, because we always set `Message-ID`, `In-Reply-To`, and `References` headers for thread tracking.

### SendBulkEmail

Used for broadcasting the same template to many recipients (e.g., an agent sending a newsletter to a list). Each recipient gets individual delivery tracking.

```python
response = ses_v2.send_bulk_email(
    FromEmailAddress='newsletter@acme.agentmail.dev',
    DefaultContent={
        'Template': {
            'TemplateName': 'weekly-digest-v2',
            'TemplateData': '{"company": "Acme Corp", "week": "2026-W15"}'
        }
    },
    ConfigurationSetName='org-acme-config',
    BulkEmailEntries=[
        {
            'Destination': {
                'ToAddresses': ['user1@example.com']
            },
            'ReplacementEmailContent': {
                'ReplacementTemplate': {
                    'ReplacementTemplateData': '{"name": "Alice", "unsubscribe_url": "..."}'
                }
            }
        },
        {
            'Destination': {
                'ToAddresses': ['user2@example.com']
            },
            'ReplacementEmailContent': {
                'ReplacementTemplate': {
                    'ReplacementTemplateData': '{"name": "Bob", "unsubscribe_url": "..."}'
                }
            }
        }
        # Up to 50 entries per call
    ],
    DefaultTags=[
        {'Name': 'org_id', 'Value': 'org_xxx'},
        {'Name': 'campaign_id', 'Value': 'camp_xxx'}
    ]
)

# Response contains per-recipient status
for entry in response['BulkEmailEntryResults']:
    if entry['Status'] == 'SUCCESS':
        print(f"Sent: {entry['MessageId']}")
    else:
        print(f"Failed: {entry['Error']}")
```

**Limit:** 50 recipients per `SendBulkEmail` call. For larger sends, chunk into batches of 50 and parallelize.

---

## MIME Message Construction

AgentMail builds RFC 5322-compliant MIME messages for every outbound email. The MIME structure depends on what the agent provides.

### Structure Decision Tree

```
Agent provides:            MIME structure:
─────────────────          ──────────────
text only              →   text/plain
html only              →   text/html
text + html            →   multipart/alternative
                             ├── text/plain
                             └── text/html
text + html + files    →   multipart/mixed
                             ├── multipart/alternative
                             │     ├── text/plain
                             │     └── text/html
                             └── application/pdf (attachment)
                             └── image/png (attachment)
text + inline images   →   multipart/related
                             ├── multipart/alternative
                             │     ├── text/plain
                             │     └── text/html (with cid: refs)
                             └── image/png (Content-ID: <img001>)
```

### Complete MIME Builder

```python
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders
from email.utils import formataddr, formatdate, make_msgid
from typing import Optional
import hashlib
import base64


def build_mime_message(
    from_address: str,
    from_display_name: str,
    to_addresses: list[str],
    cc_addresses: list[str],
    bcc_addresses: list[str],
    subject: str,
    text_body: Optional[str],
    html_body: Optional[str],
    attachments: list[dict],        # [{filename, content_type, data_bytes}]
    inline_images: list[dict],      # [{filename, content_type, data_bytes, content_id}]
    in_reply_to: Optional[str],     # Message-ID of parent
    references: list[str],          # List of Message-IDs in thread chain
    custom_headers: dict,
    org_id: str,
    inbox_id: str,
    message_id: str,                # Our internal message ID
) -> bytes:
    """
    Build a complete MIME message suitable for SES SendRawEmail.

    Returns the raw bytes of the complete MIME message.
    """

    has_text = text_body is not None
    has_html = html_body is not None
    has_attachments = len(attachments) > 0
    has_inline = len(inline_images) > 0

    # ── Build the body part ──────────────────────────────────────────

    if has_text and not has_html:
        body_part = MIMEText(text_body, 'plain', 'utf-8')
    elif has_html and not has_text:
        body_part = MIMEText(html_body, 'html', 'utf-8')
    elif has_text and has_html:
        body_part = MIMEMultipart('alternative')
        body_part.attach(MIMEText(text_body, 'plain', 'utf-8'))
        body_part.attach(MIMEText(html_body, 'html', 'utf-8'))
    else:
        # Neither text nor HTML -- empty body
        body_part = MIMEText('', 'plain', 'utf-8')

    # ── Wrap with inline images if present ───────────────────────────

    if has_inline:
        related_part = MIMEMultipart('related')
        related_part.attach(body_part)
        for img in inline_images:
            mime_image = MIMEImage(img['data_bytes'])
            mime_image.add_header('Content-ID', f'<{img["content_id"]}>')
            mime_image.add_header(
                'Content-Disposition', 'inline',
                filename=img['filename']
            )
            related_part.attach(mime_image)
        body_part = related_part

    # ── Wrap with attachments if present ─────────────────────────────

    if has_attachments:
        msg = MIMEMultipart('mixed')
        msg.attach(body_part)
        for att in attachments:
            maintype, subtype = att['content_type'].split('/', 1)
            part = MIMEBase(maintype, subtype)
            part.set_payload(att['data_bytes'])
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition', 'attachment',
                filename=att['filename']
            )
            # Add Content-ID for potential cross-referencing
            content_id = hashlib.md5(att['filename'].encode()).hexdigest()[:12]
            part.add_header('Content-ID', f'<att-{content_id}>')
            msg.attach(part)
    else:
        msg = body_part
        # If body_part is not a MIMEMultipart, we need to add headers to it
        # If it is, headers go on the outer wrapper

    # ── Set standard headers ─────────────────────────────────────────

    # Generate a globally unique Message-ID using our domain
    domain = from_address.split('@')[1]
    rfc_message_id = f'<{message_id}@{domain}>'

    msg['From'] = formataddr((from_display_name, from_address))
    msg['To'] = ', '.join(to_addresses)
    if cc_addresses:
        msg['Cc'] = ', '.join(cc_addresses)
    # BCC is intentionally omitted from headers (SES handles via Destination)
    msg['Subject'] = subject
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = rfc_message_id
    msg['MIME-Version'] = '1.0'

    # ── Threading headers ────────────────────────────────────────────

    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = ' '.join(references)

    # ── AgentMail tracking headers ───────────────────────────────────

    msg['X-AgentMail-Org-ID'] = org_id
    msg['X-AgentMail-Inbox-ID'] = inbox_id
    msg['X-AgentMail-Message-ID'] = message_id

    # ── Custom headers from the agent ────────────────────────────────

    for header_name, header_value in custom_headers.items():
        # Only allow X-* custom headers to prevent header injection
        if header_name.startswith('X-'):
            msg[header_name] = header_value

    # ── Auto-generated headers for deliverability ────────────────────

    # List-Unsubscribe (required by Gmail/Yahoo for bulk senders)
    msg['List-Unsubscribe'] = f'<mailto:unsubscribe-{inbox_id}@{domain}>'
    msg['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'

    return msg.as_bytes()
```

### Attachment Size Limits

| Constraint | Limit |
|---|---|
| SES maximum message size (after encoding) | 40 MB |
| AgentMail per-attachment limit | 25 MB |
| AgentMail total message size limit | 35 MB (leaves room for base64 expansion) |
| Base64 expansion factor | ~1.37x (3 bytes become 4 characters) |
| Practical max attachment size (single) | ~25 MB raw = ~34 MB encoded |

### Character Encoding

All text parts use UTF-8. Subject lines with non-ASCII characters are automatically encoded by Python's `email` library using RFC 2047 encoded-word syntax (e.g., `=?utf-8?q?Re=3A_=C3=9Cber_Important?=`).

---

## Configuration Sets

Every organization gets a dedicated SES configuration set. This is the central mechanism for per-tenant tracking, IP pool assignment, and event routing.

### Configuration Set Creation

When an organization is created, we provision a configuration set:

```python
ses_v2 = boto3.client('sesv2')

def create_org_config_set(org_id: str, org_name: str, tier: str):
    config_set_name = f'agentmail-{org_id}'

    ses_v2.create_configuration_set(
        ConfigurationSetName=config_set_name,
        TrackingOptions={
            'CustomRedirectDomain': 'track.agentmail.dev',
            # Used for open/click tracking if enabled
        },
        DeliveryOptions={
            'TlsPolicy': 'REQUIRE',
            'SendingPoolName': _get_pool_for_tier(tier),
            # 'MaxDeliverySeconds': 300  # Optional: max time SES will retry
        },
        ReputationOptions={
            'ReputationMetricsEnabled': True,
            'LastFreshStart': datetime.utcnow()
        },
        SendingOptions={
            'SendingEnabled': True
        },
        SuppressionOptions={
            'SuppressedReasons': ['BOUNCE', 'COMPLAINT']
        },
        VdmOptions={
            'DashboardOptions': {
                'EngagementMetrics': 'ENABLED'
            },
            'GuardianOptions': {
                'OptimizedSharedDelivery': 'ENABLED'
            }
        },
        Tags=[
            {'Key': 'org_id', 'Value': org_id},
            {'Key': 'org_name', 'Value': org_name},
            {'Key': 'tier', 'Value': tier},
            {'Key': 'managed_by', 'Value': 'agentmail'}
        ]
    )

    # Add event destinations
    _add_event_destinations(config_set_name, org_id)

    return config_set_name


def _get_pool_for_tier(tier: str) -> str:
    """Map pricing tier to SES sending pool."""
    return {
        'free': 'ses-shared-pool',           # SES shared IPs (no cost)
        'standard': 'agentmail-standard',     # 2-4 dedicated IPs shared across paid tenants
        'premium': 'agentmail-premium',       # Dedicated IPs per tenant (provisioned separately)
        'enterprise': 'agentmail-enterprise', # Per-tenant dedicated IPs
    }.get(tier, 'ses-shared-pool')
```

### Event Destinations

Each configuration set gets three event destinations -- one for each SNS topic:

```python
def _add_event_destinations(config_set_name: str, org_id: str):
    # Bounce notifications
    ses_v2.create_configuration_set_event_destination(
        ConfigurationSetName=config_set_name,
        EventDestinationName='bounces',
        EventDestination={
            'Enabled': True,
            'MatchingEventTypes': ['BOUNCE', 'REJECT'],
            'SnsDestination': {
                'TopicArn': f'arn:aws:sns:us-east-1:{ACCOUNT_ID}:agentmail-bounces'
            }
        }
    )

    # Complaint notifications
    ses_v2.create_configuration_set_event_destination(
        ConfigurationSetName=config_set_name,
        EventDestinationName='complaints',
        EventDestination={
            'Enabled': True,
            'MatchingEventTypes': ['COMPLAINT'],
            'SnsDestination': {
                'TopicArn': f'arn:aws:sns:us-east-1:{ACCOUNT_ID}:agentmail-complaints'
            }
        }
    )

    # Delivery and send notifications
    ses_v2.create_configuration_set_event_destination(
        ConfigurationSetName=config_set_name,
        EventDestinationName='deliveries',
        EventDestination={
            'Enabled': True,
            'MatchingEventTypes': [
                'SEND',
                'DELIVERY',
                'DELIVERY_DELAY',
                'OPEN',     # If tracking enabled
                'CLICK',    # If tracking enabled
            ],
            'SnsDestination': {
                'TopicArn': f'arn:aws:sns:us-east-1:{ACCOUNT_ID}:agentmail-deliveries'
            }
        }
    )
```

### SNS Topic Processing

Each SNS topic triggers a Lambda that processes the SES event notification:

```python
# Lambda: ses-event-processor
# Triggered by SNS topics: agentmail-bounces, agentmail-complaints, agentmail-deliveries

def handler(event, context):
    for record in event['Records']:
        sns_message = json.loads(record['Sns']['Message'])
        event_type = sns_message['eventType']
        mail = sns_message['mail']

        ses_message_id = mail['messageId']
        org_id = _extract_tag(mail['tags'], 'org_id')
        inbox_id = _extract_tag(mail['tags'], 'inbox_id')

        if event_type == 'Bounce':
            bounce = sns_message['bounce']
            bounce_type = bounce['bounceType']       # 'Permanent' or 'Transient'
            bounce_subtype = bounce['bounceSubType']  # 'General', 'NoEmail', 'Suppressed', etc.

            for recipient in bounce['bouncedRecipients']:
                address = recipient['emailAddress']
                diagnostic = recipient.get('diagnosticCode', '')

                if bounce_type == 'Permanent':
                    # Add to suppression list
                    _add_to_suppression_list(org_id, address, 'bounce', diagnostic)
                    # Update message status
                    _update_message_status(ses_message_id, 'bounced', {
                        'bounce_type': bounce_type,
                        'bounce_subtype': bounce_subtype,
                        'diagnostic': diagnostic
                    })
                else:
                    # Transient bounce -- SES will retry automatically
                    _update_message_status(ses_message_id, 'delayed', {
                        'bounce_type': bounce_type,
                        'diagnostic': diagnostic
                    })

                # Publish event to Kinesis
                _publish_event('message.bounced', org_id, inbox_id, {
                    'message_id': ses_message_id,
                    'recipient': address,
                    'bounce_type': bounce_type,
                    'bounce_subtype': bounce_subtype,
                    'diagnostic': diagnostic
                })

                # Increment per-tenant bounce counter (for reputation monitoring)
                _increment_bounce_counter(org_id)

        elif event_type == 'Complaint':
            complaint = sns_message['complaint']
            feedback_type = complaint.get('complaintFeedbackType', 'unknown')

            for recipient in complaint['complainedRecipients']:
                address = recipient['emailAddress']

                # Always suppress on complaint -- this is critical
                _add_to_suppression_list(org_id, address, 'complaint', feedback_type)
                _update_message_status(ses_message_id, 'complained')

                _publish_event('message.complained', org_id, inbox_id, {
                    'message_id': ses_message_id,
                    'recipient': address,
                    'feedback_type': feedback_type
                })

                _increment_complaint_counter(org_id)

        elif event_type == 'Delivery':
            delivery = sns_message['delivery']
            _update_message_status(ses_message_id, 'delivered', {
                'smtp_response': delivery.get('smtpResponse', ''),
                'processing_time_ms': delivery.get('processingTimeMillis', 0)
            })

            _publish_event('message.delivered', org_id, inbox_id, {
                'message_id': ses_message_id,
                'recipients': delivery['recipients'],
                'processing_time_ms': delivery.get('processingTimeMillis', 0)
            })

        elif event_type == 'Send':
            _update_message_status(ses_message_id, 'sent')

        elif event_type == 'DeliveryDelay':
            delay = sns_message['deliveryDelay']
            _update_message_status(ses_message_id, 'delayed', {
                'delay_type': delay['delayType'],
                'expiration_time': delay['expirationTime']
            })
```

---

## Event Destinations

### Complete Event Type Reference

| SES Event Type | AgentMail Event | Description |
|---|---|---|
| `SEND` | `message.sent` | SES accepted the message for delivery |
| `DELIVERY` | `message.delivered` | Message delivered to recipient's mail server |
| `BOUNCE` (Permanent) | `message.bounced` | Hard bounce -- address does not exist |
| `BOUNCE` (Transient) | `message.delayed` | Soft bounce -- mailbox full, server down |
| `COMPLAINT` | `message.complained` | Recipient marked as spam (via ISP feedback loop) |
| `REJECT` | `message.rejected` | SES rejected -- virus detected or suppressed address |
| `DELIVERY_DELAY` | `message.delayed` | Delivery delayed beyond initial attempt |
| `OPEN` | `message.opened` | Recipient opened the email (tracking pixel, if enabled) |
| `CLICK` | `message.clicked` | Recipient clicked a tracked link (if enabled) |
| `RENDERING_FAILURE` | (internal alert) | SES template rendering failed |
| `SUBSCRIPTION` | (internal) | List-Unsubscribe action |

### Event Flow Architecture

```
SES sends email
     │
     ▼
Configuration Set (per-org)
     │
     ├── SNS Topic: agentmail-bounces
     │        │
     │        ▼
     │   Lambda: ses-event-processor
     │        │
     │        ├── Update DynamoDB message status
     │        ├── Update per-tenant bounce counter (CloudWatch)
     │        ├── Update suppression list (DynamoDB)
     │        └── Publish to Kinesis (message.bounced)
     │
     ├── SNS Topic: agentmail-complaints
     │        │
     │        ▼
     │   Lambda: ses-event-processor
     │        │
     │        ├── Update DynamoDB message status
     │        ├── Update per-tenant complaint counter (CloudWatch)
     │        ├── Suppress recipient address immediately
     │        └── Publish to Kinesis (message.complained)
     │
     └── SNS Topic: agentmail-deliveries
              │
              ▼
         Lambda: ses-event-processor
              │
              ├── Update DynamoDB message status
              └── Publish to Kinesis (message.delivered / message.sent)
```

---

## Sending Limits and Quotas

### SES Account-Level Limits

| Environment | Daily Sending Quota | Maximum Send Rate |
|---|---|---|
| **Sandbox** (new accounts) | 200 emails/day | 1 email/second |
| **Production** (default) | 50,000 emails/day | 14 emails/second |
| **Production** (after increase) | Custom (request via AWS Support) | Custom |
| **Production** (mature account) | Up to 10M+/day | 500+ emails/second |

### Moving Out of Sandbox

New SES accounts start in sandbox mode. Sandbox restrictions:

1. Can only send to verified email addresses
2. 200 emails/24-hour rolling window
3. 1 email/second send rate

To move to production, submit a request via `ses_v2.put_account_details()`:

```python
ses_v2.put_account_details(
    MailType='TRANSACTIONAL',
    WebsiteURL='https://agentmail.dev',
    ContactLanguage='EN',
    UseCaseDescription=(
        'AgentMail is an API platform that provides email inboxes for AI agents. '
        'We send transactional emails on behalf of our customers\' AI agents, including '
        'notifications, replies to human conversations, and automated correspondence. '
        'All sending is opt-in and API-driven. We implement per-tenant bounce/complaint '
        'monitoring and automatically suspend senders who exceed thresholds.'
    ),
    ProductionAccessEnabled=True,
    AdditionalContactEmailAddresses=[
        'postmaster@agentmail.dev',
        'abuse@agentmail.dev'
    ]
)
```

AWS typically reviews within 24 hours. Initial production quota is usually 50K/day.

### Requesting Quota Increases

For higher limits, use the AWS Service Quotas API:

```python
import boto3

quotas = boto3.client('service-quotas', region_name='us-east-1')

# Request daily sending quota increase
quotas.request_service_quota_increase(
    ServiceCode='ses',
    QuotaCode='L-804C8AE8',  # Daily email sending quota
    DesiredValue=500000.0     # 500K/day
)

# Request send rate increase
quotas.request_service_quota_increase(
    ServiceCode='ses',
    QuotaCode='L-AE5D8F8A',  # Sending rate (emails/second)
    DesiredValue=100.0        # 100/sec
)
```

### Per-Tenant Rate Limiting (Application Layer)

SES quotas are account-level. We enforce per-tenant limits in the application:

```python
# Redis-based per-tenant rate limiter
# Called before enqueueing to SQS

TENANT_LIMITS = {
    'free':       {'per_second': 1,   'per_minute': 10,   'per_day': 200},
    'standard':   {'per_second': 5,   'per_minute': 100,  'per_day': 10_000},
    'premium':    {'per_second': 14,  'per_minute': 500,  'per_day': 50_000},
    'enterprise': {'per_second': 50,  'per_minute': 2000, 'per_day': 200_000},
}

async def check_send_rate_limit(redis, org_id: str, tier: str) -> bool:
    """Returns True if the send is allowed, False if rate-limited."""
    limits = TENANT_LIMITS[tier]
    now = time.time()

    pipe = redis.pipeline()

    # Sliding window counters
    second_key = f'rate:{org_id}:s:{int(now)}'
    minute_key = f'rate:{org_id}:m:{int(now / 60)}'
    day_key = f'rate:{org_id}:d:{int(now / 86400)}'

    pipe.incr(second_key)
    pipe.expire(second_key, 2)
    pipe.incr(minute_key)
    pipe.expire(minute_key, 120)
    pipe.incr(day_key)
    pipe.expire(day_key, 86400 + 60)

    results = await pipe.execute()
    second_count = results[0]
    minute_count = results[2]
    day_count = results[4]

    if second_count > limits['per_second']:
        return False
    if minute_count > limits['per_minute']:
        return False
    if day_count > limits['per_day']:
        return False

    return True
```

---

## Burst Rate Handling

SES enforces a maximum send rate (emails per second). The default production rate is 14 msg/sec. When exceeded, SES returns a `ThrottlingException`.

### Backpressure Strategy

```
Send Worker Lambda
       │
       ▼
  Call SES SendRawEmail
       │
       ├── Success → Update status, return
       │
       ├── ThrottlingException →
       │     Raise exception (message returns to SQS)
       │     SQS visibility timeout provides backoff:
       │       Attempt 1: 10 seconds
       │       Attempt 2: 30 seconds
       │       Attempt 3: 60 seconds
       │       After 3 attempts → DLQ
       │
       ├── MessageRejected →
       │     Parse error:
       │     - "Email address is on the suppression list"
       │       → Mark as bounced, do not retry
       │     - "Email address is not verified"
       │       → Mark as failed, do not retry
       │     - "Sending paused"
       │       → Re-queue with 5 minute delay
       │
       └── ServiceUnavailableException →
             Transient error, re-queue automatically
```

### SQS Visibility Timeout Backoff

```python
def send_worker_handler(event, context):
    for record in event['Records']:
        body = json.loads(record['body'])
        message_id = body['message_id']
        attempt = int(record['attributes'].get('ApproximateReceiveCount', 1))

        try:
            mime_bytes = _build_mime(message_id)
            _send_via_ses(mime_bytes, body)
            _update_status(message_id, 'sent')

        except ses_v2.exceptions.ThrottlingException:
            # Calculate backoff delay
            delay = min(10 * (3 ** (attempt - 1)), 300)  # 10s, 30s, 90s, capped at 300s

            # Change visibility timeout for this specific message
            sqs = boto3.client('sqs')
            sqs.change_message_visibility(
                QueueUrl=SEND_QUEUE_URL,
                ReceiptHandle=record['receiptHandle'],
                VisibilityTimeout=delay
            )
            raise  # Let Lambda report failure so message stays in queue

        except ses_v2.exceptions.MessageRejectedException as e:
            error_msg = str(e)
            if 'suppression list' in error_msg.lower():
                _update_status(message_id, 'bounced', {'reason': 'suppression_list'})
                # Do NOT raise -- message should not retry
            elif 'not verified' in error_msg.lower():
                _update_status(message_id, 'failed', {'reason': 'sender_not_verified'})
            elif 'sending paused' in error_msg.lower():
                _update_status(message_id, 'queued', {'reason': 'account_paused'})
                raise  # Retry later
            else:
                _update_status(message_id, 'failed', {'reason': error_msg})

        except Exception as e:
            if attempt >= 3:
                _update_status(message_id, 'failed', {'reason': str(e)})
                # Message will go to DLQ
            raise
```

### Token Bucket for Burst Smoothing

To avoid hitting the SES burst limit, we use a token bucket implemented in Redis:

```python
-- Redis Lua script: token_bucket.lua
-- KEYS[1] = bucket key
-- ARGV[1] = max_tokens (burst capacity)
-- ARGV[2] = refill_rate (tokens per second)
-- ARGV[3] = now (current timestamp as float)
-- ARGV[4] = tokens_requested (usually 1)

local key = KEYS[1]
local max_tokens = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1]) or max_tokens
local last_refill = tonumber(data[2]) or now

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
local new_tokens = math.min(max_tokens, tokens + (elapsed * refill_rate))

if new_tokens >= requested then
    new_tokens = new_tokens - requested
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 300)
    return 1  -- Allowed
else
    redis.call('HMSET', key, 'tokens', new_tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 300)
    return 0  -- Denied
end
```

Usage:

```python
async def acquire_send_token(redis, org_id: str, tier: str) -> bool:
    """Attempt to acquire a send token from the per-org bucket."""
    max_rate = TENANT_LIMITS[tier]['per_second']
    result = await redis.evalsha(
        TOKEN_BUCKET_SHA,
        keys=[f'bucket:{org_id}'],
        args=[max_rate * 2, max_rate, time.time(), 1]  # burst = 2x rate
    )
    return result == 1
```

---

## Multi-Region Sending Strategy

### Why Multi-Region?

1. **Quota distribution.** Each region has independent SES quotas. Sending from 3 regions triples effective capacity.
2. **Latency.** Sending from a region closer to the recipient's mail server reduces SMTP handshake time.
3. **Resilience.** If one region's SES is degraded, traffic routes to others.

### Regional SES Endpoints

| Region | Endpoint | Use Case |
|---|---|---|
| `us-east-1` | `email.us-east-1.amazonaws.com` | Primary (North America, default) |
| `us-west-2` | `email.us-west-2.amazonaws.com` | Secondary (West Coast, Asia-Pacific) |
| `eu-west-1` | `email.eu-west-1.amazonaws.com` | Europe, GDPR-sensitive customers |
| `ap-south-1` | `email.ap-south-1.amazonaws.com` | India (if needed) |
| `eu-central-1` | `email.eu-central-1.amazonaws.com` | Germany (strict data residency) |

### Region Selection Logic

```python
def select_sending_region(
    org_id: str,
    recipient_domain: str,
    org_settings: dict
) -> str:
    """Select the optimal SES region for sending."""

    # 1. Org-level override (enterprise customers may require specific region)
    if org_settings.get('sending_region'):
        return org_settings['sending_region']

    # 2. Data residency requirements
    if org_settings.get('data_residency') == 'eu':
        return 'eu-west-1'

    # 3. Domain-based heuristic for recipient's likely location
    tld = recipient_domain.split('.')[-1]
    REGION_MAP = {
        # European TLDs
        'de': 'eu-west-1', 'fr': 'eu-west-1', 'uk': 'eu-west-1',
        'nl': 'eu-west-1', 'it': 'eu-west-1', 'es': 'eu-west-1',
        'eu': 'eu-west-1',
        # Asia-Pacific TLDs
        'jp': 'us-west-2', 'au': 'us-west-2', 'nz': 'us-west-2',
        'in': 'ap-south-1',
    }
    if tld in REGION_MAP:
        return REGION_MAP[tld]

    # 4. Load-based routing (spread across regions if primary is near quota)
    primary_usage = _get_region_usage_percent('us-east-1')
    if primary_usage > 80:
        return 'us-west-2'

    # 5. Default
    return 'us-east-1'
```

### Cross-Region SES Setup

Each region requires independent setup:

```python
def setup_ses_region(region: str, domain: str):
    """Initialize SES in a new region for sending."""
    ses = boto3.client('sesv2', region_name=region)

    # 1. Verify the sending domain in this region
    ses.create_email_identity(
        EmailIdentity=domain,
        DkimSigningAttributes={
            'DomainSigningSelector': 'agentmail',
            'DomainSigningPrivateKey': DKIM_PRIVATE_KEY
            # Use BYODKIM so all regions share the same DKIM key
            # This avoids needing separate DKIM DNS records per region
        },
        ConfigurationSetName='agentmail-default',
        Tags=[{'Key': 'managed_by', 'Value': 'agentmail'}]
    )

    # 2. Create the default configuration set
    ses.create_configuration_set(
        ConfigurationSetName='agentmail-default',
        # ... same config as primary region
    )

    # 3. Set up SNS topics (or use cross-region SNS subscriptions)
    # Option A: Regional SNS topics → Lambda in each region
    # Option B: All SNS → SQS in primary region (simpler)
```

---

## Complete Code Example

End-to-end example: receiving an API request and sending an email through SES.

```python
"""
Lambda: send-worker
Triggered by: SQS queue agentmail-send-queue
"""

import json
import time
import boto3
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.utils import formataddr, formatdate
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ses_v2 = boto3.client('sesv2', region_name='us-east-1')
dynamodb = boto3.resource('dynamodb', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')
kinesis = boto3.client('kinesis', region_name='us-east-1')
sqs = boto3.client('sqs', region_name='us-east-1')

TABLE_NAME = 'agentmail'
RAW_EMAIL_BUCKET = 'agentmail-raw-email'
ATTACHMENTS_BUCKET = 'agentmail-attachments'
SEND_QUEUE_URL = 'https://sqs.us-east-1.amazonaws.com/123456789012/agentmail-send-queue'
KINESIS_STREAM = 'agentmail-events'


def handler(event, context):
    """Process send requests from SQS."""
    table = dynamodb.Table(TABLE_NAME)

    for record in event['Records']:
        body = json.loads(record['body'])
        message_id = body['message_id']
        inbox_id = body['inbox_id']
        org_id = body['org_id']
        attempt = int(record['attributes'].get('ApproximateReceiveCount', 1))

        try:
            # ── Step 1: Fetch message details from DynamoDB ──────────
            msg_response = table.get_item(
                Key={
                    'PK': f'INB#{inbox_id}',
                    'SK': f'MSG#{body["timestamp"]}#{message_id}'
                }
            )
            msg = msg_response['Item']

            # Verify message is still in queued state (idempotency check)
            if msg['status'] != 'queued':
                logger.info(f'Message {message_id} already in state {msg["status"]}, skipping')
                continue

            # ── Step 2: Fetch inbox details for sender info ──────────
            inbox_response = table.get_item(
                Key={
                    'PK': f'ORG#{org_id}',
                    'SK': f'INB#{inbox_id}'
                }
            )
            inbox = inbox_response['Item']

            # ── Step 3: Fetch attachments from S3 ────────────────────
            attachments = []
            if msg.get('attachment_ids'):
                for att_id in msg['attachment_ids']:
                    att_response = table.get_item(
                        Key={
                            'PK': f'MSG#{message_id}',
                            'SK': f'ATT#{att_id}'
                        }
                    )
                    att = att_response['Item']
                    att_data = s3.get_object(
                        Bucket=ATTACHMENTS_BUCKET,
                        Key=att['s3_key']
                    )['Body'].read()
                    attachments.append({
                        'filename': att['filename'],
                        'content_type': att['content_type'],
                        'data_bytes': att_data
                    })

            # ── Step 4: Build MIME message ────────────────────────────
            from_address = inbox['address']
            from_name = inbox.get('display_name', '')
            to_addresses = msg['to']
            cc_addresses = msg.get('cc', [])
            subject = msg['subject']
            text_body = msg.get('text_body')
            html_body = msg.get('html_body')

            # If HTML body is stored in S3 (>4KB)
            if not html_body and msg.get('html_s3_key'):
                html_body = s3.get_object(
                    Bucket='agentmail-bodies',
                    Key=msg['html_s3_key']
                )['Body'].read().decode('utf-8')

            # Build the MIME message
            mime_bytes = build_mime_message(
                from_address=from_address,
                from_display_name=from_name,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
                bcc_addresses=msg.get('bcc', []),
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                attachments=attachments,
                inline_images=[],
                in_reply_to=msg.get('in_reply_to'),
                references=msg.get('references', []),
                custom_headers=msg.get('custom_headers', {}),
                org_id=org_id,
                inbox_id=inbox_id,
                message_id=message_id,
            )

            # ── Step 5: Determine configuration set and region ───────
            config_set = f'agentmail-{org_id}'
            # region = select_sending_region(org_id, to_addresses[0].split('@')[1], ...)

            # ── Step 6: Send via SES ─────────────────────────────────
            ses_response = ses_v2.send_email(
                FromEmailAddress=from_address,
                Destination={
                    'ToAddresses': to_addresses,
                    'CcAddresses': cc_addresses,
                    'BccAddresses': msg.get('bcc', [])
                },
                Content={
                    'Raw': {
                        'Data': mime_bytes
                    }
                },
                ConfigurationSetName=config_set,
                Tags=[
                    {'Name': 'org_id', 'Value': org_id},
                    {'Name': 'inbox_id', 'Value': inbox_id},
                    {'Name': 'message_id', 'Value': message_id}
                ]
            )

            ses_message_id = ses_response['MessageId']

            # ── Step 7: Update status to sent ────────────────────────
            table.update_item(
                Key={
                    'PK': f'INB#{inbox_id}',
                    'SK': f'MSG#{body["timestamp"]}#{message_id}'
                },
                UpdateExpression='SET #status = :status, ses_message_id = :ses_id, sent_at = :now',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={
                    ':status': 'sent',
                    ':ses_id': ses_message_id,
                    ':now': int(time.time() * 1000)
                }
            )

            # ── Step 8: Store raw MIME in S3 for archival ────────────
            s3.put_object(
                Bucket=RAW_EMAIL_BUCKET,
                Key=f'{org_id}/{inbox_id}/{message_id}.eml',
                Body=mime_bytes,
                ContentType='message/rfc822',
                ServerSideEncryption='aws:kms'
            )

            # ── Step 9: Publish event to Kinesis ─────────────────────
            kinesis.put_record(
                StreamName=KINESIS_STREAM,
                Data=json.dumps({
                    'eventId': f'evt_{message_id}',
                    'eventType': 'message.sent',
                    'timestamp': int(time.time() * 1000),
                    'orgId': org_id,
                    'inboxId': inbox_id,
                    'data': {
                        'messageId': message_id,
                        'sesMessageId': ses_message_id,
                        'to': to_addresses,
                        'subject': subject
                    }
                }),
                PartitionKey=inbox_id
            )

            logger.info(f'Sent message {message_id} via SES (SES ID: {ses_message_id})')

        except ses_v2.exceptions.TooManyRequestsException:
            logger.warning(f'SES throttle on message {message_id}, attempt {attempt}')
            _apply_backoff(record, attempt)
            raise  # Re-raise so SQS retries

        except ses_v2.exceptions.MessageRejectedException as e:
            error_msg = str(e)
            logger.error(f'SES rejected message {message_id}: {error_msg}')
            _handle_rejection(table, inbox_id, body, message_id, error_msg)
            # Do not raise -- message should not retry

        except ses_v2.exceptions.MailFromDomainNotVerifiedException as e:
            logger.error(f'Domain not verified for message {message_id}: {e}')
            _update_status(table, inbox_id, body, message_id, 'failed', {
                'reason': 'domain_not_verified',
                'error': str(e)
            })

        except ClientError as e:
            error_code = e.response['Error']['Code']
            logger.error(f'AWS error sending {message_id}: {error_code} - {e}')
            if attempt >= 3:
                _update_status(table, inbox_id, body, message_id, 'failed', {
                    'reason': error_code,
                    'error': str(e)
                })
            raise  # Let SQS retry (or DLQ after max attempts)


def _apply_backoff(record, attempt):
    """Apply exponential backoff by changing SQS visibility timeout."""
    delay = min(10 * (3 ** (attempt - 1)), 300)
    sqs.change_message_visibility(
        QueueUrl=SEND_QUEUE_URL,
        ReceiptHandle=record['receiptHandle'],
        VisibilityTimeout=delay
    )


def _handle_rejection(table, inbox_id, body, message_id, error_msg):
    """Handle permanent SES rejections."""
    reason = 'unknown'
    if 'suppression list' in error_msg.lower():
        reason = 'suppression_list'
    elif 'not verified' in error_msg.lower():
        reason = 'sender_not_verified'
    elif 'sending paused' in error_msg.lower():
        reason = 'account_paused'
        # This one should retry -- re-raise
        raise Exception('SES sending paused, will retry')

    _update_status(table, inbox_id, body, message_id, 'failed', {
        'reason': reason,
        'error': error_msg
    })


def _update_status(table, inbox_id, body, message_id, status, metadata=None):
    """Update message status in DynamoDB."""
    update_expr = 'SET #status = :status'
    expr_values = {':status': status}

    if metadata:
        update_expr += ', error_metadata = :meta'
        expr_values[':meta'] = metadata

    table.update_item(
        Key={
            'PK': f'INB#{inbox_id}',
            'SK': f'MSG#{body["timestamp"]}#{message_id}'
        },
        UpdateExpression=update_expr,
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues=expr_values
    )
```

---

## Error Handling

### Error Classification

| Error | Type | Action | Retry? |
|---|---|---|---|
| `ThrottlingException` / `TooManyRequestsException` | Transient | Backoff and retry via SQS | Yes (3x) |
| `MessageRejectedException` (suppression list) | Permanent | Mark as bounced | No |
| `MessageRejectedException` (not verified) | Permanent | Mark as failed | No |
| `MessageRejectedException` (sending paused) | Transient | Retry with long delay | Yes |
| `MailFromDomainNotVerifiedException` | Permanent | Mark as failed, alert ops | No |
| `AccountSendingPausedException` | Critical | Pause all sending, alert ops | No |
| `LimitExceededException` (daily quota) | Transient | Queue until next day or route to another region | Deferred |
| `ServiceUnavailableException` | Transient | Standard retry | Yes (3x) |
| `BadRequestException` | Permanent | Mark as failed, log for debugging | No |
| MIME construction error | Permanent | Mark as failed, log full details | No |
| S3 attachment fetch failure | Transient | Retry | Yes (3x) |
| DynamoDB write failure | Transient | Retry | Yes (3x) |

### Dead Letter Queue Processing

Messages that exhaust all retries land in the DLQ:

```python
# Lambda: send-dlq-processor
# Triggered by: SQS DLQ agentmail-send-dlq

def handler(event, context):
    for record in event['Records']:
        body = json.loads(record['body'])
        message_id = body['message_id']

        # 1. Update message status to "failed" if not already
        _update_status_to_failed(message_id)

        # 2. Publish failure event to Kinesis
        _publish_event('message.failed', body['org_id'], body['inbox_id'], {
            'message_id': message_id,
            'reason': 'max_retries_exhausted',
            'original_error': body.get('error', 'unknown')
        })

        # 3. Increment failure metric for alerting
        cloudwatch = boto3.client('cloudwatch')
        cloudwatch.put_metric_data(
            Namespace='AgentMail/Sending',
            MetricData=[{
                'MetricName': 'SendFailures',
                'Value': 1,
                'Unit': 'Count',
                'Dimensions': [
                    {'Name': 'OrgId', 'Value': body['org_id']},
                    {'Name': 'FailureType', 'Value': 'DLQ'}
                ]
            }]
        )

        # 4. Log for manual investigation
        logger.error(
            f'Message {message_id} permanently failed after all retries',
            extra={
                'org_id': body['org_id'],
                'inbox_id': body['inbox_id'],
                'message_id': message_id,
                'sqs_message_id': record['messageId'],
                'approximate_receive_count': record['attributes']['ApproximateReceiveCount']
            }
        )
```

### Suppression List Checks (Pre-Send)

Before enqueueing a message, check both SES account-level and per-tenant suppression lists:

```python
async def check_suppression(org_id: str, recipient: str) -> tuple[bool, str]:
    """
    Check if recipient is suppressed.
    Returns (is_suppressed, reason).
    """
    # 1. Check per-tenant suppression list (DynamoDB)
    table = dynamodb.Table(TABLE_NAME)
    response = table.get_item(
        Key={
            'PK': f'ORG#{org_id}',
            'SK': f'SUPPRESS#{recipient.lower()}'
        }
    )
    if 'Item' in response:
        return True, f'tenant_suppressed:{response["Item"]["reason"]}'

    # 2. Check SES account-level suppression list
    try:
        ses_v2.get_suppressed_destination(
            EmailAddress=recipient
        )
        return True, 'ses_account_suppressed'
    except ses_v2.exceptions.NotFoundException:
        pass

    return False, ''
```
