# Disaster Recovery and Business Continuity

This document defines the disaster recovery (DR) and business continuity (BC) strategy for AgentMail. It covers recovery objectives, failure scenarios with detailed runbooks, backup configuration, multi-region failover architecture, data integrity verification, incident response procedures, and chaos engineering plans.

---

## Table of Contents

1. [Recovery Objectives](#1-recovery-objectives)
2. [Failure Scenarios and Response](#2-failure-scenarios-and-response)
3. [Backup Strategy](#3-backup-strategy)
4. [Multi-Region Failover (Phase 2+)](#4-multi-region-failover-phase-2)
5. [Data Integrity Checks](#5-data-integrity-checks)
6. [Incident Response](#6-incident-response)
7. [Chaos Engineering (Future)](#7-chaos-engineering-future)

---

## 1. Recovery Objectives

### Recovery Time Objective (RTO)

| Service Mode | RTO | Description |
|-------------|-----|-------------|
| **Degraded service** | 30 minutes | Core email send/receive functional; API may be read-only or rate-limited; AI features disabled |
| **Full service** | 4 hours | All features fully operational at normal performance levels |

### Recovery Point Objective (RPO)

| Data Store | RPO | Mechanism |
|-----------|-----|-----------|
| **DynamoDB** | 0 (zero data loss) | Continuous backups via Point-in-Time Recovery (PITR) |
| **S3** | < 15 minutes | Cross-region replication with Replication Time Control (RTC) |
| **Redis** | Up to 24 hours | Daily snapshots; cache data is reconstructable from DynamoDB |
| **OpenSearch** | Up to 1 hour | Hourly automated snapshots; fully reconstructable from DynamoDB Streams |

### Service Priority Tiers

| Tier | Services | Recovery Priority | RTO Target |
|------|----------|-------------------|------------|
| **P0 -- Critical** | Email sending (SES outbound), Email receiving (SES inbound rules, S3 storage, Lambda processing) | Restored first; all resources allocated | < 30 min (degraded), < 2 hr (full) |
| **P1 -- High** | REST API (API Gateway + Lambda), Web console (CloudFront + S3 static), Cognito authentication | Restored immediately after P0 | < 1 hr (degraded), < 3 hr (full) |
| **P2 -- Medium** | AI features (Bedrock integration, smart routing), IMAP/SMTP bridge (NLB + Fargate), Webhooks (Kinesis + Lambda) | Restored after P0 and P1 are stable | < 2 hr (degraded), < 4 hr (full) |
| **P3 -- Low** | Metrics and dashboards (CloudWatch), Analytics (OpenSearch), Usage billing aggregation | Restored last; acceptable to be offline for extended period | < 4 hr (degraded), < 8 hr (full) |

### Recovery Decision Matrix

```
IF full regional outage:
  → Initiate multi-region failover (Section 4)
  → P0 services restored via secondary region within 30 min
  → P1-P3 services follow in priority order

IF single-service failure:
  → Follow service-specific runbook (Section 2)
  → Automated remediation handles most cases
  → Escalate to on-call if automated recovery fails after 5 min

IF data corruption:
  → Halt writes to affected data store immediately
  → Restore from backup (Section 3)
  → Run integrity checks (Section 5) before resuming traffic
```

---

## 2. Failure Scenarios and Response

### Summary Table

| # | Scenario | Probability | Impact | RTO |
|---|----------|------------|--------|-----|
| 2.1 | Single Lambda function failure | High | Low (auto-retry) | < 1 min |
| 2.2 | DynamoDB throttling | Medium | Medium (degraded API) | < 5 min |
| 2.3 | SES regional outage | Low | Critical (no email) | 1-4 hours |
| 2.4 | S3 regional degradation | Very Low | High (no attachments) | 1-2 hours |
| 2.5 | Full us-east-1 outage | Very Low | Critical (full outage) | 2-4 hours |
| 2.6 | DynamoDB table corruption | Very Low | Critical (data loss) | 1-2 hours |
| 2.7 | Redis cluster failure | Low | Medium (degraded perf) | 15-30 min |
| 2.8 | Kinesis shard failure | Low | Medium (delayed events) | < 5 min |
| 2.9 | API Gateway outage | Very Low | Critical (no API) | Depends on AWS |
| 2.10 | DNS (Route 53) failure | Very Low | Critical (unreachable) | Depends on AWS |
| 2.11 | Accidental data deletion | Low | High (data loss) | 1-4 hours |
| 2.12 | Security breach (key compromise) | Low | Critical | Immediate response |

---

### 2.1 Single Lambda Function Failure

**Detection:**
- CloudWatch alarm on `Errors` metric exceeding threshold (> 5% error rate over 2 minutes)
- Lambda Insights detecting elevated duration or timeout patterns
- X-Ray traces showing increased failure spans

**Impact:**
- Low. Lambda has built-in retry behavior (2 retries for asynchronous invocations). SQS-triggered Lambdas retry based on queue visibility timeout and redrive policy. Individual request failures are transparent to most callers due to API Gateway retry logic.

**Automated Response:**
- Lambda retries the invocation automatically (up to 2 times for async, configurable for SQS)
- Dead Letter Queue (DLQ) captures failed events after max retries
- CloudWatch alarm triggers SNS notification to on-call

**Manual Response (if automated recovery fails):**

```
RUNBOOK: Lambda Function Failure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. IDENTIFY the failing function:
   aws cloudwatch get-metric-data \
     --metric-data-queries '[{
       "Id": "errors",
       "MetricStat": {
         "Metric": {
           "Namespace": "AWS/Lambda",
           "MetricName": "Errors",
           "Dimensions": [{"Name": "FunctionName", "Value": "<FUNCTION_NAME>"}]
         },
         "Period": 60,
         "Stat": "Sum"
       }
     }]' \
     --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%S)

2. CHECK recent deployments (was a bad version deployed?):
   aws lambda list-versions-by-function --function-name <FUNCTION_NAME> \
     --query 'Versions[-3:].[Version,Description,LastModified]'

3. REVIEW CloudWatch Logs for error details:
   aws logs filter-log-events \
     --log-group-name /aws/lambda/<FUNCTION_NAME> \
     --start-time $(date -u -d '30 minutes ago' +%s)000 \
     --filter-pattern "ERROR"

4. IF bad deployment → ROLLBACK to previous version:
   aws lambda update-alias \
     --function-name <FUNCTION_NAME> \
     --name prod \
     --function-version <PREVIOUS_VERSION>

5. IF resource exhaustion → INCREASE concurrency or memory:
   aws lambda put-function-concurrency \
     --function-name <FUNCTION_NAME> \
     --reserved-concurrent-executions <NEW_LIMIT>

6. IF dependency failure → CHECK downstream service health:
   - DynamoDB: aws dynamodb describe-table --table-name <TABLE>
   - S3: aws s3api head-bucket --bucket <BUCKET>
   - SES: aws ses get-send-quota

7. PROCESS DLQ messages after root cause is fixed:
   aws sqs receive-message --queue-url <DLQ_URL> --max-number-of-messages 10
   # Re-drive messages back to source queue or process manually

8. VERIFY recovery:
   - Monitor error rate returns to < 0.1% over 5 minutes
   - Confirm DLQ is draining (no new messages arriving)
```

**RTO:** < 1 minute (automatic), < 15 minutes (manual rollback)

---

### 2.2 DynamoDB Throttling

**Detection:**
- CloudWatch alarm on `ThrottledRequests` metric > 0 sustained over 1 minute
- CloudWatch alarm on `ConsumedReadCapacityUnits` or `ConsumedWriteCapacityUnits` approaching provisioned limits
- Application-level 400 errors with `ProvisionedThroughputExceededException`

**Impact:**
- Medium. API requests experience elevated latency or 429 errors. Email receiving pipeline may queue up. On-demand billing mode tables auto-scale but may have brief burst limitations.

**Automated Response:**
- DynamoDB auto-scaling adjusts provisioned capacity (if using provisioned mode)
- On-demand tables handle traffic spikes automatically (but have per-partition limits)
- Application-level exponential backoff with jitter retries throttled requests
- CloudWatch alarm triggers notification

**Manual Response:**

```
RUNBOOK: DynamoDB Throttling
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. IDENTIFY the affected table and operation type:
   aws cloudwatch get-metric-data \
     --metric-data-queries '[{
       "Id": "throttles",
       "MetricStat": {
         "Metric": {
           "Namespace": "AWS/DynamoDB",
           "MetricName": "ThrottledRequests",
           "Dimensions": [{"Name": "TableName", "Value": "<TABLE_NAME>"}]
         },
         "Period": 60,
         "Stat": "Sum"
       }
     }]' \
     --start-time $(date -u -d '15 minutes ago' +%Y-%m-%dT%H:%M:%S) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%S)

2. CHECK current capacity mode:
   aws dynamodb describe-table --table-name <TABLE_NAME> \
     --query 'Table.BillingModeSummary'

3. IF provisioned mode → SWITCH to on-demand (immediate relief):
   aws dynamodb update-table \
     --table-name <TABLE_NAME> \
     --billing-mode PAY_PER_REQUEST
   # Note: Cannot switch back to provisioned for 24 hours

4. IF on-demand mode and hitting per-partition limits:
   a. IDENTIFY hot partition keys:
      - Enable DynamoDB Contributor Insights:
        aws dynamodb update-contributor-insights \
          --table-name <TABLE_NAME> \
          --contributor-insights-action ENABLE
      - Review most accessed keys in CloudWatch

   b. IMPLEMENT write sharding if single key is hot:
      - Add random suffix to partition key (e.g., orgId#<0-9>)
      - Update application code to scatter writes

5. IF burst traffic from a single org:
   a. CHECK per-org request rates in application metrics
   b. APPLY org-level rate limiting:
      - Update rate limit configuration in Parameter Store
      - Lambda picks up new limits on next cold start (or force redeploy)

6. IF global table limit reached:
   a. Request table limit increase via AWS Support
   b. TEMPORARY: Enable request queuing in SQS to buffer writes

7. VERIFY recovery:
   - ThrottledRequests returns to 0
   - API latency p99 returns to < 200ms
   - No messages accumulating in DLQ
```

**RTO:** < 5 minutes (auto-scaling), < 30 minutes (manual intervention for hot partitions)

---

### 2.3 SES Regional Outage

**Detection:**
- CloudWatch alarm on `ses:Send` errors exceeding 5% over 5 minutes
- Bounce rate spike (CloudWatch `Bounce` metric)
- SES sending quota returning errors
- AWS Health Dashboard notification for SES in us-east-1

**Impact:**
- Critical. No outbound email delivery. Inbound email receiving may also be affected if SES receipt rules are impacted. This is a P0 service failure.

**Automated Response:**
- CloudWatch alarm fires, SNS notification to all on-call channels
- If multi-region is configured: Route 53 health check triggers failover to secondary region SES

**Manual Response:**

```
RUNBOOK: SES Regional Outage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IMMEDIATE (0-15 minutes):

1. CONFIRM SES outage (distinguish from account-level sending pause):
   aws ses get-send-quota --region us-east-1
   aws ses get-account --region us-east-1
   # Check AWS Health Dashboard: https://health.aws.amazon.com/

2. CHECK if this is a sending reputation issue vs regional outage:
   aws ses get-account --query 'SendingEnabled'
   aws ses get-account --query 'EnforcementStatus'
   # If EnforcementStatus is "PAUSED" → this is a reputation issue, not a regional outage
   # Follow reputation recovery process instead

3. VERIFY inbound email status:
   aws ses describe-active-receipt-rule-set --region us-east-1
   # Test inbound by sending a test email to a monitored inbox

SHORT-TERM MITIGATION (15-60 minutes):

4. IF multi-region failover is available (Phase 2+):
   a. Verify SES is healthy in secondary region:
      aws ses get-send-quota --region eu-west-1
   b. Update DNS MX records to point to secondary region:
      aws route53 change-resource-record-sets --hosted-zone-id <ZONE_ID> \
        --change-batch '{
          "Changes": [{
            "Action": "UPSERT",
            "ResourceRecordSet": {
              "Name": "mail.agentmail.aws",
              "Type": "MX",
              "TTL": 60,
              "ResourceRecords": [{"Value": "10 inbound-smtp.eu-west-1.amazonaws.com"}]
            }
          }]
        }'
   c. Update application configuration to use eu-west-1 SES endpoint:
      aws ssm put-parameter \
        --name /agentmail/ses/region \
        --value eu-west-1 \
        --overwrite
   d. Redeploy affected Lambda functions (or trigger configuration refresh)

5. IF no multi-region failover:
   a. Queue outbound emails in SQS with delayed retry:
      - Emails are already queued via the send pipeline
      - Increase SQS visibility timeout to 15 minutes
      - Set max receive count to 48 (12 hours of retries at 15-min intervals)
   b. Communicate to customers:
      - Update status page (status.agentmail.aws)
      - Send notification via alternate channel (not email!)
      - Post ETA based on AWS Health Dashboard

RECOVERY (when SES is restored):

6. VERIFY SES functionality:
   aws ses send-email --region us-east-1 \
     --from noreply@agentmail.aws \
     --to ops-test@agentmail.aws \
     --subject "SES Recovery Test" \
     --text "Testing SES recovery at $(date -u)"

7. DRAIN queued emails:
   - SQS consumers will automatically retry queued messages
   - Monitor SQS ApproximateNumberOfMessagesVisible metric
   - Watch for bounce rate spikes from stale messages

8. IF failover was activated → FAILBACK:
   a. Wait 30 minutes with primary region healthy
   b. Revert MX records to us-east-1
   c. Revert application SES region parameter
   d. Monitor for 1 hour before closing incident

9. POST-INCIDENT:
   - Audit all queued messages for delivery status
   - Reconcile sent vs delivered counts
   - Update customers on resolution
```

**RTO:** 1-4 hours (depending on multi-region readiness)

---

### 2.4 S3 Regional Degradation

**Detection:**
- CloudWatch alarm on S3 `5xxErrors` exceeding threshold
- Elevated latency on `GetObject` / `PutObject` (> 500ms p99)
- Application errors reading raw email or attachments
- AWS Health Dashboard notification

**Impact:**
- High. Email attachments cannot be retrieved or stored. Raw email storage may fail. New inbound emails that cannot be stored in S3 are lost unless buffered. Existing DynamoDB metadata remains accessible.

**Automated Response:**
- S3 cross-region replication (CRR) ensures data exists in secondary region
- Application retries S3 operations with exponential backoff
- CloudWatch alarm triggers notification

**Manual Response:**

```
RUNBOOK: S3 Regional Degradation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. CONFIRM S3 degradation scope:
   aws s3api head-bucket --bucket agentmail-raw-email-us-east-1
   aws s3api head-bucket --bucket agentmail-attachments-us-east-1
   # Time the requests -- degradation often manifests as extreme latency

2. TEST object access:
   aws s3api head-object \
     --bucket agentmail-raw-email-us-east-1 \
     --key test/health-check-object

3. IF writes are failing → BUFFER inbound email:
   a. SES receipt rule stores email in S3; if S3 is down, configure fallback:
      - Update receipt rule to invoke Lambda directly (skip S3 action)
      - Lambda stores raw email in DynamoDB as base64 (temporary, for small emails)
      - Queue large emails in SQS for retry when S3 recovers

4. IF reads are failing → FAILOVER to replica bucket:
   a. Verify replica bucket health:
      aws s3api head-bucket --bucket agentmail-raw-email-eu-west-1
   b. Update application to read from replica:
      aws ssm put-parameter \
        --name /agentmail/s3/raw-email-bucket \
        --value agentmail-raw-email-eu-west-1 \
        --overwrite
   c. Redeploy or trigger configuration refresh

5. IF partial degradation (some prefixes affected):
   a. Identify affected key prefixes
   b. Reroute affected org traffic if prefix-based partitioning is in use

6. RECOVERY:
   a. Verify S3 operations return to normal latency
   b. Revert bucket configuration to primary
   c. Verify CRR is caught up (check replication metrics)
   d. Process any buffered emails from DynamoDB/SQS fallback

7. VERIFY:
   - S3 GetObject p99 latency < 100ms
   - No 5xx errors in trailing 5-minute window
   - Attachment retrieval working end-to-end
```

**RTO:** 1-2 hours

---

### 2.5 Full us-east-1 Outage

**Detection:**
- Route 53 health checks fail for all endpoints in us-east-1
- Multiple CloudWatch alarms fire simultaneously
- AWS Health Dashboard shows regional issue
- External monitoring (e.g., third-party uptime service) reports AgentMail unreachable

**Impact:**
- Critical. Complete service outage -- no API, no email processing, no console access. This is a total P0/P1/P2/P3 failure.

**Automated Response:**
- Route 53 health checks detect failure within 30 seconds (3 consecutive failed checks at 10-second intervals)
- DNS automatically fails over to secondary region (eu-west-1) if multi-region is configured
- If no multi-region: all automated systems are down, manual intervention required

**Manual Response:**

```
RUNBOOK: Full us-east-1 Outage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PHASE 1 -- CONFIRM AND COMMUNICATE (0-15 minutes):

1. CONFIRM regional outage (verify it is not account-specific):
   - Check AWS Health Dashboard: https://health.aws.amazon.com/
   - Check third-party status: https://downdetector.com/status/aws/
   - Try accessing AWS Console in us-east-1
   - Note: If us-east-1 is down, CloudWatch alarms in us-east-1 may not fire.
     Use cross-region monitoring or external services.

2. DECLARE INCIDENT:
   - Page all on-call engineers (use phone/SMS, not email)
   - Open incident Slack channel: #incident-YYYY-MM-DD
   - Assign roles: Incident Commander, Communications Lead, Technical Lead

3. COMMUNICATE:
   - Update status page (hosted outside us-east-1): status.agentmail.aws
   - Post to social media / support channels
   - Send push notifications to mobile app users (if available)

PHASE 2 -- FAILOVER (15-60 minutes):

4. IF multi-region failover is configured (Phase 2+):
   a. Verify Route 53 has automatically failed over:
      dig api.agentmail.aws +short
      # Should resolve to eu-west-1 endpoints
   b. IF automatic failover did not trigger:
      aws route53 change-resource-record-sets --hosted-zone-id <ZONE_ID> \
        --change-batch file://failover-to-eu-west-1.json
   c. Verify secondary region services:
      - API Gateway: curl https://api-eu.agentmail.aws/health
      - DynamoDB Global Table: aws dynamodb describe-table \
          --table-name agentmail-messages --region eu-west-1
      - SES: aws ses get-send-quota --region eu-west-1
   d. Verify data freshness:
      - DynamoDB Global Table replication lag (should be < 1 second)
      - S3 CRR lag (check last replicated object timestamp)

5. IF no multi-region failover:
   a. This is a total outage -- service is unavailable until us-east-1 recovers
   b. Focus on communication and preparation:
      - Prepare deployment scripts for secondary region
      - If outage extends beyond 2 hours, consider emergency deployment to eu-west-1
   c. Emergency secondary region deployment (if needed):
      - Deploy CDK stacks to eu-west-1 (pre-tested via DR drills)
      - Restore DynamoDB from cross-region backup
      - Configure SES in eu-west-1 (domain verification, DKIM, etc.)
      - Update DNS to point to new endpoints

PHASE 3 -- DEGRADED OPERATION (ongoing during outage):

6. IN SECONDARY REGION:
   - P0: Email send/receive operational via eu-west-1 SES
   - P1: API serving from DynamoDB Global Table replica
   - P2: AI features may be degraded (Bedrock regional availability varies)
   - P2: IMAP/SMTP bridge needs redeployment (Fargate in new region)
   - P3: OpenSearch stale -- degrade search to DynamoDB queries
   - P3: Metrics/analytics unavailable until rebuilt

7. KNOWN LIMITATIONS during failover:
   - OpenSearch index may be stale (last hourly snapshot)
   - Redis cache is empty (rebuilds on miss, performance degraded initially)
   - Kinesis streams not replicated (events regenerated from SES in secondary)
   - Some Cognito sessions may need re-authentication

PHASE 4 -- FAILBACK (after us-east-1 recovers):
   → See Section 4 "Failback Process"
```

**RTO:** 2-4 hours (with multi-region), 4-8 hours (emergency deployment)

---

### 2.6 DynamoDB Table Corruption

**Detection:**
- Application errors reading/writing specific items or ranges
- Data inconsistency detected by integrity checks (Section 5)
- Unexpected scan results (missing items, garbled attributes)
- Customer reports of missing or incorrect data

**Impact:**
- Critical. Data loss or data integrity issues affecting one or more organizations. May cascade to inconsistent state between DynamoDB, S3, and OpenSearch.

**Automated Response:**
- No automated response for corruption (requires human judgment on scope and recovery point)
- CloudWatch alarm on elevated DynamoDB error rates triggers notification

**Manual Response:**

```
RUNBOOK: DynamoDB Table Corruption
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IMMEDIATE (0-15 minutes):

1. ASSESS scope of corruption:
   a. Is it a single item, a partition, or the entire table?
      aws dynamodb query --table-name <TABLE> \
        --key-condition-expression "PK = :pk" \
        --expression-attribute-values '{":pk": {"S": "<KNOWN_GOOD_KEY>"}}' \
        --limit 10
   b. Test multiple partitions to determine scope
   c. Check if corruption is in base table, GSI, or both

2. HALT writes to prevent further corruption:
   a. If single-org corruption:
      - Set org status to "maintenance" in org table
      - Return 503 for affected org's API requests
   b. If table-wide corruption:
      - Disable Lambda triggers that write to the table
      - Return 503 for all API requests
      - Do NOT delete or modify the corrupted table yet

3. DETERMINE the corruption timestamp:
   a. Review CloudTrail for recent table modifications:
      aws cloudtrail lookup-events \
        --lookup-attributes AttributeKey=ResourceType,AttributeValue=AWS::DynamoDB::Table \
        --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
        --region us-east-1
   b. Check DynamoDB Streams for anomalous writes
   c. Interview recent deployers -- was there a bad migration script?

RECOVERY (15 minutes - 2 hours):

4. CHOOSE recovery method based on scope:

   OPTION A -- Point-in-Time Recovery (best for table-wide issues):
   aws dynamodb restore-table-to-point-in-time \
     --source-table-name agentmail-messages \
     --target-table-name agentmail-messages-restored-$(date +%s) \
     --restore-date-time <TIMESTAMP_BEFORE_CORRUPTION>
   # Note: Restored table does not include GSIs, auto-scaling, or IAM policies.
   # These must be reconfigured manually.

   OPTION B -- On-demand backup restore (for known-good daily snapshot):
   aws dynamodb list-backups --table-name agentmail-messages
   aws dynamodb restore-table-from-backup \
     --target-table-name agentmail-messages-restored-$(date +%s) \
     --backup-arn <BACKUP_ARN>

   OPTION C -- Selective item repair (for single-org corruption):
   # Export affected partition from PITR-restored table
   # Selectively overwrite corrupted items in production table
   # This preserves all other data and minimizes downtime

5. VALIDATE restored data:
   a. Compare item counts between original and restored table
   b. Spot-check known records across multiple orgs
   c. Run integrity check (Section 5) against restored table

6. SWAP tables (if using Option A or B):
   a. Rename current table (keep as evidence):
      # DynamoDB does not support rename -- use application config swap
      aws ssm put-parameter \
        --name /agentmail/dynamodb/messages-table \
        --value agentmail-messages-restored-<TIMESTAMP> \
        --overwrite
   b. Recreate GSIs on restored table
   c. Re-enable DynamoDB Streams on restored table
   d. Update Lambda event source mappings to new stream ARN
   e. Redeploy application with new table name

7. REPLAY lost writes (between PITR point and corruption detection):
   a. Identify writes from application logs (CloudWatch Logs)
   b. Replay from SQS DLQ if applicable
   c. Re-process inbound emails from S3 raw email store
   d. Accept that some real-time writes may be lost -- notify affected orgs

8. VERIFY and RESUME:
   - Run full integrity check (Section 5)
   - Resume writes (remove maintenance mode)
   - Monitor closely for 2 hours
   - Keep corrupted table for 7 days for forensic analysis
```

**RTO:** 1-2 hours

---

### 2.7 Redis Cluster Failure

**Detection:**
- ElastiCache CloudWatch alarm on `EngineCPUUtilization`, `CurrConnections`, or `ReplicationLag`
- Application errors on cache read/write with connection timeout or `CLUSTERDOWN`
- Elevated API latency (cache misses falling through to DynamoDB)

**Impact:**
- Medium. All cached data (session tokens, rate limit counters, frequently accessed metadata) must be re-fetched from DynamoDB. API latency increases 2-5x during cache rebuild. Rate limiting may be temporarily inaccurate.

**Automated Response:**
- ElastiCache Multi-AZ automatic failover promotes replica to primary (< 60 seconds)
- Application cache-miss path falls through to DynamoDB (degraded but functional)
- CloudWatch alarm triggers notification

**Manual Response:**

```
RUNBOOK: Redis Cluster Failure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ASSESS cluster status:
   aws elasticache describe-replication-groups \
     --replication-group-id agentmail-redis \
     --query 'ReplicationGroups[0].{Status:Status,NodeGroups:NodeGroups}'

2. IF automatic failover succeeded:
   a. Verify new primary is serving requests:
      redis-cli -h <NEW_PRIMARY_ENDPOINT> -p 6379 PING
   b. Check replication lag on remaining replicas:
      redis-cli -h <NEW_PRIMARY_ENDPOINT> INFO replication
   c. No further action needed -- cache rebuilds on miss

3. IF automatic failover failed or cluster is fully down:
   a. Attempt manual failover:
      aws elasticache modify-replication-group \
        --replication-group-id agentmail-redis \
        --primary-cluster-id agentmail-redis-002  # promote a replica
   b. IF no replicas available, restore from snapshot:
      aws elasticache describe-snapshots \
        --replication-group-id agentmail-redis \
        --query 'Snapshots | sort_by(@, &SnapshotCreateTime) | [-1]'
      aws elasticache create-replication-group \
        --replication-group-id agentmail-redis-restored \
        --replication-group-description "Restored from snapshot" \
        --snapshot-name <LATEST_SNAPSHOT> \
        --automatic-failover-enabled \
        --num-cache-clusters 3

   c. Update application endpoint:
      aws ssm put-parameter \
        --name /agentmail/redis/endpoint \
        --value <NEW_ENDPOINT> \
        --overwrite

4. MITIGATE during recovery:
   - Application gracefully degrades: all cache misses served from DynamoDB
   - Rate limiting falls back to DynamoDB-based counters (less precise)
   - Session tokens validated against Cognito directly (slower)
   - Monitor DynamoDB consumed capacity -- may need to scale up temporarily

5. POST-RECOVERY:
   - Cache rebuilds organically as requests come in (no manual warming needed)
   - Monitor cache hit ratio -- should return to > 90% within 30 minutes
   - Verify rate limiting is functioning correctly
```

**RTO:** 15-30 minutes

---

### 2.8 Kinesis Shard Failure

**Detection:**
- CloudWatch alarm on `ReadProvisionedThroughputExceeded` or `WriteProvisionedThroughputExceeded`
- CloudWatch alarm on `GetRecords.IteratorAgeMilliseconds` exceeding 60,000ms (1 minute behind)
- Lambda consumer `IteratorAge` metric increasing
- Webhook delivery delays reported by customers

**Impact:**
- Medium. Real-time events (webhooks, email notifications) are delayed. Email processing continues (SES -> S3 -> Lambda pipeline is independent of Kinesis). Events are not lost due to Kinesis 24-hour retention.

**Automated Response:**
- Kinesis automatically redistributes data across healthy shards
- Lambda event source mapping retries from last successful checkpoint
- Enhanced fan-out consumers are isolated from each other

**Manual Response:**

```
RUNBOOK: Kinesis Shard Failure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. ASSESS stream health:
   aws kinesis describe-stream-summary \
     --stream-name agentmail-events
   aws kinesis list-shards \
     --stream-name agentmail-events \
     --query 'Shards[].{ShardId:ShardId,Status:SequenceNumberRange}'

2. CHECK consumer lag:
   aws cloudwatch get-metric-data \
     --metric-data-queries '[{
       "Id": "age",
       "MetricStat": {
         "Metric": {
           "Namespace": "AWS/Kinesis",
           "MetricName": "GetRecords.IteratorAgeMilliseconds",
           "Dimensions": [{"Name": "StreamName", "Value": "agentmail-events"}]
         },
         "Period": 60,
         "Stat": "Maximum"
       }
     }]' \
     --start-time $(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%S) \
     --end-time $(date -u +%Y-%m-%dT%H:%M:%S)

3. IF throughput exceeded → SCALE shards:
   aws kinesis update-shard-count \
     --stream-name agentmail-events \
     --target-shard-count <NEW_COUNT> \
     --scaling-type UNIFORM_SCALING

4. IF individual shard is stuck:
   a. Identify the problematic shard from metrics
   b. Split or merge the shard:
      aws kinesis split-shard \
        --stream-name agentmail-events \
        --shard-to-split <SHARD_ID> \
        --new-starting-hash-key <MIDPOINT>

5. IF consumer Lambda is failing:
   a. Check Lambda error logs
   b. Reset iterator if needed (skip bad records):
      aws lambda update-event-source-mapping \
        --uuid <MAPPING_UUID> \
        --starting-position LATEST
      # WARNING: This skips unprocessed records. Only use if records
      # can be reconstructed from DynamoDB Streams or are non-critical.

6. VERIFY:
   - IteratorAge returns to < 1000ms
   - Webhook delivery latency returns to normal
   - No records in DLQ
```

**RTO:** < 5 minutes (automatic), < 15 minutes (manual scaling)

---

### 2.9 API Gateway Outage

**Detection:**
- External health check (third-party uptime monitor) returns non-200 for `api.agentmail.aws/health`
- CloudWatch alarm on API Gateway `5XXError` count
- Customer reports of API unavailability
- AWS Health Dashboard notification

**Impact:**
- Critical. No API access -- customers cannot manage inboxes, read messages, or configure settings. Email receiving continues (SES pipeline is independent), but email sending via API is blocked.

**Automated Response:**
- Route 53 health check can failover to secondary region API Gateway (if configured)
- CloudWatch alarm triggers notification

**Manual Response:**

```
RUNBOOK: API Gateway Outage
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. CONFIRM API Gateway outage vs application error:
   curl -v https://api.agentmail.aws/health
   # 502/503 from API Gateway = Gateway issue
   # 500 from Lambda = Application issue (different runbook)

2. CHECK API Gateway status:
   aws apigateway get-rest-apis --query 'items[?name==`agentmail-api`]'
   aws apigateway get-deployments --rest-api-id <API_ID>

3. IF recent deployment caused the issue:
   a. Roll back to previous stage deployment:
      aws apigateway update-stage \
        --rest-api-id <API_ID> \
        --stage-name prod \
        --patch-operations op=replace,path=/deploymentId,value=<PREVIOUS_DEPLOYMENT_ID>
   b. Verify rollback: curl https://api.agentmail.aws/health

4. IF AWS-level API Gateway outage:
   a. This is an AWS service issue -- no direct remediation available
   b. IF multi-region: verify Route 53 failover activated
   c. IF no multi-region:
      - Communicate outage to customers
      - Consider temporary direct Lambda invocation for critical operations:
        aws lambda invoke --function-name agentmail-send-email \
          --payload '{"orgId": "<ORG>", "to": "<TO>", ...}' \
          response.json
      - This is emergency-only and bypasses auth/rate-limiting

5. ALTERNATIVE ACCESS (during extended outage):
   - Direct Lambda invocation for critical operations (admin only)
   - DynamoDB direct queries for read operations (admin only)
   - SES direct API for email sending (bypasses AgentMail logic)

6. RECOVERY:
   - Verify API Gateway returns 200 on health endpoint
   - Test full API flow (create inbox, send email, receive email)
   - Monitor error rates for 30 minutes
```

**RTO:** Depends on AWS (minutes for deployment rollback, hours for service outage)

---

### 2.10 DNS (Route 53) Failure

**Detection:**
- External DNS monitoring reports resolution failure for `agentmail.aws`
- Multiple geographic regions unable to resolve AgentMail domains
- AWS Health Dashboard notification for Route 53

**Impact:**
- Critical. Service is completely unreachable. No API, no email (MX records unresolvable), no console. All service tiers affected.

**Automated Response:**
- Route 53 has 100% SLA and is globally distributed; complete failure is extremely unlikely
- No automated failover exists for DNS itself (it is the failover mechanism)

**Manual Response:**

```
RUNBOOK: DNS (Route 53) Failure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. CONFIRM DNS failure scope:
   dig agentmail.aws @8.8.8.8
   dig agentmail.aws @1.1.1.1
   dig api.agentmail.aws
   dig mail.agentmail.aws MX
   # Test from multiple geographic locations using online tools:
   # https://www.whatsmydns.net/

2. DISTINGUISH between:
   a. Route 53 global outage (extremely rare, last occurred 2019)
   b. Hosted zone misconfiguration (more likely -- check recent changes)
   c. Domain registration/expiry issue

3. IF hosted zone misconfiguration:
   a. Review recent changes:
      aws route53 list-resource-record-sets --hosted-zone-id <ZONE_ID>
   b. Compare against known-good configuration (stored in CDK/CloudFormation)
   c. Restore correct records:
      aws route53 change-resource-record-sets \
        --hosted-zone-id <ZONE_ID> \
        --change-batch file://dns-records-known-good.json

4. IF domain expiry/registration issue:
   a. Check domain status:
      aws route53domains get-domain-detail --domain-name agentmail.aws
   b. Renew immediately if expired
   c. Contact AWS Support for emergency domain restoration

5. IF Route 53 global outage:
   a. This is an AWS-level incident with no direct mitigation
   b. Consider temporary workaround:
      - Publish IP addresses directly to customers
      - Use /etc/hosts entries for critical integrations
      - Consider secondary DNS provider (e.g., Cloudflare) as future mitigation

6. COMMUNICATION:
   - All normal communication channels (email, web) may be affected
   - Use social media, direct phone calls, SMS to reach customers
   - Post to third-party status aggregators

7. POST-INCIDENT:
   - Evaluate adding secondary DNS provider
   - Consider lower TTLs on critical records (tradeoff: more DNS queries)
   - Document all IP addresses for emergency bypass
```

**RTO:** Depends on AWS (Route 53 has 100% SLA; most "DNS failures" are configuration errors fixable in minutes)

---

### 2.11 Accidental Data Deletion

**Detection:**
- Customer reports missing data (inboxes, messages, orgs)
- Audit logs (CloudTrail) show unexpected `DeleteItem`, `DeleteTable`, or `DeleteObject` operations
- Integrity check (Section 5) reports missing records
- Developer reports running wrong command against production

**Impact:**
- High. Data loss ranging from single items to entire organizations depending on scope. May violate data retention agreements with customers.

**Automated Response:**
- S3 versioning preserves deleted objects (marked with delete markers)
- DynamoDB PITR allows restoration to any second within 35 days
- DynamoDB deletion protection prevents accidental table deletion
- CloudTrail logs all data plane operations for forensics

**Manual Response:**

```
RUNBOOK: Accidental Data Deletion
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. STOP THE BLEEDING:
   a. Identify the source of deletions (human, script, application bug)
   b. If a script is running: KILL IT IMMEDIATELY
   c. If application bug: disable the affected Lambda/service
   d. If human error: revoke the IAM session:
      aws iam put-user-policy --user-name <USER> \
        --policy-name EmergencyDeny \
        --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"*","Resource":"*"}]}'

2. ASSESS scope of deletion:
   a. Check CloudTrail for delete operations:
      aws cloudtrail lookup-events \
        --lookup-attributes AttributeKey=EventName,AttributeValue=DeleteItem \
        --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S)
   b. For S3 deletions:
      aws s3api list-object-versions --bucket <BUCKET> --prefix <PREFIX> \
        --query 'DeleteMarkers[?IsLatest==`true`]'

3. RECOVER S3 objects (versioning):
   a. List deleted objects:
      aws s3api list-object-versions --bucket <BUCKET> --prefix <PREFIX> \
        --query 'DeleteMarkers[?IsLatest==`true`].{Key:Key,VersionId:VersionId}'
   b. Remove delete markers to restore:
      aws s3api delete-object \
        --bucket <BUCKET> \
        --key <KEY> \
        --version-id <DELETE_MARKER_VERSION_ID>
   c. For bulk restoration, use S3 Batch Operations

4. RECOVER DynamoDB items (PITR):
   a. Determine the timestamp just before deletion
   b. Restore table to that point:
      aws dynamodb restore-table-to-point-in-time \
        --source-table-name <TABLE> \
        --target-table-name <TABLE>-restored-$(date +%s) \
        --restore-date-time <TIMESTAMP>
   c. Extract deleted items from restored table
   d. Write them back to production table:
      # Use a script to scan restored table and batch-write to production
      # Only write items that are missing from production (do not overwrite newer data)

5. RECOVER DynamoDB items (on-demand backup):
   a. If PITR window has passed, use daily backup:
      aws dynamodb list-backups --table-name <TABLE>
      aws dynamodb restore-table-from-backup \
        --target-table-name <TABLE>-from-backup \
        --backup-arn <BACKUP_ARN>

6. RECONCILE:
   a. Compare restored data against production
   b. Identify any data created AFTER the deletion that should be preserved
   c. Merge carefully -- newer data takes precedence

7. NOTIFY affected customers:
   a. Identify affected organizations from the deleted data
   b. Communicate what was lost and what was recovered
   c. Provide timeline of events

8. POST-INCIDENT:
   - Review IAM permissions -- apply least privilege
   - Add DynamoDB deletion protection if not already enabled
   - Review CI/CD pipeline for production safety guards
   - Consider adding "soft delete" pattern (mark as deleted, purge later)
```

**RTO:** 1-4 hours (depending on scope)

---

### 2.12 Security Breach (Key Compromise)

**Detection:**
- AWS GuardDuty alert for anomalous API calls
- CloudTrail shows API calls from unusual IP addresses or regions
- Unexpected resource creation (crypto mining instances, data exfiltration)
- Customer reports unauthorized access to their data
- Secrets Manager rotation failure or unexpected access patterns

**Impact:**
- Critical. Potential unauthorized access to customer data, email content, API keys, and infrastructure. Regulatory and legal implications. Reputational damage.

**Automated Response:**
- GuardDuty findings trigger SNS notification to security team
- AWS Config rules detect policy changes and non-compliant resources

**Manual Response:**

```
RUNBOOK: Security Breach (Key Compromise)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

IMMEDIATE (0-15 minutes) -- CONTAIN:

1. IDENTIFY compromised credentials:
   a. Review GuardDuty findings:
      aws guardduty list-findings --detector-id <DETECTOR_ID> \
        --finding-criteria '{"Criterion":{"severity":{"Gte":7}}}'
   b. Review CloudTrail for the compromised principal:
      aws cloudtrail lookup-events \
        --lookup-attributes AttributeKey=AccessKeyId,AttributeValue=<COMPROMISED_KEY>

2. REVOKE compromised credentials IMMEDIATELY:
   a. For IAM user access keys:
      aws iam update-access-key --access-key-id <KEY_ID> \
        --status Inactive --user-name <USER>
      aws iam delete-access-key --access-key-id <KEY_ID> \
        --user-name <USER>
   b. For IAM role (invalidate all sessions):
      aws iam put-role-policy --role-name <ROLE> \
        --policy-name EmergencyRevokeOlderSessions \
        --policy-document '{
          "Version": "2012-10-17",
          "Statement": [{
            "Effect": "Deny",
            "Action": "*",
            "Resource": "*",
            "Condition": {
              "DateLessThan": {"aws:TokenIssueTime": "'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}
            }
          }]
        }'
   c. For Cognito user pool (if user tokens compromised):
      aws cognito-idp admin-user-global-sign-out \
        --user-pool-id <POOL_ID> --username <USERNAME>

3. ROTATE all potentially affected secrets:
   aws secretsmanager rotate-secret --secret-id agentmail/ses/smtp-credentials
   aws secretsmanager rotate-secret --secret-id agentmail/api/signing-key
   # Rotate ALL secrets if scope of compromise is unclear

4. IF API keys compromised:
   a. Invalidate affected customer API keys:
      # Update DynamoDB api-keys table to revoke compromised keys
      # Issue new keys to affected customers
   b. Block known-malicious IPs at WAF:
      aws wafv2 update-ip-set --name blocked-ips --scope REGIONAL \
        --id <IP_SET_ID> --lock-token <TOKEN> \
        --addresses "<MALICIOUS_IP>/32"

INVESTIGATION (15 minutes - ongoing):

5. DETERMINE scope of breach:
   a. What data was accessed?
      - Query CloudTrail for all actions by compromised principal
      - Check S3 access logs for email/attachment downloads
      - Check DynamoDB Streams for data reads
   b. What was the attack vector?
      - Leaked credentials in code repository?
      - Phished employee credentials?
      - Exploited application vulnerability?
      - Compromised CI/CD pipeline?
   c. What is the blast radius?
      - Single org? Multiple orgs? All orgs?

6. PRESERVE EVIDENCE:
   - Snapshot CloudTrail logs to a separate, secured S3 bucket
   - Export CloudWatch Logs for affected services
   - Preserve GuardDuty findings
   - Do NOT delete or modify any resources used in the attack

REMEDIATION (hours - days):

7. AFTER containment:
   a. Patch the attack vector (fix code, rotate all credentials, etc.)
   b. Review and tighten IAM permissions
   c. Enable additional monitoring:
      - CloudTrail data events (if not already enabled)
      - VPC Flow Logs
      - S3 access logging
   d. Consider enabling AWS Security Hub for centralized findings

8. NOTIFICATION:
   a. Legal team: assess regulatory notification requirements
      - GDPR: 72-hour notification requirement if EU data affected
      - SOC 2: document incident for auditors
   b. Affected customers: transparent communication about scope and remediation
   c. AWS: report via AWS Abuse if attacker used AWS resources

9. POST-INCIDENT (within 48 hours):
   - Full post-mortem with timeline
   - Root cause analysis
   - Action items with owners and deadlines
   - Update security policies and runbooks
```

**RTO:** Immediate containment (< 15 minutes), full remediation (hours to days)

---

## 3. Backup Strategy

### Backup Summary

| Data Store | Backup Method | Frequency | Retention | Recovery Method |
|------------|--------------|-----------|-----------|----------------|
| **DynamoDB** | Point-in-Time Recovery (PITR) | Continuous | 35 days | `RestoreTableToPointInTime` |
| **DynamoDB** | On-demand backups | Daily (2:00 AM UTC) | 90 days | `RestoreTableFromBackup` |
| **S3 (raw email)** | Cross-region replication | Real-time | Same as source | Failover to replica bucket |
| **S3 (attachments)** | Versioning enabled | On every write | 30 days (noncurrent versions) | Restore from version |
| **Redis** | ElastiCache snapshots | Daily | 7 days | Restore from snapshot |
| **OpenSearch** | Automated snapshots | Hourly | 14 days | Restore from snapshot |
| **Cognito** | N/A (managed) | AWS managed | N/A | AWS manages replication and recovery |
| **Secrets Manager** | N/A (managed) | Versioned on every change | Automatic (all versions retained) | Restore previous version |

### CDK Backup Configuration

```python
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_s3 as s3,
    aws_backup as backup,
    aws_events as events,
    aws_iam as iam,
    aws_elasticache as elasticache,
    aws_lambda as lambda_,
    aws_events_targets as targets,
)
from constructs import Construct


class AgentMailBackupStack(Stack):
    """
    Backup and disaster recovery configuration for all AgentMail data stores.
    """

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # =====================================================================
        # DynamoDB: Point-in-Time Recovery (PITR)
        # =====================================================================
        # PITR is enabled per-table in the main database stack.
        # This is a reference showing the required configuration:
        #
        # messages_table = dynamodb.Table(
        #     self, "MessagesTable",
        #     table_name="agentmail-messages",
        #     partition_key=dynamodb.Attribute(
        #         name="PK", type=dynamodb.AttributeType.STRING
        #     ),
        #     sort_key=dynamodb.Attribute(
        #         name="SK", type=dynamodb.AttributeType.STRING
        #     ),
        #     billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
        #     point_in_time_recovery=True,  # ← CRITICAL: enables PITR
        #     deletion_protection=True,      # ← Prevents accidental table deletion
        #     removal_policy=RemovalPolicy.RETAIN,
        # )

        # =====================================================================
        # DynamoDB: Daily On-Demand Backups via AWS Backup
        # =====================================================================
        backup_vault = backup.BackupVault(
            self, "AgentMailBackupVault",
            backup_vault_name="agentmail-backup-vault",
            removal_policy=RemovalPolicy.RETAIN,
        )

        backup_plan = backup.BackupPlan(
            self, "DynamoDBDailyBackup",
            backup_plan_name="agentmail-dynamodb-daily",
            backup_vault=backup_vault,
        )

        # Daily backup at 2:00 AM UTC, retain for 90 days
        backup_plan.add_rule(
            backup.BackupPlanRule(
                rule_name="DailyBackup",
                schedule_expression=events.Schedule.cron(
                    hour="2", minute="0"
                ),
                start_window=Duration.hours(1),
                completion_window=Duration.hours(3),
                delete_after=Duration.days(90),
            )
        )

        # Select all DynamoDB tables tagged with backup:enabled
        backup_plan.add_selection(
            "DynamoDBTables",
            resources=[
                backup.BackupResource.from_tag("backup:enabled", "true"),
            ],
        )

        # =====================================================================
        # S3: Cross-Region Replication for Raw Email
        # =====================================================================
        # Replication role
        replication_role = iam.Role(
            self, "S3ReplicationRole",
            assumed_by=iam.ServicePrincipal("s3.amazonaws.com"),
            description="Role for S3 cross-region replication of raw email",
        )

        # Source bucket (us-east-1) -- raw email storage
        raw_email_bucket = s3.Bucket(
            self, "RawEmailBucket",
            bucket_name="agentmail-raw-email-us-east-1",
            versioned=True,  # Required for CRR
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionToIA",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        ),
                    ],
                ),
                s3.LifecycleRule(
                    id="CleanupNoncurrentVersions",
                    noncurrent_version_expiration=Duration.days(30),
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # Note: CRR destination bucket must exist in eu-west-1.
        # Cross-region replication rules are configured via CfnBucket
        # because L2 construct support for replication is limited.
        #
        # raw_email_bucket.node.default_child.add_property_override(
        #     "ReplicationConfiguration", {
        #         "Role": replication_role.role_arn,
        #         "Rules": [{
        #             "Id": "ReplicateAllObjects",
        #             "Status": "Enabled",
        #             "Destination": {
        #                 "Bucket": "arn:aws:s3:::agentmail-raw-email-eu-west-1",
        #                 "StorageClass": "STANDARD",
        #                 "ReplicationTime": {
        #                     "Status": "Enabled",
        #                     "Time": {"Minutes": 15}
        #                 },
        #                 "Metrics": {
        #                     "Status": "Enabled",
        #                     "EventThreshold": {"Minutes": 15}
        #                 }
        #             }
        #         }]
        #     }
        # )

        # Attachments bucket with versioning
        attachments_bucket = s3.Bucket(
            self, "AttachmentsBucket",
            bucket_name="agentmail-attachments-us-east-1",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="CleanupNoncurrentVersions",
                    noncurrent_version_expiration=Duration.days(30),
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # =====================================================================
        # Redis: Daily Snapshots
        # =====================================================================
        # ElastiCache snapshot configuration is set on the replication group.
        # Reference configuration:
        #
        # redis_cluster = elasticache.CfnReplicationGroup(
        #     self, "RedisCluster",
        #     replication_group_description="AgentMail Redis cluster",
        #     engine="redis",
        #     cache_node_type="cache.r6g.large",
        #     num_cache_clusters=3,
        #     automatic_failover_enabled=True,
        #     multi_az_enabled=True,
        #     at_rest_encryption_enabled=True,
        #     transit_encryption_enabled=True,
        #     snapshot_retention_limit=7,        # ← 7 daily snapshots retained
        #     snapshot_window="03:00-04:00",      # ← Daily snapshot at 3 AM UTC
        #     preferred_maintenance_window="sun:05:00-sun:06:00",
        # )

        # =====================================================================
        # OpenSearch: Automated Snapshots
        # =====================================================================
        # OpenSearch Serverless collections have automated snapshots enabled
        # by default. For managed domains, snapshots are configured as:
        #
        # opensearch_domain = opensearch.Domain(
        #     self, "SearchDomain",
        #     domain_name="agentmail-search",
        #     version=opensearch.EngineVersion.OPENSEARCH_2_11,
        #     automated_snapshot_start_hour=4,  # ← Hourly snapshots, base at 4 AM UTC
        # )
        # Retention: 14 days (configurable, max 14 for automated snapshots)
        # Manual snapshots can extend retention further if needed.

        # =====================================================================
        # Backup Monitoring: Alert on Failed Backups
        # =====================================================================
        backup_failure_rule = events.Rule(
            self, "BackupFailureRule",
            event_pattern=events.EventPattern(
                source=["aws.backup"],
                detail_type=["Backup Job State Change"],
                detail={
                    "state": ["FAILED", "EXPIRED"],
                },
            ),
        )

        # Route to SNS for alerting (SNS topic defined in observability stack)
        # backup_failure_rule.add_target(
        #     targets.SnsTopic(ops_alerts_topic)
        # )

        # =====================================================================
        # Scheduled Integrity Check Lambda
        # =====================================================================
        # See Section 5 for integrity check implementation.
        # The Lambda runs daily and compares data store consistency.
        #
        # integrity_check_fn = lambda_.Function(
        #     self, "IntegrityCheckFunction",
        #     function_name="agentmail-integrity-check",
        #     runtime=lambda_.Runtime.PYTHON_3_12,
        #     handler="integrity_check.handler",
        #     code=lambda_.Code.from_asset("lambda/integrity-check"),
        #     timeout=Duration.minutes(15),
        #     memory_size=1024,
        # )
        #
        # events.Rule(
        #     self, "DailyIntegrityCheck",
        #     schedule=events.Schedule.cron(hour="6", minute="0"),
        #     targets=[targets.LambdaFunction(integrity_check_fn)],
        # )
```

### Backup Verification

Backups are only valuable if they can be restored. Verification schedule:

| Verification | Frequency | Method |
|-------------|-----------|--------|
| DynamoDB PITR restore test | Monthly | Restore to test table, validate row counts and sample records |
| DynamoDB on-demand backup restore test | Monthly | Restore latest backup, compare against live table |
| S3 CRR lag verification | Daily (automated) | Compare object counts between source and replica buckets |
| Redis snapshot restore test | Quarterly | Restore snapshot to test cluster, verify key counts |
| OpenSearch snapshot restore test | Quarterly | Restore to test domain, verify document counts |
| Full DR drill (multi-region failover) | Quarterly | See Section 7, Chaos Engineering |

---

## 4. Multi-Region Failover (Phase 2+)

### Architecture Overview

```
                        ┌─────────────────┐
                        │    Route 53      │
                        │  Health Checks   │
                        │  + DNS Failover  │
                        └────────┬────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
            ┌───────▼───────┐         ┌──────▼────────┐
            │  us-east-1    │         │  eu-west-1    │
            │  (PRIMARY)    │         │  (SECONDARY)  │
            └───────┬───────┘         └──────┬────────┘
                    │                         │
        ┌───────────┼───────────┐    ┌───────┼────────┐
        │           │           │    │       │        │
   ┌────▼──┐  ┌────▼──┐  ┌────▼┐  ┌▼────┐ ┌▼────┐ ┌▼────┐
   │API GW │  │  SES  │  │ S3  │  │API  │ │ SES │ │ S3  │
   │       │  │       │  │     │  │GW   │ │     │ │     │
   └───┬───┘  └───┬───┘  └──┬──┘  └──┬──┘ └──┬──┘ └──┬──┘
       │          │          │        │       │       │
   ┌───▼───┐     │     ┌────▼──────────────────────────┐
   │Lambda │     │     │  DynamoDB Global Tables        │
   │       │     │     │  (automatic replication <1s)   │
   └───┬───┘     │     └───────────────────────────────┘
       │         │
   ┌───▼───┐  ┌─▼──────┐
   │Redis  │  │Kinesis │   (not replicated -- regional)
   └───────┘  └────────┘
```

### Region Configuration

| Component | Primary (us-east-1) | Secondary (eu-west-1) | Replication |
|-----------|--------------------|-----------------------|-------------|
| **DynamoDB** | Global Table (read/write) | Global Table replica (read/write) | Automatic, < 1 second lag |
| **S3 (raw email)** | Source bucket | Replica bucket | CRR with RTC, 15-minute SLA |
| **S3 (attachments)** | Source bucket | Replica bucket | CRR with RTC, 15-minute SLA |
| **SES** | Configured independently | Configured independently | No replication needed (stateless) |
| **API Gateway** | Separate deployment | Separate deployment | Both deploy same code via CI/CD |
| **Lambda** | Deployed via CDK | Deployed via CDK | Both deploy same code via CI/CD |
| **Cognito** | Primary user pool | N/A (single-region) | Users authenticate against primary; fallback is token validation only |
| **Kinesis** | Regional streams | Regional streams | Not replicated; events regenerated from SES in secondary |
| **OpenSearch** | Primary index | Secondary index | Rebuilt from DynamoDB Streams in failover region |
| **Redis** | Regional cluster | Regional cluster | Not replicated; cache rebuilds on miss |
| **Route 53** | Health checks on primary | Failover routing to secondary | Automatic failover |

### DynamoDB Global Tables Configuration

```python
from aws_cdk import aws_dynamodb as dynamodb

# Global Tables are configured by adding replicas to the table definition.
# CDK handles the replication setup automatically.

messages_table = dynamodb.Table(
    self, "MessagesTable",
    table_name="agentmail-messages",
    partition_key=dynamodb.Attribute(
        name="PK", type=dynamodb.AttributeType.STRING
    ),
    sort_key=dynamodb.Attribute(
        name="SK", type=dynamodb.AttributeType.STRING
    ),
    billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
    point_in_time_recovery=True,
    deletion_protection=True,
    replication_regions=["eu-west-1"],  # ← Enables Global Table replication
    removal_policy=RemovalPolicy.RETAIN,
)
```

### S3 Cross-Region Replication with RTC

```python
from aws_cdk import (
    aws_s3 as s3,
    aws_iam as iam,
    CfnOutput,
)

# Replication configuration (applied via L1 construct override)
# because CDK L2 does not fully support ReplicationTime Control (RTC).

raw_email_bucket_cfn = raw_email_bucket.node.default_child
raw_email_bucket_cfn.add_property_override(
    "ReplicationConfiguration",
    {
        "Role": replication_role.role_arn,
        "Rules": [
            {
                "Id": "ReplicateRawEmail",
                "Status": "Enabled",
                "Filter": {"Prefix": ""},
                "Destination": {
                    "Bucket": f"arn:aws:s3:::agentmail-raw-email-eu-west-1",
                    "StorageClass": "STANDARD",
                    "ReplicationTime": {
                        "Status": "Enabled",
                        "Time": {"Minutes": 15},
                    },
                    "Metrics": {
                        "Status": "Enabled",
                        "EventThreshold": {"Minutes": 15},
                    },
                },
                "DeleteMarkerReplication": {"Status": "Enabled"},
            }
        ],
    },
)
```

### Route 53 Health Checks and Failover

```python
from aws_cdk import (
    aws_route53 as route53,
    aws_route53_targets as r53_targets,
)

# Health check on primary API endpoint
primary_health_check = route53.CfnHealthCheck(
    self, "PrimaryHealthCheck",
    health_check_config={
        "FullyQualifiedDomainName": "api-us.agentmail.aws",
        "Port": 443,
        "Type": "HTTPS",
        "ResourcePath": "/health",
        "RequestInterval": 10,       # Check every 10 seconds
        "FailureThreshold": 3,       # 3 consecutive failures = unhealthy
        "EnableSNI": True,
    },
)

# Primary record (us-east-1 API Gateway)
route53.CfnRecordSet(
    self, "PrimaryApiRecord",
    hosted_zone_id=hosted_zone.hosted_zone_id,
    name="api.agentmail.aws",
    type="A",
    alias_target={
        "DNSName": "d-us-east-1.execute-api.us-east-1.amazonaws.com",
        "HostedZoneId": "Z1UJRXOUMOOFQ8",  # API Gateway hosted zone ID for us-east-1
        "EvaluateTargetHealth": True,
    },
    set_identifier="primary",
    failover="PRIMARY",
    health_check_id=primary_health_check.ref,
)

# Secondary record (eu-west-1 API Gateway)
route53.CfnRecordSet(
    self, "SecondaryApiRecord",
    hosted_zone_id=hosted_zone.hosted_zone_id,
    name="api.agentmail.aws",
    type="A",
    alias_target={
        "DNSName": "d-eu-west-1.execute-api.eu-west-1.amazonaws.com",
        "HostedZoneId": "ZLY8HYME6SFDD",  # API Gateway hosted zone ID for eu-west-1
        "EvaluateTargetHealth": True,
    },
    set_identifier="secondary",
    failover="SECONDARY",
)
```

### Failover Process

**Automatic failover (Route 53 health check driven):**

```
Time 0:00  - Primary region health check fails (first failure)
Time 0:10  - Second consecutive health check failure
Time 0:20  - Third consecutive failure → Route 53 marks primary UNHEALTHY
Time 0:20  - DNS begins resolving to secondary region (eu-west-1)
Time 0:20  - TTL propagation (60-second TTL on failover records)
Time ~1:20 - Majority of clients now routing to secondary region
Time ~1:20 - Secondary API Gateway serves requests from DynamoDB Global Table replica
Time ~1:20 - SES in eu-west-1 handles email send/receive
Time ~1:20 - P0 and P1 services operational in degraded mode

Degraded mode limitations:
- OpenSearch may be stale → search degrades to DynamoDB queries
- Redis cache is cold → elevated latency for first ~30 minutes
- Kinesis streams are regional → webhooks re-established in secondary
- Cognito primary may be unreachable → token validation via cached JWKS
- AI features depend on Bedrock regional availability
```

**Failover decision tree for manual triggers:**

```
IF automated failover has NOT triggered but primary appears unhealthy:

1. Verify from multiple vantage points (not just your network)
2. Check AWS Health Dashboard for known issues
3. If confirmed unhealthy for > 5 minutes with no AWS acknowledgment:
   → Manually update Route 53 to failover

   aws route53 change-resource-record-sets \
     --hosted-zone-id <ZONE_ID> \
     --change-batch '{
       "Changes": [{
         "Action": "UPSERT",
         "ResourceRecordSet": {
           "Name": "api.agentmail.aws",
           "Type": "A",
           "SetIdentifier": "primary",
           "Failover": "PRIMARY",
           "AliasTarget": {
             "DNSName": "d-eu-west-1.execute-api.eu-west-1.amazonaws.com",
             "HostedZoneId": "ZLY8HYME6SFDD",
             "EvaluateTargetHealth": true
           }
         }
       }]
     }'
```

### Failback Process (after primary recovers)

```
RUNBOOK: Failback to Primary Region
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. VERIFY primary region is stable (30-minute observation):
   a. All AWS services healthy in us-east-1 (check Health Dashboard)
   b. API Gateway health check returning 200:
      curl https://api-us.agentmail.aws/health
   c. DynamoDB accessible and responsive:
      aws dynamodb describe-table --table-name agentmail-messages --region us-east-1
   d. SES sending functional:
      aws ses get-send-quota --region us-east-1

2. VERIFY DynamoDB Global Table replication is caught up:
   a. Check replication status:
      aws dynamodb describe-table --table-name agentmail-messages \
        --query 'Table.Replicas[?RegionName==`us-east-1`].ReplicaStatus'
      # Must be "ACTIVE"
   b. Write a test item in eu-west-1, read it in us-east-1:
      aws dynamodb put-item --table-name agentmail-messages \
        --item '{"PK":{"S":"HEALTH#CHECK"},"SK":{"S":"failback-test"}}' \
        --region eu-west-1
      sleep 2
      aws dynamodb get-item --table-name agentmail-messages \
        --key '{"PK":{"S":"HEALTH#CHECK"},"SK":{"S":"failback-test"}}' \
        --region us-east-1
      # Item must be present

3. VERIFY S3 replication is caught up:
   a. Compare object counts between replica and source:
      aws s3api list-objects-v2 --bucket agentmail-raw-email-us-east-1 \
        --query 'KeyCount' --region us-east-1
      aws s3api list-objects-v2 --bucket agentmail-raw-email-eu-west-1 \
        --query 'KeyCount' --region eu-west-1
   b. Check replication metrics:
      aws s3api get-bucket-replication \
        --bucket agentmail-raw-email-us-east-1

4. RESTORE Route 53 to primary:
   a. Route 53 health check should auto-detect primary is healthy
   b. DNS will automatically route back to primary
   c. IF manual failover was performed, revert the manual change:
      aws route53 change-resource-record-sets \
        --hosted-zone-id <ZONE_ID> \
        --change-batch file://dns-records-primary.json

5. DRAIN secondary region:
   a. Wait for in-flight requests to complete (monitor API Gateway metrics in eu-west-1)
   b. Verify no new requests routing to secondary (request count should drop to ~0)
   c. Secondary region remains hot standby (do NOT tear down)

6. POST-FAILBACK verification:
   a. End-to-end test: create inbox, send email, receive email, read via API
   b. Monitor error rates for 1 hour
   c. Run integrity check (Section 5)
   d. Update status page: "All services fully restored"
```

---

## 5. Data Integrity Checks

### Scheduled Integrity Verification

| Check | Frequency | Scope | Alert Threshold |
|-------|-----------|-------|-----------------|
| DynamoDB message count vs S3 object count per inbox | Daily (6:00 AM UTC) | All active inboxes | Mismatch > 0 |
| OpenSearch document count vs DynamoDB record count | Daily (6:30 AM UTC) | All indexes | Mismatch > 1% |
| S3 inventory reconciliation with DynamoDB storage counters | Weekly (Sunday 2:00 AM UTC) | Full platform | Mismatch > 0.1% |
| Per-org integrity check | On-demand | Single organization | Any mismatch |
| Cross-region replication lag | Daily (7:00 AM UTC) | S3 CRR metrics | Lag > 15 minutes |

### Integrity Check Implementation

```python
"""
AgentMail Data Integrity Check Lambda

Scheduled daily to verify consistency across data stores:
- DynamoDB (source of truth for metadata)
- S3 (raw email and attachments)
- OpenSearch (search index)

Alerts on any discrepancies via SNS.
"""

import boto3
import json
import os
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
s3 = boto3.client("s3")
opensearch = boto3.client("opensearch")
sns = boto3.client("sns")
cloudwatch = boto3.client("cloudwatch")

MESSAGES_TABLE = os.environ["MESSAGES_TABLE"]
RAW_EMAIL_BUCKET = os.environ["RAW_EMAIL_BUCKET"]
ATTACHMENTS_BUCKET = os.environ["ATTACHMENTS_BUCKET"]
OPENSEARCH_ENDPOINT = os.environ["OPENSEARCH_ENDPOINT"]
ALERTS_TOPIC_ARN = os.environ["ALERTS_TOPIC_ARN"]


def handler(event, context):
    """
    Main integrity check handler.

    Supports two modes:
    - Scheduled: checks all orgs (event from EventBridge)
    - On-demand: checks single org (event contains org_id)
    """
    org_id = event.get("org_id")
    results = {}

    if org_id:
        results[org_id] = check_org_integrity(org_id)
    else:
        results = check_all_orgs()

    # Publish metrics
    publish_integrity_metrics(results)

    # Alert on discrepancies
    discrepancies = {
        org: result
        for org, result in results.items()
        if result.get("has_discrepancy")
    }

    if discrepancies:
        alert_discrepancies(discrepancies)

    return {
        "statusCode": 200,
        "body": json.dumps({
            "checked_orgs": len(results),
            "discrepancies": len(discrepancies),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }),
    }


def check_all_orgs():
    """Scan the orgs table and check each org."""
    table = dynamodb.Table(MESSAGES_TABLE)
    results = {}

    # Query all org records
    response = table.query(
        IndexName="GSI-OrgIndex",
        KeyConditionExpression="entity_type = :type",
        ExpressionAttributeValues={":type": "ORG"},
    )

    for item in response.get("Items", []):
        org_id = item["org_id"]
        results[org_id] = check_org_integrity(org_id)

    return results


def check_org_integrity(org_id: str) -> dict:
    """
    Check data integrity for a single organization.

    Compares:
    1. DynamoDB message count vs S3 raw email object count
    2. DynamoDB attachment references vs S3 attachment objects
    3. DynamoDB message count vs OpenSearch document count
    """
    result = {
        "org_id": org_id,
        "has_discrepancy": False,
        "checks": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # --- Check 1: DynamoDB messages vs S3 raw emails ---
    dynamo_message_count = count_dynamo_messages(org_id)
    s3_raw_email_count = count_s3_objects(
        RAW_EMAIL_BUCKET, prefix=f"{org_id}/"
    )

    msg_s3_match = dynamo_message_count == s3_raw_email_count
    result["checks"]["dynamo_vs_s3_raw"] = {
        "dynamo_count": dynamo_message_count,
        "s3_count": s3_raw_email_count,
        "match": msg_s3_match,
    }
    if not msg_s3_match:
        result["has_discrepancy"] = True

    # --- Check 2: DynamoDB attachment refs vs S3 attachment objects ---
    dynamo_attachment_count = count_dynamo_attachments(org_id)
    s3_attachment_count = count_s3_objects(
        ATTACHMENTS_BUCKET, prefix=f"{org_id}/"
    )

    att_match = dynamo_attachment_count == s3_attachment_count
    result["checks"]["dynamo_vs_s3_attachments"] = {
        "dynamo_count": dynamo_attachment_count,
        "s3_count": s3_attachment_count,
        "match": att_match,
    }
    if not att_match:
        result["has_discrepancy"] = True

    # --- Check 3: DynamoDB messages vs OpenSearch documents ---
    opensearch_doc_count = count_opensearch_docs(org_id)
    # Allow 1% tolerance for OpenSearch (eventual consistency)
    tolerance = max(1, int(dynamo_message_count * 0.01))
    os_match = abs(dynamo_message_count - opensearch_doc_count) <= tolerance

    result["checks"]["dynamo_vs_opensearch"] = {
        "dynamo_count": dynamo_message_count,
        "opensearch_count": opensearch_doc_count,
        "tolerance": tolerance,
        "match": os_match,
    }
    if not os_match:
        result["has_discrepancy"] = True

    return result


def count_dynamo_messages(org_id: str) -> int:
    """Count messages for an org in DynamoDB."""
    table = dynamodb.Table(MESSAGES_TABLE)
    count = 0
    kwargs = {
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk)",
        "ExpressionAttributeValues": {
            ":pk": f"ORG#{org_id}",
            ":sk": "MSG#",
        },
        "Select": "COUNT",
    }
    while True:
        response = table.query(**kwargs)
        count += response["Count"]
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return count


def count_dynamo_attachments(org_id: str) -> int:
    """Count attachment records for an org in DynamoDB."""
    table = dynamodb.Table(MESSAGES_TABLE)
    count = 0
    kwargs = {
        "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk)",
        "ExpressionAttributeValues": {
            ":pk": f"ORG#{org_id}",
            ":sk": "ATT#",
        },
        "Select": "COUNT",
    }
    while True:
        response = table.query(**kwargs)
        count += response["Count"]
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    return count


def count_s3_objects(bucket: str, prefix: str) -> int:
    """Count objects in an S3 bucket under a prefix."""
    count = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        count += page.get("KeyCount", 0)
    return count


def count_opensearch_docs(org_id: str) -> int:
    """Count documents for an org in OpenSearch."""
    import requests
    from requests_aws4auth import AWS4Auth

    credentials = boto3.Session().get_credentials()
    auth = AWS4Auth(
        credentials.access_key,
        credentials.secret_key,
        os.environ.get("AWS_REGION", "us-east-1"),
        "es",
        session_token=credentials.token,
    )

    url = f"{OPENSEARCH_ENDPOINT}/messages/_count"
    response = requests.get(
        url,
        auth=auth,
        json={"query": {"term": {"org_id": org_id}}},
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        return response.json().get("count", 0)
    return -1  # Error indicator


def publish_integrity_metrics(results: dict):
    """Publish integrity check results as CloudWatch metrics."""
    metric_data = []
    for org_id, result in results.items():
        metric_data.append({
            "MetricName": "IntegrityCheckDiscrepancy",
            "Dimensions": [{"Name": "OrgId", "Value": org_id}],
            "Value": 1 if result.get("has_discrepancy") else 0,
            "Unit": "Count",
        })

    # Publish in batches of 20 (CloudWatch limit)
    for i in range(0, len(metric_data), 20):
        cloudwatch.put_metric_data(
            Namespace="AgentMail/Integrity",
            MetricData=metric_data[i : i + 20],
        )


def alert_discrepancies(discrepancies: dict):
    """Send SNS alert for data discrepancies."""
    message = {
        "severity": "HIGH",
        "source": "integrity-check",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": f"Data integrity discrepancies found in {len(discrepancies)} org(s)",
        "details": discrepancies,
    }

    sns.publish(
        TopicArn=ALERTS_TOPIC_ARN,
        Subject=f"[AgentMail] Data Integrity Alert - {len(discrepancies)} org(s) affected",
        Message=json.dumps(message, indent=2, default=str),
    )
```

### On-Demand Integrity Check API

```
POST /admin/integrity-check/{org_id}

Response:
{
  "org_id": "org_abc123",
  "has_discrepancy": false,
  "checks": {
    "dynamo_vs_s3_raw": {
      "dynamo_count": 15234,
      "s3_count": 15234,
      "match": true
    },
    "dynamo_vs_s3_attachments": {
      "dynamo_count": 3421,
      "s3_count": 3421,
      "match": true
    },
    "dynamo_vs_opensearch": {
      "dynamo_count": 15234,
      "opensearch_count": 15230,
      "tolerance": 152,
      "match": true
    }
  },
  "timestamp": "2026-04-10T12:00:00Z"
}
```

### Weekly S3 Inventory Reconciliation

```python
"""
Weekly S3 Inventory Reconciliation

Uses S3 Inventory reports to reconcile object counts with DynamoDB storage
counters. This catches drift that daily per-inbox checks might miss
(orphaned objects, missing objects in rarely-accessed inboxes, etc.).
"""

def reconcile_s3_inventory(event, context):
    """
    Triggered weekly. Reads the latest S3 Inventory manifest and compares
    total object counts and sizes against DynamoDB aggregate counters.
    """
    # 1. Read latest S3 Inventory manifest
    manifest = read_inventory_manifest(RAW_EMAIL_BUCKET)

    # 2. Parse inventory CSV files (can be large -- use streaming)
    inventory_summary = parse_inventory(manifest)
    # Returns: {org_id: {count: N, total_size: M}, ...}

    # 3. Compare against DynamoDB storage counters
    for org_id, inv_data in inventory_summary.items():
        dynamo_counters = get_org_storage_counters(org_id)

        if abs(inv_data["count"] - dynamo_counters["message_count"]) > 0:
            report_inventory_discrepancy(
                org_id=org_id,
                s3_count=inv_data["count"],
                s3_size=inv_data["total_size"],
                dynamo_count=dynamo_counters["message_count"],
                dynamo_size=dynamo_counters["total_storage_bytes"],
            )

    # 4. Publish reconciliation metrics
    cloudwatch.put_metric_data(
        Namespace="AgentMail/Integrity",
        MetricData=[{
            "MetricName": "WeeklyReconciliationOrgs",
            "Value": len(inventory_summary),
            "Unit": "Count",
        }],
    )
```

---

## 6. Incident Response

### Severity Levels

| Level | Criteria | Response Team | Update Cadence | Examples |
|-------|----------|---------------|----------------|----------|
| **SEV1** | Full service outage or data loss affecting multiple orgs | All hands (engineering + leadership) | Every 15 minutes | Full regional outage, DynamoDB corruption, security breach |
| **SEV2** | Partial outage or degraded service | On-call team (2-3 engineers) | Every 30 minutes | SES regional outage, API Gateway errors > 10%, single-org data loss |
| **SEV3** | Minor issue affecting single feature | On-call engineer | Every 60 minutes | IMAP bridge degraded, search index stale, webhook delays > 5 min |
| **SEV4** | Cosmetic or documentation issue | Next business day | As needed | Console UI glitch, API documentation error, non-functional metric |

### Incident Response Process

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   DETECT     │────▶│   RESPOND    │────▶│   RECOVER    │────▶│   REVIEW     │
│              │     │              │     │              │     │              │
│ - Alarms     │     │ - Classify   │     │ - Execute    │     │ - Post-      │
│ - Health     │     │ - Page team  │     │   runbook    │     │   mortem     │
│   checks     │     │ - Assign     │     │ - Verify     │     │ - Action     │
│ - Customer   │     │   roles      │     │   recovery   │     │   items      │
│   reports    │     │ - Contain    │     │ - Restore    │     │ - Improve    │
│              │     │              │     │   service    │     │   runbooks   │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

### Incident Roles

| Role | Responsibility | Who |
|------|---------------|-----|
| **Incident Commander (IC)** | Owns the incident. Makes decisions, delegates tasks, manages timeline. Does NOT do hands-on troubleshooting. | Senior engineer or engineering manager on rotation |
| **Technical Lead** | Hands-on troubleshooting. Executes runbooks, investigates root cause, implements fixes. | On-call engineer closest to the affected system |
| **Communications Lead** | Updates status page, notifies customers, manages Slack channel, writes external communications. | Product manager or designated communicator |
| **Scribe** | Documents timeline, decisions, and actions in real time. This becomes the basis for the post-mortem. | Any available team member |

### Communication Plan

**Internal communication:**

| Channel | Purpose | Audience |
|---------|---------|----------|
| Slack `#incident-YYYY-MM-DD-<title>` | Real-time incident coordination | All responders |
| Slack `#ops-alerts` | Automated alarm notifications | Engineering team |
| PagerDuty | On-call paging for SEV1/SEV2 | On-call rotation |
| Email | Incident summary after resolution | Full engineering team |

**External communication:**

| Channel | Purpose | SLA |
|---------|---------|-----|
| Status page (status.agentmail.aws) | Public incident status | Updated within 10 minutes of SEV1/SEV2 detection |
| Email to affected orgs | Direct notification | Within 30 minutes of SEV1, 1 hour of SEV2 |
| API response headers | Degraded mode indicator | Real-time (`X-AgentMail-Status: degraded`) |

**Status page update template (SEV1/SEV2):**

```
Title: [Investigating/Identified/Monitoring/Resolved] - <Brief Description>

Body:
We are currently [investigating/experiencing] [issue description].

Impact: [What is affected — be specific]
- Email sending: [operational/degraded/down]
- Email receiving: [operational/degraded/down]
- API: [operational/degraded/down]
- Console: [operational/degraded/down]

Current status: [What we know and what we're doing]
Next update: [Time of next update]

---
Last updated: [Timestamp UTC]
```

### Post-Mortem Process

All SEV1 and SEV2 incidents require a post-mortem within 48 hours of resolution.

**Post-mortem template:**

```markdown
# Post-Mortem: [Incident Title]

**Date:** YYYY-MM-DD
**Duration:** HH:MM (from detection to resolution)
**Severity:** SEV1/SEV2
**Incident Commander:** [Name]
**Author:** [Name]

## Summary
[1-2 sentence summary of what happened and the impact]

## Impact
- Duration of customer impact: [duration]
- Number of affected organizations: [count]
- Messages delayed/lost: [count]
- Revenue impact: [estimate if applicable]

## Timeline (all times UTC)
| Time | Event |
|------|-------|
| HH:MM | [First detection signal] |
| HH:MM | [Incident declared] |
| HH:MM | [Key actions taken] |
| HH:MM | [Resolution] |
| HH:MM | [All-clear confirmed] |

## Root Cause
[Detailed technical explanation of what caused the incident]

## What Went Well
- [Things that worked as expected]

## What Went Poorly
- [Things that did not work or were slower than expected]

## Action Items
| Priority | Action | Owner | Due Date |
|----------|--------|-------|----------|
| P0 | [Critical fix] | [Name] | [Date] |
| P1 | [Important improvement] | [Name] | [Date] |
| P2 | [Nice-to-have improvement] | [Name] | [Date] |

## Lessons Learned
[Key takeaways for the team]
```

### Escalation Matrix

```
Time Since Detection    Action
─────────────────────   ──────────────────────────────────────────
0 min                   Automated alarm fires → on-call paged
5 min                   If no acknowledgment → page backup on-call
15 min                  If SEV1 → page engineering manager
30 min                  If SEV1 unresolved → page VP Engineering
60 min                  If SEV1 unresolved → page CTO
2 hours                 If SEV1 unresolved → executive briefing
```

---

## 7. Chaos Engineering (Future)

### Overview

Chaos engineering validates that our disaster recovery procedures work as expected. We use AWS Fault Injection Simulator (FIS) to inject controlled failures in non-production environments, then graduate to production with safeguards.

### FIS Experiment Catalog

| Experiment | Target | Expected Behavior | Environment |
|-----------|--------|-------------------|-------------|
| Lambda function failure | Random Lambda invocation errors (50% error rate) | Auto-retry succeeds; DLQ catches persistent failures; alarm fires | Staging, then Production |
| DynamoDB throttling | Inject `ProvisionedThroughputExceededException` | Application retries with backoff; API returns 429 to clients; alarm fires | Staging |
| Network partition | Block connectivity between Lambda and DynamoDB | Circuit breaker activates; cached responses served; alarm fires | Staging |
| SES sending failure | Simulate SES `MessageRejected` errors | Emails queued in SQS; retry logic engages; alarm fires; status page updated | Staging |
| Redis failure | Terminate Redis primary node | ElastiCache failover promotes replica; application falls back to DynamoDB | Staging, then Production |
| S3 latency injection | Add 5-second delay to S3 API calls | Application timeout handling; attachment retrieval degrades gracefully | Staging |
| Full AZ failure | Terminate all resources in one AZ | Multi-AZ services failover; Lambda executes in remaining AZs; no customer impact | Staging |

### FIS Experiment Template (Lambda Failure)

```json
{
  "description": "Inject errors into AgentMail email processing Lambda",
  "targets": {
    "emailProcessorLambda": {
      "resourceType": "aws:lambda:function",
      "resourceArns": [
        "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-process-email"
      ],
      "selectionMode": "ALL"
    }
  },
  "actions": {
    "injectLambdaErrors": {
      "actionId": "aws:lambda:invocation-add-delay",
      "parameters": {
        "duration": "PT5M",
        "invocationPercentage": "50"
      },
      "targets": {
        "Functions": "emailProcessorLambda"
      }
    }
  },
  "stopConditions": [
    {
      "source": "aws:cloudwatch:alarm",
      "value": "arn:aws:cloudwatch:us-east-1:ACCOUNT:alarm:agentmail-email-processing-critical"
    }
  ],
  "roleArn": "arn:aws:iam::ACCOUNT:role/agentmail-fis-role",
  "tags": {
    "Environment": "staging",
    "Team": "platform"
  }
}
```

### Game Day Schedule

| Frequency | Scope | Participants | Duration |
|-----------|-------|-------------|----------|
| **Monthly** | Single-service failure (FIS experiment in staging) | On-call engineer + 1 observer | 2 hours |
| **Quarterly** | Multi-service failure or regional failover drill | Full engineering team | Half day |
| **Annually** | Full DR drill (failover to secondary region, operate for 4 hours, failback) | Full engineering team + leadership | Full day |

### Game Day Runbook

```
GAME DAY: Regional Failover Drill
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PRE-DRILL (1 week before):
1. Announce drill date to all stakeholders
2. Verify secondary region is deployed and healthy
3. Ensure all runbooks are up to date
4. Prepare monitoring dashboards for both regions
5. Confirm rollback plan is tested

DRILL EXECUTION:

Phase 1 -- Simulate Primary Failure (30 min)
  1. Disable Route 53 health check (simulate health check failure)
  2. Observe: Does DNS failover trigger automatically?
  3. Measure: Time from "failure" to secondary region serving traffic
  4. Verify: All P0 services operational in secondary region

Phase 2 -- Operate in Secondary Region (2 hours)
  1. Run full integration test suite against secondary region
  2. Send and receive test emails
  3. Create inboxes, read messages, manage orgs
  4. Verify AI features (Bedrock availability in eu-west-1)
  5. Monitor DynamoDB Global Table replication
  6. Document any degradation or missing functionality

Phase 3 -- Failback (1 hour)
  1. Re-enable Route 53 health check for primary
  2. Observe: Does DNS failback trigger automatically?
  3. Verify data consistency between regions
  4. Run full integration test suite against primary region
  5. Confirm all services fully operational

Phase 4 -- Debrief (1 hour)
  1. Review timeline and measurements
  2. Document what worked and what did not
  3. Create action items for improvements
  4. Update RTOs based on actual measurements
  5. Update runbooks with lessons learned

SUCCESS CRITERIA:
  - Failover completes within RTO (30 min degraded, 4 hr full)
  - No data loss (RPO met)
  - All P0 services operational in secondary region
  - Failback completes without data loss
  - All alarms fired as expected
```

### Chaos Engineering Maturity Roadmap

| Phase | Timeline | Activities |
|-------|----------|-----------|
| **Phase 1: Foundation** | Months 1-3 | Define steady-state metrics. Run tabletop exercises (talk through scenarios without injecting faults). Implement FIS experiments for single Lambda failure in staging. |
| **Phase 2: Staging Chaos** | Months 4-6 | Run full FIS experiment catalog in staging monthly. Conduct first regional failover drill. Automate experiment scheduling. |
| **Phase 3: Production Chaos** | Months 7-12 | Graduate low-risk experiments to production (Lambda failure, Redis failover). Implement automatic rollback on safety metric violation. Conduct quarterly regional failover drills. |
| **Phase 4: Continuous Chaos** | Year 2+ | Chaos experiments run continuously in production at low blast radius. Automated game days. Chaos results feed into CI/CD pipeline (block deploys if resilience degrades). |

---

## Appendix A: Emergency Contact List

| Role | Primary | Backup | Contact Method |
|------|---------|--------|----------------|
| On-call engineer | Rotation (PagerDuty) | Rotation (PagerDuty) | PagerDuty, Phone, Slack |
| Engineering manager | [TBD] | [TBD] | Phone, Slack |
| VP Engineering | [TBD] | [TBD] | Phone |
| CTO | [TBD] | [TBD] | Phone |
| AWS Support | Enterprise Support | TAM | AWS Console, Phone |
| Domain registrar | Route 53 (AWS) | N/A | AWS Console |

## Appendix B: Known-Good DNS Configuration

Store this configuration in version control and use it for DNS restoration in emergency scenarios.

```json
{
  "Comment": "AgentMail known-good DNS configuration",
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.agentmail.aws",
        "Type": "A",
        "AliasTarget": {
          "DNSName": "d-xxxx.execute-api.us-east-1.amazonaws.com",
          "HostedZoneId": "Z1UJRXOUMOOFQ8",
          "EvaluateTargetHealth": true
        }
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "mail.agentmail.aws",
        "Type": "MX",
        "TTL": 300,
        "ResourceRecords": [
          {"Value": "10 inbound-smtp.us-east-1.amazonaws.com"}
        ]
      }
    },
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "agentmail.aws",
        "Type": "TXT",
        "TTL": 300,
        "ResourceRecords": [
          {"Value": "\"v=spf1 include:amazonses.com -all\""}
        ]
      }
    }
  ]
}
```

## Appendix C: Recovery Command Quick Reference

```bash
# DynamoDB: Restore table to point in time
aws dynamodb restore-table-to-point-in-time \
  --source-table-name <TABLE> \
  --target-table-name <TABLE>-restored-$(date +%s) \
  --restore-date-time <ISO8601_TIMESTAMP>

# DynamoDB: Restore from on-demand backup
aws dynamodb restore-table-from-backup \
  --target-table-name <TABLE>-from-backup \
  --backup-arn <BACKUP_ARN>

# S3: Restore deleted object (remove delete marker)
aws s3api delete-object \
  --bucket <BUCKET> --key <KEY> \
  --version-id <DELETE_MARKER_VERSION_ID>

# Redis: Create cluster from snapshot
aws elasticache create-replication-group \
  --replication-group-id <NEW_ID> \
  --snapshot-name <SNAPSHOT> \
  --automatic-failover-enabled \
  --num-cache-clusters 3

# SES: Switch sending region
aws ssm put-parameter \
  --name /agentmail/ses/region \
  --value eu-west-1 --overwrite

# Route 53: Manual DNS failover
aws route53 change-resource-record-sets \
  --hosted-zone-id <ZONE_ID> \
  --change-batch file://failover-to-eu-west-1.json

# IAM: Emergency revoke all sessions for a role
aws iam put-role-policy --role-name <ROLE> \
  --policy-name EmergencyRevoke \
  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Deny","Action":"*","Resource":"*","Condition":{"DateLessThan":{"aws:TokenIssueTime":"'$(date -u +%Y-%m-%dT%H:%M:%SZ)'"}}}]}'

# Secrets Manager: Restore previous secret version
aws secretsmanager get-secret-value \
  --secret-id <SECRET_ID> --version-stage AWSPREVIOUS
aws secretsmanager update-secret-version-stage \
  --secret-id <SECRET_ID> \
  --version-stage AWSCURRENT \
  --move-to-version-id <PREVIOUS_VERSION_ID> \
  --remove-from-version-id <CURRENT_VERSION_ID>
```
