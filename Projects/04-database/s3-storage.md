# S3 Storage Design

Complete S3 storage architecture for AgentMail, covering bucket structure, key patterns, lifecycle policies, encryption, access control, replication, virus scanning, and cost optimization.

---

## Bucket Structure

AgentMail uses four S3 buckets, each serving a distinct purpose with its own lifecycle and access pattern:

| Bucket | Purpose | Access Pattern | Retention |
|--------|---------|---------------|-----------|
| `agentmail-raw-email-{env}` | Raw RFC 2822 email source files | Write once, read rarely | 90 days Standard, then Glacier |
| `agentmail-attachments-{env}` | Email attachments (PDFs, images, etc.) | Write once, read via pre-signed URLs | 30 days Standard, then IA, then Glacier |
| `agentmail-bodies-{env}` | Parsed email bodies (text + HTML as JSON) | Write once, read on every message GET | 365 days Standard, then IA |
| `agentmail-exports-{env}` | Bulk export archives (ZIP/tar) | Write once, read once, delete | 7 days, then delete |

Where `{env}` is `prod`, `staging`, or `dev`.

---

## Key Patterns

### Raw Email Bucket

```
raw-email/{org_id}/{inbox_id}/{message_id}.eml

Example:
raw-email/01HXYZ1234567890ABCDEFGHJK/01HXYZ1234567890ABCDEFGHJA/01HXYZ1234567890ABCDEFGM01.eml
```

- One file per inbound email, written immediately by the SES inbound Lambda.
- The raw MIME source is preserved exactly as received (no modifications).
- Used for the `GET /inboxes/{id}/messages/{mid}/raw` endpoint and for debugging/compliance.

### Attachments Bucket

```
attachments/{org_id}/{inbox_id}/{message_id}/{attachment_id}/{filename}

Example:
attachments/01HXYZ1234567890ABCDEFGHJK/01HXYZ1234567890ABCDEFGHJA/01HXYZ1234567890ABCDEFGM01/01HXYZ1234567890ABCDEFGA01/requirements.pdf
```

- Each attachment is stored as a separate object.
- The `filename` is sanitized (stripped of path separators, limited to 255 chars, special chars replaced).
- Content-Type is set from the MIME part's declared type.
- Content-Disposition is set to `attachment; filename="..."` for download.

### Bodies Bucket

```
bodies/{org_id}/{inbox_id}/{message_id}.json

Example:
bodies/01HXYZ1234567890ABCDEFGHJK/01HXYZ1234567890ABCDEFGHJA/01HXYZ1234567890ABCDEFGM01.json
```

JSON structure:

```json
{
  "text": "Hi, I was wondering about your enterprise pricing...",
  "html": "<html><body><p>Hi, I was wondering about your enterprise pricing...</p></body></html>",
  "text_length": 52,
  "html_length": 89
}
```

- Stored separately from DynamoDB to avoid the 400 KB item limit.
- Fetched on every `GET /inboxes/{id}/messages/{mid}` call (hot path).
- The DynamoDB item stores only a `snippet` (first 200 chars of text) for list views.

### Exports Bucket

```
exports/{org_id}/{export_id}/{filename}.zip

Example:
exports/01HXYZ1234567890ABCDEFGHJK/01HXYZ1234567890ABCDEFGE01/inbox-export-2026-04-10.zip
```

- Bulk exports (e.g., download all messages in an inbox) are assembled asynchronously.
- A pre-signed URL is returned to the client for download.
- Short retention: files are deleted after 7 days.

---

## Lifecycle Policies

### Raw Email Bucket

```json
{
  "Rules": [
    {
      "ID": "raw-email-lifecycle",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "raw-email/"
      },
      "Transitions": [
        {
          "Days": 90,
          "StorageClass": "GLACIER_IR"
        },
        {
          "Days": 365,
          "StorageClass": "DEEP_ARCHIVE"
        }
      ],
      "Expiration": {
        "Days": 2555
      }
    }
  ]
}
```

| Phase | Days | Storage Class | Cost/GB/Month |
|-------|------|---------------|---------------|
| Hot | 0-90 | Standard | $0.023 |
| Warm | 90-365 | Glacier Instant Retrieval | $0.004 |
| Cold | 365-2555 | Deep Archive | $0.00099 |
| Expired | 2555+ | Deleted | $0 |

### Attachments Bucket

```json
{
  "Rules": [
    {
      "ID": "attachments-lifecycle",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "attachments/"
      },
      "Transitions": [
        {
          "Days": 30,
          "StorageClass": "STANDARD_IA"
        },
        {
          "Days": 180,
          "StorageClass": "GLACIER_IR"
        },
        {
          "Days": 730,
          "StorageClass": "DEEP_ARCHIVE"
        }
      ],
      "Expiration": {
        "Days": 2555
      }
    }
  ]
}
```

### Bodies Bucket

```json
{
  "Rules": [
    {
      "ID": "bodies-lifecycle",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "bodies/"
      },
      "Transitions": [
        {
          "Days": 365,
          "StorageClass": "STANDARD_IA"
        },
        {
          "Days": 730,
          "StorageClass": "GLACIER_IR"
        }
      ],
      "Expiration": {
        "Days": 2555
      }
    }
  ]
}
```

Bodies stay in Standard longer than other objects because they are read on every message detail request. After a year, most messages are rarely accessed.

### Exports Bucket

```json
{
  "Rules": [
    {
      "ID": "exports-cleanup",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "exports/"
      },
      "Expiration": {
        "Days": 7
      }
    }
  ]
}
```

---

## Encryption

### Default: SSE-S3

All buckets use SSE-S3 (AES-256) encryption by default. This is automatic, free, and requires no key management.

```json
{
  "ServerSideEncryptionConfiguration": {
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "AES256"
        },
        "BucketKeyEnabled": true
      }
    ]
  }
}
```

### Enterprise: SSE-KMS

Enterprise-tier organizations can opt into KMS encryption for additional control (key rotation policies, CloudTrail key usage logging, cross-account access control).

```json
{
  "ServerSideEncryptionConfiguration": {
    "Rules": [
      {
        "ApplyServerSideEncryptionByDefault": {
          "SSEAlgorithm": "aws:kms",
          "KMSMasterKeyID": "arn:aws:kms:us-east-1:123456789012:key/mrk-abc123"
        },
        "BucketKeyEnabled": true
      }
    ]
  }
}
```

**Bucket Key** is enabled to reduce KMS API calls (and cost) by caching the data encryption key at the bucket level.

---

## Access Control

### VPC Endpoint Only

All Lambda functions access S3 through a VPC Gateway Endpoint. The bucket policy denies access from outside the VPC:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNonVPCAccess",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::agentmail-attachments-prod",
        "arn:aws:s3:::agentmail-attachments-prod/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "aws:sourceVpce": "vpce-0abc123def456789"
        }
      }
    },
    {
      "Sid": "AllowLambdaRole",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::123456789012:role/agentmail-lambda-role"
      },
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::agentmail-attachments-prod/*"
    }
  ]
}
```

### Pre-Signed URLs for Downloads

Attachment and raw email downloads use pre-signed URLs with a 15-minute expiry:

```python
import boto3
from botocore.config import Config

s3_client = boto3.client(
    "s3",
    config=Config(
        signature_version="s3v4",
        s3={"addressing_style": "virtual"},
    ),
)


def generate_download_url(bucket: str, key: str, filename: str) -> str:
    """Generate a pre-signed download URL with 15-minute expiry."""
    return s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=900,  # 15 minutes
    )
```

The API returns a 302 redirect to the pre-signed URL:

```python
def handle_attachment_download(inbox_id, message_id, attachment_id):
    # Get attachment metadata from DynamoDB
    attachment = get_attachment(message_id, attachment_id)

    # Generate pre-signed URL
    url = generate_download_url(
        bucket=attachment["s3_bucket"],
        key=attachment["s3_key"],
        filename=attachment["filename"],
    )

    return {
        "statusCode": 302,
        "headers": {"Location": url},
    }
```

### Block Public Access

All buckets have S3 Block Public Access enabled at both the account and bucket level:

```json
{
  "BlockPublicAcls": true,
  "IgnorePublicAcls": true,
  "BlockPublicPolicy": true,
  "RestrictPublicBuckets": true
}
```

---

## Cross-Region Replication

For disaster recovery, the raw email and bodies buckets are replicated to us-west-2:

```json
{
  "ReplicationConfiguration": {
    "Role": "arn:aws:iam::123456789012:role/s3-replication-role",
    "Rules": [
      {
        "ID": "replicate-raw-email",
        "Status": "Enabled",
        "Filter": {
          "Prefix": "raw-email/"
        },
        "Destination": {
          "Bucket": "arn:aws:s3:::agentmail-raw-email-prod-replica",
          "StorageClass": "STANDARD_IA",
          "EncryptionConfiguration": {
            "ReplicaKmsKeyID": "arn:aws:kms:us-west-2:123456789012:key/mrk-def456"
          }
        },
        "DeleteMarkerReplication": {
          "Status": "Enabled"
        }
      }
    ]
  }
}
```

Replicated objects use Standard-IA in the destination region to reduce cost (they are only accessed during a disaster).

Attachments and exports are **not replicated** -- attachments can be re-extracted from raw email, and exports are ephemeral.

---

## S3 Object Lock

For compliance-sensitive organizations (financial services, healthcare), S3 Object Lock can be enabled on the raw email bucket:

```json
{
  "ObjectLockConfiguration": {
    "ObjectLockEnabled": "Enabled",
    "Rule": {
      "DefaultRetention": {
        "Mode": "GOVERNANCE",
        "Days": 2555
      }
    }
  }
}
```

| Mode | Behavior |
|------|----------|
| GOVERNANCE | Prevents deletion by most users; can be overridden by users with `s3:BypassGovernanceRetention` permission |
| COMPLIANCE | Prevents deletion by ALL users, including root. Cannot be shortened once set. |

Object Lock is opt-in per organization. It is enabled at inbox creation time for organizations that have compliance mode configured.

---

## Virus Scanning

All inbound attachments are scanned for malware before being made available to clients.

### Architecture

```
SES receives email
    |
    v
Inbound Lambda extracts attachments
    |
    v
Write to S3 (attachments bucket, "pending/" prefix)
    |
    v
S3 Event Notification triggers Scan Lambda
    |
    v
Scan Lambda:
  1. Download object to /tmp (Lambda ephemeral storage)
  2. Run ClamAV scan (bundled in Lambda layer)
  3. If clean: move to "attachments/" prefix (rename)
  4. If infected: move to "quarantine/" prefix, tag with virus name
  5. Update DynamoDB attachment record with scan result
```

### ClamAV Lambda Layer

```yaml
ScanFunction:
  Type: AWS::Lambda::Function
  Properties:
    FunctionName: agentmail-virus-scan
    Runtime: python3.12
    Handler: scan.handler
    MemorySize: 2048        # ClamAV needs ~1.5 GB for virus definitions
    Timeout: 300            # Large attachments take time
    EphemeralStorage:
      Size: 2048            # /tmp for downloaded files + ClamAV DB
    Layers:
      - !Ref ClamAVLayer    # Custom layer with ClamAV binaries + virus defs
    Environment:
      Variables:
        QUARANTINE_PREFIX: "quarantine/"
        CLEAN_PREFIX: "attachments/"
```

### Scan Lambda Code

```python
import subprocess
import boto3
import os

s3 = boto3.client("s3")


def handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        # Download to /tmp
        local_path = f"/tmp/{os.path.basename(key)}"
        s3.download_file(bucket, key, local_path)

        # Run ClamAV scan
        result = subprocess.run(
            ["clamscan", "--no-summary", local_path],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # Clean -- move from pending/ to attachments/
            new_key = key.replace("pending/", "attachments/", 1)
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": key},
                Key=new_key,
            )
            s3.delete_object(Bucket=bucket, Key=key)
            update_attachment_status(key, "clean")
        else:
            # Infected -- move to quarantine/
            new_key = key.replace("pending/", "quarantine/", 1)
            s3.copy_object(
                Bucket=bucket,
                CopySource={"Bucket": bucket, "Key": key},
                Key=new_key,
                Tagging="scan_result=infected&virus_name=" + parse_virus_name(result.stdout),
            )
            s3.delete_object(Bucket=bucket, Key=key)
            update_attachment_status(key, "infected", parse_virus_name(result.stdout))
```

### Virus Definition Updates

ClamAV virus definitions are updated daily via a scheduled Lambda that downloads the latest definitions to an S3 prefix, then updates the Lambda layer:

```yaml
UpdateVirusDefsSchedule:
  Type: AWS::Events::Rule
  Properties:
    ScheduleExpression: "rate(6 hours)"
    Targets:
      - Arn: !GetAtt UpdateVirusDefsFunction.Arn
        Id: UpdateVirusDefs
```

---

## Cost Optimization

### Intelligent-Tiering

For the bodies bucket (unpredictable access patterns as messages age), S3 Intelligent-Tiering automatically moves objects between frequent and infrequent access tiers:

```json
{
  "Rules": [
    {
      "ID": "bodies-intelligent-tiering",
      "Status": "Enabled",
      "Filter": {
        "Prefix": "bodies/"
      },
      "Transitions": [
        {
          "Days": 0,
          "StorageClass": "INTELLIGENT_TIERING"
        }
      ]
    }
  ]
}
```

Intelligent-Tiering monitoring fee: $0.0025 per 1,000 objects. This is cost-effective for objects larger than ~128 KB (most email bodies).

### Cost Estimates by Scale

| Scale | Raw Email/Month | Attachments/Month | Bodies/Month | Total Storage Cost |
|-------|----------------|-------------------|-------------|-------------------|
| Startup (100K msgs/day) | 15 GB | 30 GB | 5 GB | ~$2/month |
| Growth (1M msgs/day) | 150 GB | 300 GB | 50 GB | ~$15/month |
| Full Scale (10M msgs/day) | 1.5 TB | 3 TB | 500 GB | ~$130/month |

These estimates assume:
- Average raw email: 5 KB
- Average attachment: 100 KB (10% of messages have attachments)
- Average body JSON: 1.5 KB
- Lifecycle policies reduce long-term storage cost by ~80%

### Additional Optimizations

1. **Multipart upload for large attachments.** Attachments > 100 MB use S3 multipart upload for reliability and parallelism.

2. **S3 Transfer Acceleration disabled.** All access is from Lambda within the same region via VPC endpoint -- Transfer Acceleration adds cost without benefit.

3. **S3 batch operations for cleanup.** When an organization is deleted, S3 Batch Operations delete all their objects in bulk rather than individual DeleteObject calls.

4. **Request cost awareness.** GET requests cost $0.0004 per 1,000. PUT/POST cost $0.005 per 1,000. The bodies bucket serves the most GETs -- caching hot bodies in Redis could reduce S3 GET costs at very high scale.
