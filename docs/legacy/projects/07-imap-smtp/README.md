# IMAP/SMTP Compatibility Layer

AgentMail's primary interface is its REST API -- purpose-built for AI agents that communicate over HTTP. However, a significant portion of the email ecosystem still depends on IMAP for reading and SMTP for sending. Legacy monitoring tools, email clients, migration utilities, and some AI frameworks expect to connect to a standard mailbox over these protocols. The IMAP/SMTP compatibility layer provides a protocol translation bridge: traditional email clients connect via IMAP/SMTP, and the compatibility layer translates every operation into AgentMail's internal storage and sending APIs.

This layer is explicitly deferred to **Phase 3 (Months 7-9)** of the implementation roadmap. The REST API covers 95%+ of AI agent use cases, and building IMAP/SMTP before the core platform is stable would be premature optimization for a minority of users.

---

## Table of Contents

- [Why Phase 3](#why-phase-3)
- [IMAP Server Architecture](#imap-server-architecture)
- [SMTP Server Architecture](#smtp-server-architecture)
- [Infrastructure](#infrastructure)
- [Authentication](#authentication)
- [Cost Estimate](#cost-estimate)
- [Risks and Mitigations](#risks-and-mitigations)

---

## Why Phase 3

### REST API Is the Primary Interface

AgentMail exists for AI agents. AI agents make HTTP requests. Every core feature -- inbox creation, message sending, receiving, threading, search, AI categorization, extraction -- is exposed through the REST API and accessed via auto-generated SDKs. The REST API is the product.

### IMAP/SMTP Serves Three Secondary Use Cases

1. **Legacy integration**: Some customers have existing systems that read email via IMAP (monitoring dashboards, CRM connectors, Zapier/Make integrations that poll IMAP). Supporting IMAP lets them connect without rewriting their integration.
2. **Email client access**: Developers debugging AI agent inboxes may want to connect Thunderbird or Apple Mail to visually inspect messages. IMAP provides this without building a custom web UI.
3. **Migration**: Customers migrating from traditional email providers (Google Workspace, Exchange) can use IMAP-based migration tools (imapsync, offlineimap) to move historical email into AgentMail inboxes.

### Why Not Earlier

- IMAP is a complex protocol. RFC 3501 (IMAP4rev1) defines dozens of commands, many with subtle semantics (FETCH partial ranges, STORE silent mode, SEARCH with nested criteria). Building and testing a correct implementation takes 4-6 weeks of focused engineering.
- The underlying storage must be stable first. IMAP exposes DynamoDB metadata and S3 content through a protocol translation layer. If the storage schema changes (which it will during Phase 1-2), the IMAP layer would need constant updates.
- SMTP sending is already handled by SES through the REST API. The SMTP relay only adds an alternative submission interface, not new capability.

### Competitive Rationale

AgentMail.to offers IMAP/SMTP. To achieve feature parity, we must offer it -- but it does not need to be in the initial launch. Competitors like Mailgun and SendGrid do not offer IMAP at all, so having it at all is a differentiator in the broader market.

---

## IMAP Server Architecture

### Overview

```
Email Client (Thunderbird, Apple Mail, imapsync)
        |
        | TCP port 993 (TLS) or 143 (STARTTLS)
        v
Network Load Balancer (NLB)
        |
        | TCP passthrough
        v
ECS Fargate Service (IMAP server)
        |
        +---> DynamoDB (message metadata, flags, UIDs)
        +---> S3 (raw MIME bodies, attachments)
        +---> ElastiCache Redis (session state, UID validity cache)
        +---> OpenSearch Serverless (SEARCH command)
```

### Server Technology Options

| Option | Language | License | Pros | Cons | Recommendation |
|--------|----------|---------|------|------|----------------|
| **Stalwart Mail Server** | Rust | AGPL-3.0 / Commercial | High performance, modern codebase, pluggable backends, actively maintained, built-in JMAP support | Newer project (est. 2022), AGPL requires commercial license for SaaS | **Recommended** |
| **Dovecot** | C | LGPL-2.1 / Commercial (OX) | Industry standard, battle-tested at massive scale, extensive plugin system | Heavy footprint, complex configuration, Open-Xchange ownership adds commercial risk | Viable fallback |
| **WildDuck** | Node.js | EUPL-1.2 | Built for virtual mailboxes, MongoDB backend (easy to swap), REST API built-in | Smaller community, Node.js single-threaded performance limits | Good for prototype |
| **Custom** | Rust/Go | N/A | Full control, no licensing issues, minimal footprint | 3-6 month engineering effort for RFC compliance, ongoing maintenance burden | Not recommended |

**Decision: Stalwart Mail Server** with a custom storage backend plugin that maps to DynamoDB/S3. Stalwart's architecture cleanly separates protocol handling from storage, making it straightforward to implement a custom backend. If the AGPL license is problematic for our deployment model, we negotiate a commercial license (Stalwart offers these) or fall back to WildDuck.

### IMAP-to-Storage Mapping

Every IMAP command maps to one or more operations on AgentMail's storage layer:

| IMAP Command | Operation | Storage Mapping |
|-------------|-----------|-----------------|
| `LOGIN` | Authenticate | Redis: lookup inbox credentials → DynamoDB: validate |
| `LIST` | List mailboxes | DynamoDB: query folders for inbox (INBOX, Sent, Drafts, Trash) |
| `SELECT` | Open mailbox | DynamoDB: get mailbox stats (message count, recent, unseen, UID validity, UID next) |
| `FETCH` (headers) | Get message headers | DynamoDB: query message metadata by UID range |
| `FETCH` (body) | Get message content | S3: `GetObject` on `s3://agentmail-bodies/{org_id}/{inbox_id}/{message_id}.eml` |
| `FETCH` (partial) | Get byte range | S3: `GetObject` with `Range` header |
| `STORE +FLAGS` | Set flags (\\Seen, \\Flagged, etc.) | DynamoDB: `UpdateItem` on message metadata, set flag bits |
| `STORE -FLAGS` | Remove flags | DynamoDB: `UpdateItem` on message metadata, clear flag bits |
| `SEARCH` (simple) | Search by header/date/flag | DynamoDB: query with filter expressions on metadata GSI |
| `SEARCH` (full-text) | Search by body content | OpenSearch Serverless: full-text query on message index |
| `COPY` | Copy message to folder | DynamoDB: create new item with same S3 reference, new UID |
| `EXPUNGE` | Permanently delete | DynamoDB: `DeleteItem` + S3: `DeleteObject` (or mark for lifecycle) |
| `APPEND` | Upload message | S3: `PutObject` raw MIME + DynamoDB: create message metadata + run inbound pipeline |
| `IDLE` | Wait for new messages | Redis Pub/Sub: subscribe to inbox channel, notify on new message event |
| `NOOP` | Keepalive / check updates | Redis: check inbox notification channel for pending events |
| `CLOSE` | Close mailbox | Expunge deleted messages + release session state |
| `UID FETCH/STORE/SEARCH/COPY` | UID-based variants | Same as above but using UID instead of sequence number |

### UID Management

IMAP requires monotonically increasing UIDs per mailbox and a UID validity value that changes when UIDs are reassigned. Our mapping:

- **UID**: DynamoDB atomic counter per inbox. Each new message (inbound or APPEND) increments the counter and stores the UID on the message item. Counter stored as `INBOX#{inbox_id}#UID_NEXT` in the single table.
- **UID Validity**: Timestamp (epoch seconds) of inbox creation. Stored on the inbox item. Only changes if we ever need to rebuild the UID mapping (which should never happen in normal operation).
- **Sequence numbers**: Computed at SELECT time by ordering messages by UID. Maintained in-session in the IMAP server's memory. Not stored in DynamoDB.

### Virtual Folder Mapping

AgentMail's REST API uses labels and message states rather than IMAP folders. The IMAP layer maps standard IMAP folders to internal concepts:

| IMAP Folder | AgentMail Mapping |
|------------|-------------------|
| `INBOX` | Messages where `direction = inbound` and not archived |
| `Sent` | Messages where `direction = outbound` |
| `Drafts` | Draft items for this inbox |
| `Trash` | Messages with `deleted = true` (soft delete, before expunge) |
| `Archive` | Messages with `archived = true` |
| `[Custom]` | Labels applied to messages (read-only via IMAP, create via REST) |

### RFC 3501 Compliance Scope

**Phase 3 (initial release):**
- IMAP4rev1 (RFC 3501) -- core protocol
- STARTTLS (RFC 2595) -- encryption
- IDLE (RFC 2177) -- push notifications
- UIDPLUS (RFC 4315) -- UID EXPUNGE, APPENDUID, COPYUID
- LITERAL+ (RFC 7888) -- non-synchronizing literals
- NAMESPACE (RFC 2342) -- namespace reporting
- SPECIAL-USE (RFC 6154) -- folder type attributes

**Deferred (post-launch, only if customer demand exists):**
- CONDSTORE (RFC 7162) -- conditional STORE, mod-sequences
- QRESYNC (RFC 7162) -- quick resync after disconnect
- SORT (RFC 5256) -- server-side sorting
- THREAD (RFC 5256) -- server-side threading
- COMPRESS (RFC 4978) -- DEFLATE compression
- MOVE (RFC 6851) -- atomic move operation

### IMAP Server Configuration

```yaml
# stalwart-imap-config.yaml (conceptual)
server:
  protocol: imap
  listeners:
    - bind: "0.0.0.0:993"
      tls:
        certificate: /etc/ssl/certs/imap.agentmail.dev.pem
        key: /etc/ssl/private/imap.agentmail.dev.key
        min-version: "1.2"
    - bind: "0.0.0.0:143"
      starttls: required
      tls:
        certificate: /etc/ssl/certs/imap.agentmail.dev.pem
        key: /etc/ssl/private/imap.agentmail.dev.key

  max-connections: 10000
  timeout-idle: 1800  # 30 minutes
  timeout-auth: 60

storage:
  backend: custom-agentmail
  config:
    dynamodb-table: agentmail-single-table
    s3-bodies-bucket: agentmail-bodies
    s3-attachments-bucket: agentmail-attachments
    redis-endpoint: agentmail-cache.xxxxx.use1.cache.amazonaws.com:6379
    opensearch-endpoint: https://xxxxxxxxx.us-east-1.aoss.amazonaws.com
    aws-region: us-east-1

auth:
  backend: custom-agentmail
  # Credentials are inbox_id-based; see Authentication section
```

---

## SMTP Server Architecture

### Overview

```
Email Client / Legacy System
        |
        | TCP port 587 (STARTTLS) or 465 (Implicit TLS / SMTPS)
        v
Network Load Balancer (NLB)
        |
        | TCP passthrough
        v
ECS Fargate Service (SMTP relay - Haraka)
        |
        | Authenticated submission
        v
Haraka Plugin Pipeline
  1. auth/agentmail_auth    -- validate credentials
  2. mail_from/rewrite      -- enforce sender = inbox address
  3. rcpt_to/validate       -- validate recipient addresses
  4. queue/agentmail_ses    -- submit via SES SendRawEmail
        |
        v
Amazon SES
        |
        v
Internet (recipient MTA)
```

### Server Technology: Haraka

**Haraka** is a Node.js SMTP server designed for high-performance mail processing with a rich plugin architecture. It is the clear choice for SMTP relay:

- **Plugin architecture**: Every phase of the SMTP transaction (connection, AUTH, MAIL FROM, RCPT TO, DATA, queue) has hook points. We write 3-4 plugins to integrate with AgentMail.
- **Performance**: Handles thousands of concurrent connections. Node.js event loop is well-suited for I/O-bound SMTP work.
- **Battle-tested**: Used in production by Craigslist and other high-volume senders.
- **MIT license**: No commercial licensing concerns.
- **npm ecosystem**: Easy to integrate AWS SDK for SES submission.

We do **not** accept inbound email over SMTP. Inbound email arrives via SES Receipt Rules (the existing inbound pipeline). The SMTP server is **submission only** -- it accepts messages from authenticated clients and relays them through SES.

### Haraka Plugin: Authentication

```javascript
// plugins/auth/agentmail_auth.js
//
// Validates SMTP AUTH credentials against AgentMail's inbox credentials.
// Supports AUTH PLAIN and AUTH LOGIN mechanisms.

const { DynamoDBClient, GetItemCommand } = require('@aws-sdk/client-dynamodb');
const { createClient } = require('redis');
const crypto = require('crypto');

const dynamo = new DynamoDBClient({ region: process.env.AWS_REGION || 'us-east-1' });
const REDIS_URL = process.env.REDIS_ENDPOINT;
const TABLE_NAME = process.env.DYNAMODB_TABLE || 'agentmail-single-table';

let redis;

exports.register = function () {
  this.loginfo('AgentMail SMTP Auth plugin loaded');
  // Initialize Redis connection pool
  redis = createClient({ url: `redis://${REDIS_URL}` });
  redis.connect().catch(err => this.logerror(`Redis connect error: ${err}`));
};

exports.hook_capabilities = function (next, connection) {
  // Advertise AUTH only after STARTTLS
  if (connection.tls.enabled) {
    connection.capabilities.push('AUTH PLAIN LOGIN');
    connection.capabilities.push('AUTH=PLAIN LOGIN');
  }
  next();
};

exports.hook_unrecognized_command = function (next, connection, params) {
  // Handle AUTH command
  if (params[0].toUpperCase() !== 'AUTH') return next();

  const method = params[1].toUpperCase();
  if (method === 'PLAIN') {
    return handle_auth_plain(next, connection, params);
  } else if (method === 'LOGIN') {
    return handle_auth_login(next, connection, params);
  }
  return next(DENY, 'Unsupported auth mechanism');
};

async function handle_auth_plain(next, connection, params) {
  // AUTH PLAIN sends base64(NUL + username + NUL + password)
  const decoded = Buffer.from(params[2], 'base64').toString('utf8');
  const parts = decoded.split('\0');
  // parts[0] = authorization identity (ignored)
  // parts[1] = authentication identity (inbox_id or username)
  // parts[2] = password (API key or generated SMTP password)
  const username = parts[1];
  const password = parts[2];

  const result = await validate_credentials(username, password);
  if (result.valid) {
    connection.relaying = true;
    connection.notes.agentmail_inbox_id = result.inbox_id;
    connection.notes.agentmail_org_id = result.org_id;
    connection.notes.agentmail_from_address = result.email_address;
    return next(OK);
  }
  return next(DENY, 'Authentication failed');
}

async function validate_credentials(username, password) {
  // Step 1: Check Redis cache
  const cache_key = `smtp:auth:${username}`;
  const cached = await redis.get(cache_key);
  if (cached) {
    const entry = JSON.parse(cached);
    const hash = crypto.createHash('sha256').update(password).digest('hex');
    if (entry.password_hash === hash) {
      return { valid: true, inbox_id: entry.inbox_id, org_id: entry.org_id, email_address: entry.email_address };
    }
    return { valid: false };
  }

  // Step 2: Lookup in DynamoDB
  // Username format: inbox_id (e.g., "inb_abc123def456")
  // OR generated username (e.g., "agent-smith@agentmail.dev")
  const command = new GetItemCommand({
    TableName: TABLE_NAME,
    Key: {
      PK: { S: `INBOX#${username}` },
      SK: { S: `SMTP_CRED` }
    }
  });

  try {
    const response = await dynamo.send(command);
    if (!response.Item) return { valid: false };

    const stored_hash = response.Item.password_hash.S;
    const provided_hash = crypto.createHash('sha256').update(password).digest('hex');

    if (stored_hash !== provided_hash) return { valid: false };

    const result = {
      valid: true,
      inbox_id: response.Item.inbox_id.S,
      org_id: response.Item.org_id.S,
      email_address: response.Item.email_address.S
    };

    // Cache for 5 minutes
    await redis.setEx(cache_key, 300, JSON.stringify({
      password_hash: provided_hash,
      inbox_id: result.inbox_id,
      org_id: result.org_id,
      email_address: result.email_address
    }));

    return result;
  } catch (err) {
    connection.logerror(`DynamoDB auth lookup failed: ${err}`);
    return { valid: false };
  }
}
```

### Haraka Plugin: Sender Rewriting and DKIM Alignment

```javascript
// plugins/mail_from/agentmail_rewrite.js
//
// Ensures the MAIL FROM envelope and From header match the authenticated
// inbox's email address. This is required for DKIM alignment (the d= domain
// in the DKIM signature must match the From domain).

exports.hook_mail = function (next, connection, params) {
  const inbox_from = connection.notes.agentmail_from_address;
  if (!inbox_from) {
    return next(DENY, 'Authentication required before MAIL FROM');
  }

  const envelope_from = params[0].address();

  // Enforce: envelope sender must match the authenticated inbox address
  // OR be a verified alias on the same domain
  if (envelope_from !== inbox_from) {
    this.logwarn(`Rejecting MAIL FROM ${envelope_from} -- authenticated as ${inbox_from}`);
    return next(DENY, `Sender address must be ${inbox_from}`);
  }

  connection.notes.envelope_from = envelope_from;
  return next(OK);
};

exports.hook_data_post = function (next, connection) {
  // Verify From header matches envelope sender for DKIM alignment
  const from_header = connection.transaction.header.get_decoded('from');
  const inbox_from = connection.notes.agentmail_from_address;

  // Extract email from From header (handles "Display Name <email>" format)
  const match = from_header.match(/<([^>]+)>/) || [null, from_header.trim()];
  const header_from = match[1].toLowerCase();

  if (header_from !== inbox_from.toLowerCase()) {
    // Rewrite the From header to match the authenticated address
    // Preserve display name if present
    const display_match = from_header.match(/^([^<]*)</);
    const display_name = display_match ? display_match[1].trim() : '';
    const new_from = display_name ? `${display_name} <${inbox_from}>` : inbox_from;

    connection.transaction.remove_header('from');
    connection.transaction.add_header('From', new_from);
    this.loginfo(`Rewrote From header to ${new_from} for DKIM alignment`);
  }

  return next();
};
```

### Haraka Plugin: SES Queue Submission

```javascript
// plugins/queue/agentmail_ses.js
//
// Submits the complete SMTP transaction to SES via SendRawEmail.
// Also records the message in DynamoDB for the REST API to see.

const { SESv2Client, SendEmailCommand } = require('@aws-sdk/client-sesv2');
const { DynamoDBClient, PutItemCommand, UpdateItemCommand } = require('@aws-sdk/client-dynamodb');
const { S3Client, PutObjectCommand } = require('@aws-sdk/client-s3');
const { v4: uuidv4 } = require('uuid');

const ses = new SESv2Client({ region: process.env.AWS_REGION || 'us-east-1' });
const dynamo = new DynamoDBClient({ region: process.env.AWS_REGION || 'us-east-1' });
const s3 = new S3Client({ region: process.env.AWS_REGION || 'us-east-1' });

const TABLE_NAME = process.env.DYNAMODB_TABLE || 'agentmail-single-table';
const BODIES_BUCKET = process.env.S3_BODIES_BUCKET || 'agentmail-bodies';

exports.hook_queue = async function (next, connection) {
  const org_id = connection.notes.agentmail_org_id;
  const inbox_id = connection.notes.agentmail_inbox_id;
  const from_address = connection.notes.agentmail_from_address;
  const message_id = `msg_${uuidv4().replace(/-/g, '')}`;
  const timestamp = new Date().toISOString();

  try {
    // Step 1: Get the raw MIME message
    const raw_message = connection.transaction.message_stream;
    const chunks = [];
    for await (const chunk of raw_message) {
      chunks.push(chunk);
    }
    const raw_bytes = Buffer.concat(chunks);

    // Step 2: Store raw MIME in S3
    await s3.send(new PutObjectCommand({
      Bucket: BODIES_BUCKET,
      Key: `${org_id}/${inbox_id}/${message_id}.eml`,
      Body: raw_bytes,
      ContentType: 'message/rfc822',
      ServerSideEncryption: 'aws:kms'
    }));

    // Step 3: Extract recipients from transaction
    const recipients = connection.transaction.rcpt_to.map(r => r.address());
    const subject = connection.transaction.header.get_decoded('subject') || '(no subject)';

    // Step 4: Send via SES with org-specific configuration set
    const ses_response = await ses.send(new SendEmailCommand({
      Content: {
        Raw: {
          Data: raw_bytes
        }
      },
      FromEmailAddress: from_address,
      Destination: {
        ToAddresses: recipients
      },
      ConfigurationSetName: `org-${org_id}`,
      EmailTags: [
        { Name: 'org_id', Value: org_id },
        { Name: 'inbox_id', Value: inbox_id },
        { Name: 'message_id', Value: message_id },
        { Name: 'source', Value: 'smtp' }
      ]
    }));

    // Step 5: Record message in DynamoDB
    const ses_message_id = ses_response.MessageId;
    await dynamo.send(new PutItemCommand({
      TableName: TABLE_NAME,
      Item: {
        PK: { S: `INBOX#${inbox_id}` },
        SK: { S: `MSG#${timestamp}#${message_id}` },
        GSI1PK: { S: `ORG#${org_id}` },
        GSI1SK: { S: `MSG#${timestamp}` },
        message_id: { S: message_id },
        ses_message_id: { S: ses_message_id },
        inbox_id: { S: inbox_id },
        org_id: { S: org_id },
        direction: { S: 'outbound' },
        source: { S: 'smtp' },
        from_address: { S: from_address },
        to_addresses: { SS: recipients },
        subject: { S: subject },
        s3_key: { S: `${org_id}/${inbox_id}/${message_id}.eml` },
        status: { S: 'sent' },
        created_at: { S: timestamp },
        updated_at: { S: timestamp }
      }
    }));

    // Step 6: Update inbox message counter
    await dynamo.send(new UpdateItemCommand({
      TableName: TABLE_NAME,
      Key: {
        PK: { S: `INBOX#${inbox_id}` },
        SK: { S: 'META' }
      },
      UpdateExpression: 'ADD messages_sent :one SET updated_at = :now',
      ExpressionAttributeValues: {
        ':one': { N: '1' },
        ':now': { S: timestamp }
      }
    }));

    this.loginfo(`Message ${message_id} sent via SES (SES ID: ${ses_message_id}) for inbox ${inbox_id}`);
    return next(OK, `Message queued as ${message_id}`);

  } catch (err) {
    this.logerror(`SES send failed for inbox ${inbox_id}: ${err.message}`);

    // Differentiate between transient and permanent errors
    if (err.name === 'ThrottlingException' || err.name === 'ServiceUnavailableException') {
      return next(DENYSOFT, 'Temporary service error, please retry');
    }
    return next(DENY, `Send failed: ${err.message}`);
  }
};
```

### SMTP Ports and TLS

| Port | Protocol | TLS | Use Case |
|------|----------|-----|----------|
| **587** | SMTP Submission | STARTTLS (required) | Standard client submission. Client connects in plaintext, issues STARTTLS, then authenticates. Preferred by RFC 6409. |
| **465** | SMTPS (Implicit TLS) | TLS on connect | Client connects with TLS from the start. Re-standardized in RFC 8314. Some clients prefer this. |

Port 25 is **not exposed**. We are not an open relay and do not accept unauthenticated inbound SMTP. All inbound email flows through SES Receipt Rules.

---

## Infrastructure

### Why NLB, Not ALB

IMAP and SMTP are TCP protocols, not HTTP. Application Load Balancers (ALBs) only support HTTP/HTTPS and WebSocket. Network Load Balancers (NLBs) support raw TCP passthrough, which is required for:

- IMAP on ports 993 (TLS) and 143 (STARTTLS)
- SMTP on ports 587 (STARTTLS) and 465 (SMTPS)
- TLS termination at the server (not the load balancer), because both protocols use in-band TLS negotiation (STARTTLS) that the NLB cannot interpret

NLB operates at Layer 4 (TCP). It forwards raw TCP connections to ECS tasks. TLS is terminated by the IMAP/SMTP servers themselves, not by the NLB.

### NLB Configuration

```
NLB: agentmail-protocols-nlb
  |
  +-- Target Group: imap-tls (port 993)
  |     Protocol: TCP
  |     Health check: TCP port 993
  |     Deregistration delay: 300s (allow IMAP sessions to drain)
  |     Stickiness: enabled (IMAP sessions are stateful)
  |
  +-- Target Group: imap-starttls (port 143)
  |     Protocol: TCP
  |     Health check: TCP port 143
  |     Deregistration delay: 300s
  |     Stickiness: enabled
  |
  +-- Target Group: smtp-starttls (port 587)
  |     Protocol: TCP
  |     Health check: TCP port 587
  |     Deregistration delay: 60s (SMTP sessions are short)
  |     Stickiness: disabled (SMTP is stateless per transaction)
  |
  +-- Target Group: smtp-tls (port 465)
        Protocol: TCP
        Health check: TCP port 465
        Deregistration delay: 60s
        Stickiness: disabled
```

### ECS Fargate Services

Two separate ECS services, each with independent scaling:

**IMAP Service:**

```yaml
Service: agentmail-imap
Container:
  Image: ECR agentmail/imap-server:latest
  CPU: 1024 (1 vCPU)
  Memory: 2048 MB
  Ports: [993, 143]
  Environment:
    DYNAMODB_TABLE: agentmail-single-table
    S3_BODIES_BUCKET: agentmail-bodies
    S3_ATTACHMENTS_BUCKET: agentmail-attachments
    REDIS_ENDPOINT: agentmail-cache.xxxxx.use1.cache.amazonaws.com:6379
    OPENSEARCH_ENDPOINT: https://xxxxxxxxx.us-east-1.aoss.amazonaws.com
    AWS_REGION: us-east-1
  Secrets:
    TLS_CERT: arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:imap-tls-cert
    TLS_KEY: arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:imap-tls-key
  HealthCheck:
    command: ["CMD-SHELL", "echo | openssl s_client -connect localhost:993 -brief 2>/dev/null | grep -q CONNECTED"]
    interval: 30
    timeout: 5
    retries: 3

Scaling:
  Min: 2 (high availability)
  Max: 10
  Target tracking:
    - ECSServiceAverageCPUUtilization: 60%
    - Custom metric: imap_active_connections per task < 5000
```

**SMTP Service:**

```yaml
Service: agentmail-smtp
Container:
  Image: ECR agentmail/smtp-relay:latest
  CPU: 512 (0.5 vCPU)
  Memory: 1024 MB
  Ports: [587, 465]
  Environment:
    DYNAMODB_TABLE: agentmail-single-table
    S3_BODIES_BUCKET: agentmail-bodies
    REDIS_ENDPOINT: agentmail-cache.xxxxx.use1.cache.amazonaws.com:6379
    AWS_REGION: us-east-1
  Secrets:
    TLS_CERT: arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:smtp-tls-cert
    TLS_KEY: arn:aws:secretsmanager:us-east-1:ACCOUNT:secret:smtp-tls-key
  HealthCheck:
    command: ["CMD-SHELL", "echo QUIT | nc localhost 587 | grep -q 220"]
    interval: 30
    timeout: 5
    retries: 3

Scaling:
  Min: 2 (high availability)
  Max: 10
  Target tracking:
    - ECSServiceAverageCPUUtilization: 50%
    - Custom metric: smtp_messages_per_minute per task < 1000
```

### DNS Records

```
; IMAP server
imap.agentmail.dev.    IN A     <NLB elastic IP 1>
imap.agentmail.dev.    IN A     <NLB elastic IP 2>
imap.agentmail.dev.    IN AAAA  <NLB IPv6 1>
imap.agentmail.dev.    IN AAAA  <NLB IPv6 2>

; SMTP server
smtp.agentmail.dev.    IN A     <NLB elastic IP 1>
smtp.agentmail.dev.    IN A     <NLB elastic IP 2>
smtp.agentmail.dev.    IN AAAA  <NLB IPv6 1>
smtp.agentmail.dev.    IN AAAA  <NLB IPv6 2>

; SRV records for auto-discovery (RFC 6186)
_imap._tcp.agentmail.dev.   IN SRV 0 1 143 imap.agentmail.dev.
_imaps._tcp.agentmail.dev.  IN SRV 0 1 993 imap.agentmail.dev.
_submission._tcp.agentmail.dev. IN SRV 0 1 587 smtp.agentmail.dev.
_submissions._tcp.agentmail.dev. IN SRV 0 1 465 smtp.agentmail.dev.
```

---

## Authentication

### Credential Model

IMAP/SMTP authentication maps to AgentMail's existing identity model. Each inbox can have SMTP/IMAP credentials generated via the REST API:

```
POST /v1/inboxes/{inbox_id}/credentials
{
  "type": "smtp_imap",
  "description": "Thunderbird access for debugging"
}

Response:
{
  "id": "cred_abc123",
  "inbox_id": "inb_xyz789",
  "username": "inb_xyz789",
  "password": "sk_smtp_a1b2c3d4e5f6...",   // generated, shown once
  "imap_server": "imap.agentmail.dev",
  "imap_port": 993,
  "smtp_server": "smtp.agentmail.dev",
  "smtp_port": 587,
  "created_at": "2027-01-15T10:30:00Z"
}
```

**Username options:**
- `inbox_id` (e.g., `inb_xyz789`) -- simplest, used for programmatic access
- Email address (e.g., `agent-smith@agentmail.dev`) -- familiar for email clients

**Password options:**
- API key scoped to the inbox -- reuses existing auth
- Generated SMTP-specific password -- stored as SHA-256 hash in DynamoDB, separate from API keys for security isolation

### DynamoDB Credential Storage

```
PK: INBOX#inb_xyz789
SK: SMTP_CRED#cred_abc123
---
credential_id: cred_abc123
inbox_id: inb_xyz789
org_id: org_456
email_address: agent-smith@agentmail.dev
password_hash: sha256("sk_smtp_a1b2c3d4e5f6...")
type: smtp_imap
description: "Thunderbird access for debugging"
created_at: 2027-01-15T10:30:00Z
last_used_at: null
revoked: false
```

### Rate Limits

| Protocol | Limit | Scope |
|----------|-------|-------|
| IMAP connections | 10 concurrent per inbox | Per credential |
| IMAP FETCH | 100 messages/second per connection | Per connection |
| SMTP messages | 100/minute per inbox | Per credential |
| SMTP recipients | 50 per message | Per message |
| AUTH failures | 5 per minute, then 15-minute lockout | Per IP + username |

---

## Cost Estimate

### Baseline: 2 Fargate Tasks per Service (Minimum HA)

| Component | Calculation | Monthly Cost |
|-----------|-------------|-------------|
| NLB | 1 NLB x $16.43/mo base + LCU hours | ~$25 |
| IMAP Fargate (2 tasks) | 2 x 1 vCPU x 2 GB x 730 hrs x $0.04048/vCPU-hr + $0.004445/GB-hr | ~$66 |
| SMTP Fargate (2 tasks) | 2 x 0.5 vCPU x 1 GB x 730 hrs x $0.04048/vCPU-hr + $0.004445/GB-hr | ~$36 |
| TLS certificates | ACM (free for NLB) or Let's Encrypt | $0 |
| ECR storage | ~2 GB images | ~$0.20 |
| **Total (minimum)** | | **~$127/mo** |

### Growth: 6 Fargate Tasks per Service

| Component | Calculation | Monthly Cost |
|-----------|-------------|-------------|
| NLB | 1 NLB + higher LCU hours | ~$50 |
| IMAP Fargate (6 tasks) | 6 x 1 vCPU x 2 GB | ~$198 |
| SMTP Fargate (6 tasks) | 6 x 0.5 vCPU x 1 GB | ~$108 |
| **Total (growth)** | | **~$356/mo** |

### Full Scale: 10 Fargate Tasks per Service

| Component | Calculation | Monthly Cost |
|-----------|-------------|-------------|
| NLB | 1 NLB + high LCU hours | ~$80 |
| IMAP Fargate (10 tasks) | 10 x 1 vCPU x 2 GB | ~$330 |
| SMTP Fargate (10 tasks) | 10 x 0.5 vCPU x 1 GB | ~$180 |
| **Total (full)** | | **~$590/mo** |

Note: These costs are for the protocol servers only. DynamoDB, S3, SES, Redis, and OpenSearch costs are accounted for in the main platform cost analysis. The IMAP/SMTP layer adds incremental compute cost but reuses the same storage and transport infrastructure.

### Cost Optimization

- **Fargate Spot**: Use Spot capacity for IMAP tasks during off-peak hours (up to 70% savings). IMAP sessions can be gracefully drained during Spot interruptions using the 120-second warning.
- **ARM64 (Graviton)**: Both Stalwart (Rust) and Haraka (Node.js) run on ARM. Graviton Fargate is 20% cheaper than x86.
- **Right-sizing**: Start with smaller tasks (0.5 vCPU / 1 GB for IMAP) and scale up only if CPU or memory becomes a bottleneck.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Stalwart custom backend is harder than expected | Medium | High (delays Phase 3 by 2-4 weeks) | Prototype the backend plugin in Month 7 week 1. If blocked, fall back to WildDuck which has a simpler storage abstraction. |
| IMAP compliance gaps cause client incompatibility | Medium | Medium (specific clients may not work) | Test against top 5 clients (Thunderbird, Apple Mail, Outlook, mutt, imapsync) during development. Use IMAP compliance test suites (imaptest by Dovecot team). |
| SMTP relay abused for spam | Low | High (SES account suspension) | Rate limits per credential, envelope rewriting enforced, no unauthenticated relay, monitor SES bounce/complaint rates per SMTP-submitted messages with `source=smtp` tag. |
| NLB does not support TLS termination with STARTTLS | N/A (known constraint) | N/A | TLS terminated at server, not NLB. NLB does TCP passthrough. This is the correct architecture for STARTTLS. |
| Long-lived IMAP IDLE connections consume Fargate resources | Medium | Low (cost increase) | Enforce 30-minute IDLE timeout. Track connection count per task. Scale based on active connections, not just CPU. |
| Stalwart AGPL license incompatible with SaaS | Low | High (legal risk) | Negotiate commercial license before development begins. Budget $5K-$15K/year for commercial license. Alternative: WildDuck (EUPL) or Dovecot (LGPL). |
