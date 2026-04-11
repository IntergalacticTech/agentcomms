# Metering Pipeline

This document covers the implementation of usage metering for FreeMail on AWS Marketplace.

Current planning notes:

- Marketplace metering is **post-Pro** work.
- The important outcome now is to lock the correct integration pattern before any code is written.
- Some lower sections still use legacy variable names such as `customer_identifier`; treat the request/response shapes in the opening sections as authoritative.

---

## MeterUsage vs BatchMeterUsage

AWS Marketplace provides two metering APIs:

| API | Use Case | Limits | When to Use |
|-----|----------|--------|-------------|
| `MeterUsage` | Real-time, single-record submission | 1 record per call, per dimension, per hour | Synchronous metering in request path (not recommended for SaaS) |
| `BatchMeterUsage` | Batch submission of multiple records | Up to 25 records per call | **Recommended**: hourly batch job aggregates and submits all customer usage |

**We use `BatchMeterUsage`** exclusively because:
1. Hourly aggregation reduces API calls (1 call per 25 customers vs. 1 call per request)
2. Batch processing is more resilient to transient failures (retry the batch, not individual requests)
3. Separates metering from the request path (no latency impact on API responses)
4. Aligns naturally with the Marketplace's hourly billing granularity

### Current AWS Identifier Rule

For new SaaS products launched on or after June 1, 2026, AWS Marketplace requires planning around:

- `CustomerAWSAccountId` instead of relying only on `CustomerIdentifier`
- `LicenseArn` on each usage record

`CustomerIdentifier` and `ProductCode` can still be retained, but new implementations should center on the newer fields.

---

## Pipeline Architecture

```
API Gateway
    |
    v
Lambda Functions (business logic)
    |
    | (emit usage events)
    v
Kinesis Data Stream ("agentmail-usage-events")
    |
    | (shard by org_id for ordering)
    v
EventBridge Rule (fires every hour at :05 past, e.g., 14:05 UTC)
    |
    v
Lambda: UsageAggregator
    |
    | (reads from Kinesis, aggregates per customer per dimension per hour)
    v
DynamoDB Table: "UsageAggregates"
    |
    | PK: METER#{customer_id}  SK: {hour_timestamp}#{dimension}
    | Attributes: quantity, submitted (bool), submitted_at, request_id
    |
    v
Lambda: MeterUsageSubmitter (triggered by EventBridge at :10 past each hour)
    |
    | (reads unsubmitted aggregates, calls BatchMeterUsage)
    v
AWS Marketplace Metering Service (BatchMeterUsage)
    |
    +---> Success: Mark records as submitted in DynamoDB
    |
    +---> Failure: DLQ (SQS) + CloudWatch Alarm
              |
              v
         Lambda: MeterUsageDLQProcessor (retry with backoff)
              |
              +---> Permanent failure: SNS alert to operations team
```

### Timing

| Event | Time | Why |
|-------|------|-----|
| Usage events written to Kinesis | Continuous | Real-time as API requests are processed |
| Aggregator Lambda fires | :05 past each UTC hour | Gives 5 minutes for late-arriving Kinesis records |
| Submitter Lambda fires | :10 past each UTC hour | Gives aggregator 5 minutes to complete |
| 6-hour submission deadline | 6 hours after the usage hour | **Records older than 6 hours are rejected and revenue is permanently lost** |

### Why :05 and :10 Past the Hour

Kinesis has an "at least once" delivery model with potential delays of seconds to minutes. Firing the aggregator at :05 captures >99.9% of events for the preceding hour. The submitter fires at :10 to ensure aggregation is complete before submission. This leaves a 5-hour 50-minute buffer before the 6-hour deadline.

---

## BatchMeterUsage API

### Request Format

```json
{
  "ProductCode": "prod-abcdef1234567",
  "UsageRecords": [
    {
      "CustomerAWSAccountId": "123456789012",
      "LicenseArn": "arn:aws:aws-marketplace:us-east-1:123456789012:AWSMarketplace/Agreement/agmt-abc123",
      "Dimension": "messages_sent",
      "Quantity": 1547,
      "Timestamp": "2026-04-10T14:00:00Z"
    },
    {
      "CustomerAWSAccountId": "123456789012",
      "LicenseArn": "arn:aws:aws-marketplace:us-east-1:123456789012:AWSMarketplace/Agreement/agmt-abc123",
      "Dimension": "messages_received",
      "Quantity": 892,
      "Timestamp": "2026-04-10T14:00:00Z"
    },
    {
      "CustomerAWSAccountId": "210987654321",
      "LicenseArn": "arn:aws:aws-marketplace:us-east-1:210987654321:AWSMarketplace/Agreement/agmt-def456",
      "Dimension": "messages_sent",
      "Quantity": 3201,
      "Timestamp": "2026-04-10T14:00:00Z"
    }
  ]
}
```

### Request Constraints

| Constraint | Value |
|-----------|-------|
| Max records per call | **25** |
| Timestamp format | ISO 8601 UTC, **rounded down to the hour** |
| Timestamp window | Current hour minus 6 hours (records older than 6h are rejected) |
| Quantity | Non-negative integer (0 is valid) |
| Dimension | Must match a registered dimension key exactly |
| CustomerAWSAccountId | Obtained from `ResolveCustomer` during onboarding |
| LicenseArn | Obtained from `ResolveCustomer` during onboarding |
| ProductCode | Still supplied for product identification |

### CRITICAL: Timestamp Rounding

> Timestamps **must** be rounded to the beginning of the UTC hour. A timestamp of `2026-04-10T14:37:22Z` must be submitted as `2026-04-10T14:00:00Z`.

If you submit multiple records for the same customer + dimension + hour, **the last value wins**. This means you must **aggregate before submitting** -- if you submit 500 at :10 and then 200 at :15 for the same customer/dimension/hour, the customer is only billed for 200.

### Response Format

```json
{
  "Results": [
    {
      "UsageRecord": {
        "CustomerAWSAccountId": "123456789012",
        "LicenseArn": "arn:aws:aws-marketplace:us-east-1:123456789012:AWSMarketplace/Agreement/agmt-abc123",
        "Dimension": "messages_sent",
        "Quantity": 1547,
        "Timestamp": "2026-04-10T14:00:00Z"
      },
      "MeteringRecordId": "mrec-1234abcd-5678-efgh-ijkl-9012mnop3456",
      "Status": "Success"
    },
    {
      "UsageRecord": {
        "CustomerAWSAccountId": "123456789012",
        "LicenseArn": "arn:aws:aws-marketplace:us-east-1:123456789012:AWSMarketplace/Agreement/agmt-abc123",
        "Dimension": "messages_received",
        "Quantity": 892,
        "Timestamp": "2026-04-10T14:00:00Z"
      },
      "MeteringRecordId": "mrec-abcd1234-efgh-5678-ijkl-mnop90123456",
      "Status": "Success"
    },
    {
      "UsageRecord": {
        "CustomerAWSAccountId": "210987654321",
        "LicenseArn": "arn:aws:aws-marketplace:us-east-1:210987654321:AWSMarketplace/Agreement/agmt-def456",
        "Dimension": "messages_sent",
        "Quantity": 3201,
        "Timestamp": "2026-04-10T14:00:00Z"
      },
      "MeteringRecordId": "",
      "Status": "CustomerNotEntitled"
    }
  ],
  "UnprocessedRecords": []
}
```

### Response Status Values

| Status | Meaning | Action |
|--------|---------|--------|
| `Success` | Record accepted and will be billed | Store `MeteringRecordId` in local ledger |
| `CustomerNotSubscribed` | Customer has no active subscription | Check if unsubscribe SNS was missed; stop metering this customer |
| `DuplicateRecord` | Same customer + dimension + hour already submitted | Safe to ignore; idempotent |
| `CustomerNotEntitled` | Customer exists but is not entitled to this dimension | Check entitlement via `GetEntitlements`; may indicate tier mismatch |

---

## CRITICAL: 6-Hour Submission Window

> **Usage records must be submitted within 6 hours of the metered hour. Records older than 6 hours are permanently rejected. This is lost revenue that cannot be recovered.**

### Concrete Example

```
Usage hour:      2026-04-10T14:00:00Z
Submission deadline: 2026-04-10T20:00:00Z

If you submit at 2026-04-10T20:01:00Z → TimestampOutOfBoundsException → LOST REVENUE
```

### Safeguards

1. **Aggregator fires at :05** -- leaves 5h55m buffer
2. **Submitter fires at :10** -- leaves 5h50m buffer
3. **DLQ retry** -- retries within 2 hours of initial failure
4. **CloudWatch Alarm** -- fires if any record exceeds 4-hour age without submission
5. **Hourly reconciliation** -- compares DynamoDB aggregates against submitted records; alerts on gaps

---

## Error Handling

### ThrottlingException

```python
# AWS Marketplace Metering API throttle: 25 TPS for BatchMeterUsage
# With exponential backoff and jitter

import time
import random

def submit_with_retry(client, product_code, records, max_retries=5):
    for attempt in range(max_retries):
        try:
            response = client.batch_meter_usage(
                ProductCode=product_code,
                UsageRecords=records
            )
            return response
        except client.exceptions.ThrottlingException:
            wait = min(2 ** attempt + random.uniform(0, 1), 30)
            print(f"Throttled, retrying in {wait:.1f}s (attempt {attempt + 1})")
            time.sleep(wait)
    raise Exception(f"Failed after {max_retries} retries due to throttling")
```

### InvalidUsageDimensionException

Occurs when the dimension key does not match any registered dimension. This is a **code bug**, not a transient error.

```python
except client.exceptions.InvalidUsageDimensionException as e:
    # NEVER retry -- fix the dimension key in code
    logger.error(f"Invalid dimension: {e}. Check dimension keys match AMMP registration.")
    # Send to DLQ for investigation, do NOT retry
    send_to_dlq(records, error="InvalidUsageDimension")
```

### TimestampOutOfBoundsException

Occurs when the timestamp is more than 6 hours old. **This is lost revenue.**

```python
except client.exceptions.TimestampOutOfBoundsException as e:
    # CRITICAL: This is lost revenue. Alert immediately.
    logger.critical(f"LOST REVENUE: Timestamp out of bounds for records: {records}")
    publish_alarm(
        alarm_name="MeteringLostRevenue",
        message=f"Lost revenue: {len(records)} records rejected due to timestamp > 6h old",
        severity="CRITICAL"
    )
    # Record in local ledger for financial reconciliation
    mark_records_as_lost(records, reason="TimestampOutOfBounds")
```

### CustomerNotEntitledException

Customer's subscription may have been cancelled. Check SNS notifications.

```python
# In response processing (not exception -- returned in Results array)
for result in response['Results']:
    if result['Status'] == 'CustomerNotEntitled':
        customer_id = result['UsageRecord']['CustomerIdentifier']
        logger.warning(f"Customer {customer_id} not entitled. Checking subscription status.")
        # Refresh entitlement cache
        refresh_entitlement(customer_id)
        # If customer is truly unsubscribed, stop metering
        if not is_customer_active(customer_id):
            deactivate_metering(customer_id)
```

### DuplicateRequestException

Safe to ignore. `BatchMeterUsage` is idempotent for the same customer + dimension + hour.

```python
# DuplicateRecord status in Results array -- no action needed
for result in response['Results']:
    if result['Status'] == 'DuplicateRecord':
        logger.info(f"Duplicate record (safe): {result['UsageRecord']}")
```

---

## DryRun Mode

`BatchMeterUsage` supports a `DryRun` parameter for testing without actual billing.

```python
response = client.batch_meter_usage(
    ProductCode=product_code,
    UsageRecords=records,
    # DryRun validates the request without submitting to billing
    # Returns same response format with Status values
)
```

**Use DryRun for:**
- Integration testing during development
- Validating dimension keys before first publish
- Testing the metering pipeline end-to-end without billing customers
- Limited-visibility listing testing

**DryRun is not a parameter of BatchMeterUsage.** To test without billing, use the Marketplace's limited-visibility listing and subscribe with your own AWS account. This creates real metering records that you can validate, but since you are both seller and buyer, no money changes hands.

---

## Local Ledger for Reconciliation

Every metering record is persisted in DynamoDB before and after submission to `BatchMeterUsage`. This local ledger enables:

1. **Revenue reconciliation** -- compare local ledger totals against AWS Marketplace billing reports (available in AMMP)
2. **Lost revenue detection** -- records that were aggregated but never successfully submitted
3. **Dispute resolution** -- if a customer contests a charge, the ledger provides evidence
4. **Audit trail** -- complete history of what was metered, when, and the API response

### DynamoDB Schema for Local Ledger

```
Table: agentmail-metering-ledger

Primary Key:
  PK: METER#{customer_identifier}
  SK: {hour_timestamp}#{dimension_key}

Attributes:
  quantity:          Number   -- aggregated quantity for this hour
  submitted:         Boolean  -- whether BatchMeterUsage accepted the record
  submitted_at:      String   -- ISO 8601 timestamp of successful submission
  metering_record_id: String  -- MeteringRecordId from BatchMeterUsage response
  request_id:        String   -- AWS request ID for the BatchMeterUsage call
  status:            String   -- Success | DuplicateRecord | CustomerNotEntitled | Lost
  created_at:        String   -- when the aggregate was first created
  updated_at:        String   -- last update timestamp
  ttl:               Number   -- epoch seconds, set to created_at + 90 days

GSI: SubmissionStatusIndex
  PK: submitted (Boolean, "true" or "false")
  SK: {hour_timestamp}
  Projection: ALL
  Use: Query all unsubmitted records for retry processing
```

---

## IAM Permissions

### Metering Lambda Execution Role

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "MarketplaceMetering",
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:BatchMeterUsage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "MarketplaceResolve",
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ResolveCustomer"
      ],
      "Resource": "*"
    },
    {
      "Sid": "MarketplaceEntitlements",
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:GetEntitlements"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DynamoDBAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/agentmail-metering-ledger",
        "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/agentmail-metering-ledger/index/*",
        "arn:aws:dynamodb:us-east-1:ACCOUNT_ID:table/agentmail-usage-aggregates"
      ]
    },
    {
      "Sid": "KinesisRead",
      "Effect": "Allow",
      "Action": [
        "kinesis:GetRecords",
        "kinesis:GetShardIterator",
        "kinesis:DescribeStream",
        "kinesis:ListShards"
      ],
      "Resource": "arn:aws:kinesis:us-east-1:ACCOUNT_ID:stream/agentmail-usage-events"
    },
    {
      "Sid": "SQSSendDLQ",
      "Effect": "Allow",
      "Action": [
        "sqs:SendMessage"
      ],
      "Resource": "arn:aws:sqs:us-east-1:ACCOUNT_ID:agentmail-metering-dlq"
    },
    {
      "Sid": "CloudWatchAlarms",
      "Effect": "Allow",
      "Action": [
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    },
    {
      "Sid": "Logging",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:ACCOUNT_ID:log-group:/aws/lambda/agentmail-meter-*"
    }
  ]
}
```

**Note**: `aws-marketplace:BatchMeterUsage`, `aws-marketplace:ResolveCustomer`, and `aws-marketplace:GetEntitlements` do not support resource-level permissions -- `Resource: "*"` is required.

---

## Complete Metering Lambda (Python)

### Usage Aggregator Lambda

Triggered by EventBridge at :05 past each UTC hour. Reads usage events from Kinesis and aggregates per customer per dimension per hour.

```python
"""
AgentMail Usage Aggregator Lambda

Triggered: EventBridge rule, every hour at :05 past UTC
Purpose: Read usage events from Kinesis, aggregate per customer/dimension/hour,
         write aggregates to DynamoDB for submission.
"""

import json
import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from botocore.config import Config

# Environment variables
KINESIS_STREAM = os.environ["KINESIS_STREAM_NAME"]
AGGREGATES_TABLE = os.environ["AGGREGATES_TABLE_NAME"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Clients
config = Config(retries={"max_attempts": 3, "mode": "adaptive"})
kinesis = boto3.client("kinesis", region_name=REGION, config=config)
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=config)
table = dynamodb.Table(AGGREGATES_TABLE)


def get_target_hour():
    """Return the UTC hour we are aggregating for (previous hour)."""
    now = datetime.now(timezone.utc)
    target = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return target


def read_kinesis_records(stream_name, target_hour):
    """
    Read all records from Kinesis for the target hour.
    Uses TRIM_HORIZON to ensure we don't miss any records.
    In production, use enhanced fan-out or a Kinesis Data Firehose
    for higher throughput.
    """
    records = []
    hour_start = target_hour.isoformat()
    hour_end = (target_hour + timedelta(hours=1)).isoformat()

    response = kinesis.describe_stream(StreamName=stream_name)
    shards = response["StreamDescription"]["Shards"]

    for shard in shards:
        shard_id = shard["ShardId"]
        iterator_response = kinesis.get_shard_iterator(
            StreamName=stream_name,
            ShardId=shard_id,
            ShardIteratorType="AT_TIMESTAMP",
            Timestamp=target_hour,
        )
        shard_iterator = iterator_response["ShardIterator"]

        while shard_iterator:
            get_response = kinesis.get_records(
                ShardIterator=shard_iterator, Limit=1000
            )

            for record in get_response["Records"]:
                event = json.loads(record["Data"])
                event_time = event.get("timestamp", "")

                # Only include events within the target hour
                if hour_start <= event_time < hour_end:
                    records.append(event)

            shard_iterator = get_response.get("NextShardIterator")

            # Stop if we've passed the target hour
            if get_response["Records"]:
                last_ts = get_response["Records"][-1]["ApproximateArrivalTimestamp"]
                if last_ts > target_hour + timedelta(hours=2):
                    break

            if not get_response["Records"]:
                break

    return records


def aggregate_records(records):
    """
    Aggregate usage events into per-customer, per-dimension, per-hour totals.

    Expected event format:
    {
        "customer_identifier": "cust-abc123",
        "dimension": "messages_sent",
        "quantity": 1,
        "timestamp": "2026-04-10T14:23:45Z",
        "org_id": "org-xyz",
        "request_id": "req-123"
    }
    """
    aggregates = {}

    for record in records:
        customer_id = record["customer_identifier"]
        dimension = record["dimension"]
        quantity = record.get("quantity", 1)

        key = (customer_id, dimension)
        if key not in aggregates:
            aggregates[key] = {
                "customer_identifier": customer_id,
                "dimension": dimension,
                "quantity": 0,
                "event_count": 0,
            }

        aggregates[key]["quantity"] += quantity
        aggregates[key]["event_count"] += 1

    return list(aggregates.values())


def write_aggregates(aggregates, target_hour):
    """Write aggregated records to DynamoDB."""
    hour_str = target_hour.strftime("%Y-%m-%dT%H:00:00Z")
    now_str = datetime.now(timezone.utc).isoformat()
    ttl = int(time.time()) + (90 * 24 * 60 * 60)  # 90 days

    with table.batch_writer() as batch:
        for agg in aggregates:
            batch.put_item(
                Item={
                    "PK": f"METER#{agg['customer_identifier']}",
                    "SK": f"{hour_str}#{agg['dimension']}",
                    "customer_identifier": agg["customer_identifier"],
                    "dimension": agg["dimension"],
                    "quantity": Decimal(str(agg["quantity"])),
                    "hour_timestamp": hour_str,
                    "submitted": False,
                    "event_count": agg["event_count"],
                    "created_at": now_str,
                    "updated_at": now_str,
                    "ttl": ttl,
                }
            )

    return len(aggregates)


def handler(event, context):
    """Lambda entry point."""
    target_hour = get_target_hour()
    print(f"Aggregating usage for hour: {target_hour.isoformat()}")

    # Read events from Kinesis
    records = read_kinesis_records(KINESIS_STREAM, target_hour)
    print(f"Read {len(records)} usage events from Kinesis")

    if not records:
        print("No usage events for this hour. Nothing to aggregate.")
        return {"statusCode": 200, "aggregated": 0}

    # Aggregate per customer per dimension
    aggregates = aggregate_records(records)
    print(f"Aggregated into {len(aggregates)} records")

    # Write to DynamoDB
    written = write_aggregates(aggregates, target_hour)
    print(f"Wrote {written} aggregate records to DynamoDB")

    return {"statusCode": 200, "aggregated": written, "hour": target_hour.isoformat()}
```

### Meter Usage Submitter Lambda

Triggered by EventBridge at :10 past each UTC hour. Reads unsubmitted aggregates from DynamoDB and calls `BatchMeterUsage`.

```python
"""
AgentMail Meter Usage Submitter Lambda

Triggered: EventBridge rule, every hour at :10 past UTC
Purpose: Read unsubmitted usage aggregates from DynamoDB,
         submit to AWS Marketplace via BatchMeterUsage,
         update local ledger with results.
"""

import json
import os
import time
import random
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Environment variables
AGGREGATES_TABLE = os.environ["AGGREGATES_TABLE_NAME"]
LEDGER_TABLE = os.environ["LEDGER_TABLE_NAME"]
PRODUCT_CODE = os.environ["MARKETPLACE_PRODUCT_CODE"]
DLQ_URL = os.environ["DLQ_URL"]
REGION = os.environ.get("AWS_REGION", "us-east-1")

# Clients
config = Config(retries={"max_attempts": 3, "mode": "adaptive"})
marketplace = boto3.client("meteringmarketplace", region_name=REGION, config=config)
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=config)
sqs = boto3.client("sqs", region_name=REGION, config=config)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=config)

aggregates_table = dynamodb.Table(AGGREGATES_TABLE)
ledger_table = dynamodb.Table(LEDGER_TABLE)


def get_unsubmitted_records():
    """Query DynamoDB for all unsubmitted aggregate records."""
    records = []
    last_key = None

    while True:
        kwargs = {
            "IndexName": "SubmissionStatusIndex",
            "KeyConditionExpression": "submitted = :false",
            "ExpressionAttributeValues": {":false": False},
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        response = aggregates_table.query(**kwargs)
        records.extend(response["Items"])
        last_key = response.get("LastEvaluatedKey")

        if not last_key:
            break

    return records


def check_record_age(record):
    """Check if a record is within the 6-hour submission window."""
    hour_ts = datetime.fromisoformat(record["hour_timestamp"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age = now - hour_ts

    if age > timedelta(hours=6):
        return "expired"
    elif age > timedelta(hours=4):
        return "warning"
    else:
        return "ok"


def batch_records(records, batch_size=25):
    """Split records into batches of 25 (BatchMeterUsage limit)."""
    for i in range(0, len(records), batch_size):
        yield records[i : i + batch_size]


def submit_batch(usage_records):
    """
    Submit a batch of records to BatchMeterUsage with retry logic.
    Returns (successes, failures) tuples.
    """
    api_records = []
    for record in usage_records:
        api_records.append(
            {
                "CustomerIdentifier": record["customer_identifier"],
                "Dimension": record["dimension"],
                "Quantity": int(record["quantity"]),
                "Timestamp": datetime.fromisoformat(
                    record["hour_timestamp"].replace("Z", "+00:00")
                ),
            }
        )

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = marketplace.batch_meter_usage(
                ProductCode=PRODUCT_CODE, UsageRecords=api_records
            )
            return response["Results"], response.get("UnprocessedRecords", [])

        except marketplace.exceptions.ThrottlingException:
            wait = min(2**attempt + random.uniform(0, 1), 30)
            print(f"Throttled, retry in {wait:.1f}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)

        except marketplace.exceptions.TimestampOutOfBoundsException:
            # CRITICAL: Lost revenue
            print(f"CRITICAL: TimestampOutOfBounds for {len(api_records)} records")
            emit_lost_revenue_metric(len(api_records))
            return [], api_records  # All records are failures

        except marketplace.exceptions.InvalidUsageDimensionException as e:
            # Code bug -- do not retry
            print(f"ERROR: Invalid dimension: {e}")
            send_to_dlq(usage_records, str(e))
            return [], api_records

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            print(f"ClientError: {error_code} - {e}")
            if attempt < max_retries - 1:
                wait = min(2**attempt + random.uniform(0, 1), 30)
                time.sleep(wait)
            else:
                send_to_dlq(usage_records, str(e))
                return [], api_records

    # Exhausted retries
    send_to_dlq(usage_records, "Exhausted retries")
    return [], api_records


def update_ledger(results, original_records):
    """Update local ledger with submission results."""
    now_str = datetime.now(timezone.utc).isoformat()

    # Build a lookup from original records
    record_map = {}
    for r in original_records:
        key = (r["customer_identifier"], r["dimension"], r["hour_timestamp"])
        record_map[key] = r

    for result in results:
        ur = result["UsageRecord"]
        customer_id = ur["CustomerIdentifier"]
        dimension = ur["Dimension"]
        hour_ts = ur["Timestamp"].strftime("%Y-%m-%dT%H:00:00Z")
        status = result["Status"]
        metering_id = result.get("MeteringRecordId", "")

        # Update aggregates table
        aggregates_table.update_item(
            Key={"PK": f"METER#{customer_id}", "SK": f"{hour_ts}#{dimension}"},
            UpdateExpression="SET submitted = :true, submitted_at = :now, "
            "metering_record_id = :mid, #s = :status, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":true": True,
                ":now": now_str,
                ":mid": metering_id,
                ":status": status,
            },
        )

        # Write to ledger table
        ttl = int(time.time()) + (90 * 24 * 60 * 60)
        ledger_table.put_item(
            Item={
                "PK": f"METER#{customer_id}",
                "SK": f"{hour_ts}#{dimension}",
                "customer_identifier": customer_id,
                "dimension": dimension,
                "quantity": record_map.get(
                    (customer_id, dimension, hour_ts), {}
                ).get("quantity", 0),
                "hour_timestamp": hour_ts,
                "submitted": True,
                "submitted_at": now_str,
                "metering_record_id": metering_id,
                "status": status,
                "ttl": ttl,
            }
        )


def emit_lost_revenue_metric(count):
    """Emit CloudWatch metric for lost revenue records."""
    cloudwatch.put_metric_data(
        Namespace="AgentMail/Metering",
        MetricData=[
            {
                "MetricName": "LostRevenueRecords",
                "Value": count,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": "Service", "Value": "MeterUsageSubmitter"},
                ],
            }
        ],
    )


def send_to_dlq(records, error_message):
    """Send failed records to Dead Letter Queue."""
    sqs.send_message(
        QueueUrl=DLQ_URL,
        MessageBody=json.dumps(
            {
                "error": error_message,
                "records": [
                    {
                        "customer_identifier": r.get("customer_identifier", r.get("CustomerIdentifier")),
                        "dimension": r.get("dimension", r.get("Dimension")),
                        "quantity": int(r.get("quantity", r.get("Quantity", 0))),
                        "hour_timestamp": r.get("hour_timestamp", str(r.get("Timestamp", ""))),
                    }
                    for r in records
                ],
                "failed_at": datetime.now(timezone.utc).isoformat(),
            },
            default=str,
        ),
    )


def handler(event, context):
    """Lambda entry point."""
    print("Starting meter usage submission")

    # Get unsubmitted records
    records = get_unsubmitted_records()
    print(f"Found {len(records)} unsubmitted records")

    if not records:
        print("No records to submit")
        return {"statusCode": 200, "submitted": 0, "failed": 0}

    # Check for expired records
    expired_count = 0
    valid_records = []
    for record in records:
        age_status = check_record_age(record)
        if age_status == "expired":
            expired_count += 1
            print(
                f"CRITICAL: Expired record for {record['customer_identifier']} "
                f"dimension={record['dimension']} hour={record['hour_timestamp']}"
            )
            # Mark as lost in ledger
            aggregates_table.update_item(
                Key={"PK": record["PK"], "SK": record["SK"]},
                UpdateExpression="SET submitted = :true, #s = :status, updated_at = :now",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":true": True,
                    ":status": "Lost",
                    ":now": datetime.now(timezone.utc).isoformat(),
                },
            )
        elif age_status == "warning":
            print(
                f"WARNING: Record approaching 6h deadline for {record['customer_identifier']} "
                f"dimension={record['dimension']} hour={record['hour_timestamp']}"
            )
            valid_records.append(record)
        else:
            valid_records.append(record)

    if expired_count > 0:
        emit_lost_revenue_metric(expired_count)
        print(f"CRITICAL: {expired_count} records lost due to expiration")

    # Submit in batches of 25
    total_success = 0
    total_failed = 0

    for batch in batch_records(valid_records, 25):
        results, failures = submit_batch(batch)
        update_ledger(results, batch)
        total_success += len(results)
        total_failed += len(failures)

    # Emit metrics
    cloudwatch.put_metric_data(
        Namespace="AgentMail/Metering",
        MetricData=[
            {
                "MetricName": "RecordsSubmitted",
                "Value": total_success,
                "Unit": "Count",
            },
            {
                "MetricName": "RecordsFailed",
                "Value": total_failed,
                "Unit": "Count",
            },
        ],
    )

    print(f"Submission complete: {total_success} success, {total_failed} failed, {expired_count} expired")
    return {
        "statusCode": 200,
        "submitted": total_success,
        "failed": total_failed,
        "expired": expired_count,
    }
```

### Usage Event Emitter (called from API Lambda functions)

```python
"""
Usage event emitter -- called from API Lambda functions to record usage events.
"""

import json
import os
from datetime import datetime, timezone

import boto3

kinesis = boto3.client("kinesis")
STREAM_NAME = os.environ["USAGE_STREAM_NAME"]


def emit_usage(customer_identifier: str, dimension: str, quantity: int = 1, org_id: str = ""):
    """
    Emit a usage event to Kinesis for metering.

    Args:
        customer_identifier: Marketplace CustomerIdentifier
        dimension: Metering dimension key (e.g., "messages_sent")
        quantity: Number of units to meter (default 1)
        org_id: AgentMail organization ID (for internal correlation)
    """
    event = {
        "customer_identifier": customer_identifier,
        "dimension": dimension,
        "quantity": quantity,
        "org_id": org_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    kinesis.put_record(
        StreamName=STREAM_NAME,
        Data=json.dumps(event),
        PartitionKey=customer_identifier,  # Ensures ordering per customer
    )


# Usage in API Lambda handlers:
#
# def handle_send_message(event, context):
#     # ... process message ...
#     emit_usage(
#         customer_identifier=tenant.marketplace_customer_id,
#         dimension="messages_sent",
#         quantity=1,
#         org_id=tenant.org_id
#     )
#
# def handle_search(event, context):
#     # ... execute search ...
#     emit_usage(
#         customer_identifier=tenant.marketplace_customer_id,
#         dimension="ai_searches",
#         quantity=1,
#         org_id=tenant.org_id
#     )
```
