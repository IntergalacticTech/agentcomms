# AI Processing Pipeline

The AI processing pipeline orchestrates text extraction, embedding generation, categorization, and structured data extraction for every inbound message. Built on AWS Step Functions Express Workflows, the pipeline runs parallel AI tasks with per-step retry, visual monitoring, and cost at $0.000025 per state transition.

---

## Why Step Functions Express Over Alternatives

### Step Functions Express vs. Standard

| Factor | Express | Standard | Decision |
|--------|---------|----------|----------|
| **Cost** | $0.000025/transition | $0.025/transition | Express is 1000x cheaper |
| **At 1M msgs/day (8 transitions each)** | $200/mo | $200,000/mo | Express saves $199,800/mo |
| **Max duration** | 5 minutes | 1 year | 5 minutes is sufficient (pipeline completes in <10s) |
| **Execution model** | Synchronous | Asynchronous | Synchronous is fine (short-lived) |
| **Execution history** | CloudWatch Logs only | Full execution history in console | Acceptable trade-off |
| **Exactly-once** | At-least-once | Exactly-once | We handle idempotency in each step |

### Step Functions vs. Pure SQS + Lambda

| Factor | Step Functions | SQS + Lambda | Decision |
|--------|---------------|-------------|----------|
| **Parallel branching** | Built-in Parallel state | Manual fan-out/fan-in with SQS | Step Functions is simpler |
| **Per-step retry** | Built-in Retry with backoff | Manual SQS visibility timeout manipulation | Step Functions is cleaner |
| **Visual monitoring** | Step Functions console graph | CloudWatch logs + custom dashboards | Step Functions wins |
| **Error handling** | Catch/Retry per state | DLQ per queue | Step Functions is more granular |
| **Cost at scale** | $0.000025/transition | $0.0000004/request + Lambda cost | SQS is cheaper per-invocation |
| **Orchestration complexity** | Declarative JSON | Imperative code in each Lambda | Step Functions is maintainable |
| **Fan-in (wait for all parallel tasks)** | Automatic | Requires DynamoDB counter or Step Functions anyway | Step Functions |

Step Functions costs more per-invocation than raw SQS, but the orchestration complexity of parallel fan-out/fan-in with per-step retry in pure SQS+Lambda is significant. At $200/mo for 1M messages/day, the orchestration cost is negligible compared to Bedrock costs ($10K+/mo).

---

## State Machine Definition

### Text Diagram

```
                    ┌─────────────────┐
                    │   StartState    │
                    │  (set defaults) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ Text Extraction │
                    │ Lambda          │
                    │ (no LLM, <50ms) │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Check Features │
                    │  (Choice state) │
                    └────┬───┬───┬────┘
                         │   │   │
              ┌──────────┘   │   └──────────┐
              │              │              │
     ┌────────▼──────┐ ┌────▼───────┐ ┌────▼──────────┐
     │  Embedding    │ │ Categorize │ │ Extract Data  │
     │  Generation   │ │ (Bedrock)  │ │ (Bedrock)     │
     │  (Bedrock     │ │            │ │               │
     │   Titan V2)   │ │ skip if    │ │ skip if no    │
     │              │ │ not config  │ │ schema defined│
     └────────┬──────┘ └────┬───────┘ └────┬──────────┘
              │              │              │
              └──────────┬───┘──────────────┘
                         │
                ┌────────▼────────┐
                │ Update Message  │
                │ Status          │
                │ (DynamoDB)      │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │ Fire Event      │
                │ message.        │
                │ ai_processed    │
                │ (Kinesis)       │
                └─────────────────┘
```

### Complete ASL (Amazon States Language) Definition

```json
{
  "Comment": "AgentMail AI Processing Pipeline - processes inbound emails through text extraction, embedding, categorization, and data extraction",
  "StartAt": "InitializeProcessing",
  "States": {
    "InitializeProcessing": {
      "Type": "Pass",
      "Parameters": {
        "messageId.$": "$.messageId",
        "inboxId.$": "$.inboxId",
        "orgId.$": "$.orgId",
        "podId.$": "$.podId",
        "s3Key.$": "$.s3Key",
        "subject.$": "$.subject",
        "from.$": "$.from",
        "to.$": "$.to",
        "receivedAt.$": "$.receivedAt",
        "hasAttachments.$": "$.hasAttachments",
        "threadId.$": "$.threadId",
        "processingStartedAt.$": "$$.Execution.StartTime",
        "features": {
          "textExtraction": { "status": "pending" },
          "embedding": { "status": "pending" },
          "categorization": { "status": "pending" },
          "extraction": { "status": "pending" }
        }
      },
      "Next": "TextExtraction"
    },

    "TextExtraction": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-text-extraction",
      "Parameters": {
        "messageId.$": "$.messageId",
        "s3Key.$": "$.s3Key",
        "inboxId.$": "$.inboxId"
      },
      "ResultPath": "$.textExtractionResult",
      "Retry": [
        {
          "ErrorEquals": ["Lambda.ServiceException", "Lambda.TooManyRequestsException"],
          "IntervalSeconds": 2,
          "MaxAttempts": 3,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "TextExtractionFailed",
          "ResultPath": "$.textExtractionError"
        }
      ],
      "TimeoutSeconds": 30,
      "Next": "CheckFeatureConfig"
    },

    "TextExtractionFailed": {
      "Type": "Pass",
      "Parameters": {
        "textExtractionResult": {
          "extracted_text": "",
          "extracted_html": "",
          "processing_time_ms": 0,
          "extraction_method": "failed",
          "error.$": "$.textExtractionError.Cause"
        }
      },
      "ResultPath": "$.textExtractionResult",
      "Next": "CheckFeatureConfig"
    },

    "CheckFeatureConfig": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-check-features",
      "Parameters": {
        "inboxId.$": "$.inboxId",
        "orgId.$": "$.orgId"
      },
      "ResultPath": "$.featureConfig",
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 1,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Next": "ParallelProcessing"
    },

    "ParallelProcessing": {
      "Type": "Parallel",
      "Branches": [
        {
          "StartAt": "ShouldEmbed",
          "States": {
            "ShouldEmbed": {
              "Type": "Choice",
              "Choices": [
                {
                  "Variable": "$.textExtractionResult.text_length",
                  "NumericGreaterThan": 0,
                  "Next": "GenerateEmbedding"
                }
              ],
              "Default": "SkipEmbedding"
            },
            "GenerateEmbedding": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-generate-embedding",
              "Parameters": {
                "messageId.$": "$.messageId",
                "orgId.$": "$.orgId",
                "podId.$": "$.podId",
                "inboxId.$": "$.inboxId",
                "subject.$": "$.subject",
                "extracted_text.$": "$.textExtractionResult.extracted_text",
                "from.$": "$.from",
                "to.$": "$.to",
                "receivedAt.$": "$.receivedAt",
                "hasAttachments.$": "$.hasAttachments",
                "threadId.$": "$.threadId"
              },
              "ResultPath": "$.embeddingResult",
              "Retry": [
                {
                  "ErrorEquals": ["ThrottlingException", "ModelTimeoutException"],
                  "IntervalSeconds": 5,
                  "MaxAttempts": 3,
                  "BackoffRate": 3
                },
                {
                  "ErrorEquals": ["Lambda.ServiceException"],
                  "IntervalSeconds": 2,
                  "MaxAttempts": 2,
                  "BackoffRate": 2
                }
              ],
              "Catch": [
                {
                  "ErrorEquals": ["States.ALL"],
                  "Next": "EmbeddingFailed",
                  "ResultPath": "$.embeddingError"
                }
              ],
              "TimeoutSeconds": 60,
              "End": true
            },
            "SkipEmbedding": {
              "Type": "Pass",
              "Result": { "status": "skipped", "reason": "no text to embed" },
              "ResultPath": "$.embeddingResult",
              "End": true
            },
            "EmbeddingFailed": {
              "Type": "Pass",
              "Parameters": {
                "embeddingResult": {
                  "status": "failed",
                  "error.$": "$.embeddingError.Cause"
                }
              },
              "ResultPath": "$.embeddingResult",
              "End": true
            }
          }
        },
        {
          "StartAt": "ShouldCategorize",
          "States": {
            "ShouldCategorize": {
              "Type": "Choice",
              "Choices": [
                {
                  "Variable": "$.featureConfig.categorizationEnabled",
                  "BooleanEquals": true,
                  "Next": "Categorize"
                }
              ],
              "Default": "SkipCategorization"
            },
            "Categorize": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-categorizer",
              "Parameters": {
                "messageId.$": "$.messageId",
                "inboxId.$": "$.inboxId",
                "orgId.$": "$.orgId",
                "subject.$": "$.subject",
                "from.$": "$.from",
                "to.$": "$.to",
                "extracted_text.$": "$.textExtractionResult.extracted_text",
                "receivedAt.$": "$.receivedAt",
                "hasAttachments.$": "$.hasAttachments",
                "threadLength.$": "$.threadLength"
              },
              "ResultPath": "$.categorizationResult",
              "Retry": [
                {
                  "ErrorEquals": ["ThrottlingException", "ModelTimeoutException"],
                  "IntervalSeconds": 5,
                  "MaxAttempts": 3,
                  "BackoffRate": 3
                },
                {
                  "ErrorEquals": ["Lambda.ServiceException"],
                  "IntervalSeconds": 2,
                  "MaxAttempts": 2,
                  "BackoffRate": 2
                }
              ],
              "Catch": [
                {
                  "ErrorEquals": ["States.ALL"],
                  "Next": "CategorizationFailed",
                  "ResultPath": "$.categorizationError"
                }
              ],
              "TimeoutSeconds": 60,
              "End": true
            },
            "SkipCategorization": {
              "Type": "Pass",
              "Result": { "status": "skipped", "reason": "not configured" },
              "ResultPath": "$.categorizationResult",
              "End": true
            },
            "CategorizationFailed": {
              "Type": "Pass",
              "Parameters": {
                "categorizationResult": {
                  "status": "failed",
                  "error.$": "$.categorizationError.Cause"
                }
              },
              "ResultPath": "$.categorizationResult",
              "End": true
            }
          }
        },
        {
          "StartAt": "ShouldExtractData",
          "States": {
            "ShouldExtractData": {
              "Type": "Choice",
              "Choices": [
                {
                  "Variable": "$.featureConfig.extractionEnabled",
                  "BooleanEquals": true,
                  "Next": "ExtractData"
                }
              ],
              "Default": "SkipExtraction"
            },
            "ExtractData": {
              "Type": "Task",
              "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-data-extractor",
              "Parameters": {
                "messageId.$": "$.messageId",
                "inboxId.$": "$.inboxId",
                "orgId.$": "$.orgId",
                "subject.$": "$.subject",
                "from.$": "$.from",
                "extracted_text.$": "$.textExtractionResult.extracted_text"
              },
              "ResultPath": "$.extractionResult",
              "Retry": [
                {
                  "ErrorEquals": ["ThrottlingException", "ModelTimeoutException"],
                  "IntervalSeconds": 5,
                  "MaxAttempts": 3,
                  "BackoffRate": 3
                },
                {
                  "ErrorEquals": ["Lambda.ServiceException"],
                  "IntervalSeconds": 2,
                  "MaxAttempts": 2,
                  "BackoffRate": 2
                }
              ],
              "Catch": [
                {
                  "ErrorEquals": ["States.ALL"],
                  "Next": "ExtractionFailed",
                  "ResultPath": "$.extractionError"
                }
              ],
              "TimeoutSeconds": 120,
              "End": true
            },
            "SkipExtraction": {
              "Type": "Pass",
              "Result": { "status": "skipped", "reason": "no schema defined" },
              "ResultPath": "$.extractionResult",
              "End": true
            },
            "ExtractionFailed": {
              "Type": "Pass",
              "Parameters": {
                "extractionResult": {
                  "status": "failed",
                  "error.$": "$.extractionError.Cause"
                }
              },
              "ResultPath": "$.extractionResult",
              "End": true
            }
          }
        }
      ],
      "ResultPath": "$.parallelResults",
      "Next": "UpdateProcessingStatus"
    },

    "UpdateProcessingStatus": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-update-processing-status",
      "Parameters": {
        "messageId.$": "$.messageId",
        "inboxId.$": "$.inboxId",
        "orgId.$": "$.orgId",
        "textExtractionResult.$": "$.textExtractionResult",
        "parallelResults.$": "$.parallelResults",
        "processingStartedAt.$": "$.processingStartedAt"
      },
      "ResultPath": "$.statusUpdateResult",
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2
        }
      ],
      "Next": "FireAIProcessedEvent"
    },

    "FireAIProcessedEvent": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:us-east-1:ACCOUNT:function:agentmail-fire-event",
      "Parameters": {
        "eventType": "message.ai_processed",
        "messageId.$": "$.messageId",
        "inboxId.$": "$.inboxId",
        "orgId.$": "$.orgId",
        "podId.$": "$.podId",
        "processingResult.$": "$.statusUpdateResult"
      },
      "Retry": [
        {
          "ErrorEquals": ["States.ALL"],
          "IntervalSeconds": 1,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "End": true
    }
  }
}
```

---

## Error Handling Per Step

### Bedrock Throttling

Bedrock enforces per-model rate limits (requests per minute, tokens per minute). When throttled, the API returns `ThrottlingException`.

```json
{
  "ErrorEquals": ["ThrottlingException", "ModelTimeoutException"],
  "IntervalSeconds": 5,
  "MaxAttempts": 3,
  "BackoffRate": 3
}
```

Retry schedule: 5s, 15s, 45s (total: 65 seconds max wait).

### Lambda Timeouts

Each step has a `TimeoutSeconds` value:

| Step | Timeout | Rationale |
|------|---------|-----------|
| Text Extraction | 30s | S3 fetch + MIME parsing; typically <1s |
| Embedding | 60s | Bedrock InvokeModel + OpenSearch index |
| Categorization | 60s | Bedrock InvokeModel + validation + retry |
| Data Extraction | 120s | Complex schemas may require longer inference |
| Status Update | 30s | DynamoDB writes |
| Fire Event | 30s | Kinesis PutRecord |

### Invalid Responses

Categorization and extraction validate model responses. Invalid responses trigger an in-Lambda retry (not Step Functions retry):

1. **First attempt:** Standard prompt
2. **Second attempt (in-Lambda):** Stricter prompt with explicit instructions
3. **Fallback:** "uncategorized" label or empty extraction with status "failed"

This avoids consuming Step Functions retries for validation issues (which are not transient errors).

### Graceful Degradation

Each parallel branch has a Catch state that captures errors and produces a "failed" result rather than failing the entire workflow. If embedding fails, categorization and extraction still proceed. The final status reflects which features succeeded:

```json
{
  "processingStatus": "partial",
  "features": {
    "textExtraction": { "status": "completed", "processingTimeMs": 23 },
    "embedding": { "status": "failed", "error": "ThrottlingException: rate exceeded" },
    "categorization": { "status": "completed", "labels": ["support"], "processingTimeMs": 890 },
    "extraction": { "status": "completed", "fieldsExtracted": 4, "processingTimeMs": 1200 }
  }
}
```

---

## Processing Status Tracking

The message record in DynamoDB tracks processing status at both aggregate and per-feature levels.

### DynamoDB Message Record (processing fields)

```
Entity: Message (processing fields)
  PK: INBOX#{inboxId}
  SK: MSG#{messageId}

  Processing Attributes:
    processing_status:     "pending" | "processing" | "completed" | "partial" | "failed"
    processing_started_at: "2026-04-10T14:30:00.123Z"
    processing_completed_at: "2026-04-10T14:30:02.578Z"
    processing_time_ms:    2455
    processing_execution_id: "arn:aws:states:us-east-1:ACCOUNT:express:agentmail-ai-pipeline:exec123:..."
    
    feature_text_extraction_status:    "completed"
    feature_text_extraction_time_ms:   23
    feature_text_extraction_method:    "quotequail"
    
    feature_embedding_status:          "completed"
    feature_embedding_time_ms:         320
    feature_embedding_dimensions:      512
    
    feature_categorization_status:     "completed"
    feature_categorization_time_ms:    890
    feature_categorization_model:      "haiku"
    feature_categorization_labels:     ["support", "billing"]
    
    feature_extraction_status:         "completed"
    feature_extraction_time_ms:        1200
    feature_extraction_model:          "sonnet"
    feature_extraction_fields:         4

    extracted_text:   "Hi, I have a question about my order..."
    extracted_html:   "<p>Hi, I have a question about my order...</p>"
    labels:           ["support", "billing"]
    urgency:          "medium"
    extracted_data:   { "order_id": "ORD-98765", ... }
```

### Status Update Lambda

```python
def update_processing_status(event: dict) -> dict:
    """Update message record with all processing results."""
    message_id = event["messageId"]
    inbox_id = event["inboxId"]
    org_id = event["orgId"]
    
    text_result = event.get("textExtractionResult", {})
    parallel_results = event.get("parallelResults", [{}] * 3)
    
    # Unpack parallel results (order matches Parallel branches)
    embedding_result = parallel_results[0] if len(parallel_results) > 0 else {}
    categorization_result = parallel_results[1] if len(parallel_results) > 1 else {}
    extraction_result = parallel_results[2] if len(parallel_results) > 2 else {}
    
    # Determine overall status
    statuses = [
        text_result.get("extraction_method", "none") != "failed",
        embedding_result.get("embeddingResult", {}).get("status") != "failed",
        categorization_result.get("categorizationResult", {}).get("status") != "failed",
        extraction_result.get("extractionResult", {}).get("status") != "failed",
    ]
    
    if all(statuses):
        overall_status = "completed"
    elif any(statuses):
        overall_status = "partial"
    else:
        overall_status = "failed"
    
    # Calculate total processing time
    started_at = event.get("processingStartedAt", "")
    processing_time_ms = int(
        (time.time() - _parse_iso(started_at).timestamp()) * 1000
    ) if started_at else 0
    
    # Build DynamoDB update expression
    update_expression = """
        SET processing_status = :status,
            processing_completed_at = :completed_at,
            processing_time_ms = :total_time,
            extracted_text = :extracted_text,
            extracted_html = :extracted_html,
            feature_text_extraction_status = :te_status,
            feature_text_extraction_time_ms = :te_time,
            feature_embedding_status = :emb_status,
            feature_categorization_status = :cat_status,
            feature_extraction_status = :ext_status
    """
    
    now = datetime.utcnow().isoformat() + "Z"
    
    expression_values = {
        ":status": overall_status,
        ":completed_at": now,
        ":total_time": processing_time_ms,
        ":extracted_text": text_result.get("extracted_text", ""),
        ":extracted_html": text_result.get("extracted_html", ""),
        ":te_status": "completed" if text_result.get("extraction_method") != "failed" else "failed",
        ":te_time": text_result.get("processing_time_ms", 0),
        ":emb_status": embedding_result.get("embeddingResult", {}).get("status", "skipped"),
        ":cat_status": categorization_result.get("categorizationResult", {}).get("status", "skipped"),
        ":ext_status": extraction_result.get("extractionResult", {}).get("status", "skipped"),
    }
    
    # Add categorization labels if available
    cat_result = categorization_result.get("categorizationResult", {}).get("result", {})
    if cat_result:
        labels = cat_result.get("labels") or ([cat_result["label"]] if "label" in cat_result else [])
        if labels:
            update_expression += ", labels = :labels"
            expression_values[":labels"] = labels
        
        urgency = cat_result.get("urgency")
        if urgency:
            update_expression += ", urgency = :urgency"
            expression_values[":urgency"] = urgency
    
    # Add extracted data if available
    ext_result = extraction_result.get("extractionResult", {})
    extracted_data = ext_result.get("extracted_data")
    if extracted_data:
        update_expression += ", extracted_data = :ext_data"
        expression_values[":ext_data"] = extracted_data
    
    table.update_item(
        Key={"PK": f"INBOX#{inbox_id}", "SK": f"MSG#{message_id}"},
        UpdateExpression=update_expression,
        ExpressionAttributeValues=expression_values,
    )
    
    return {
        "processingStatus": overall_status,
        "processingTimeMs": processing_time_ms,
        "features": {
            "textExtraction": {"status": expression_values[":te_status"]},
            "embedding": {"status": expression_values[":emb_status"]},
            "categorization": {"status": expression_values[":cat_status"]},
            "extraction": {"status": expression_values[":ext_status"]},
        },
    }
```

---

## Queue Architecture

SQS queues buffer messages between event sources and the Step Functions pipeline, providing backpressure when Bedrock rate limits are hit.

```
EventBridge Rule (message.received)
    │
    ▼
SQS: agentmail-ai-processing-queue
    │
    │  Configuration:
    │    VisibilityTimeout: 300 (5 min, matches Step Functions Express max)
    │    MessageRetentionPeriod: 345600 (4 days)
    │    MaxReceiveCount: 3 (before DLQ)
    │    RedrivePolicy → agentmail-ai-processing-dlq
    │
    ▼
Lambda: agentmail-ai-pipeline-trigger
    │
    │  Batch size: 1 (one message per Step Functions execution)
    │  Reserved concurrency: 50 (limits parallel executions)
    │  
    │  Calls: stepfunctions.start_sync_execution()
    │
    ▼
Step Functions Express Workflow
```

### Lambda Trigger

```python
import json
import os
import boto3

sfn = boto3.client("stepfunctions")
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]


def handler(event, context):
    """Trigger Step Functions execution for each SQS message."""
    for record in event["Records"]:
        message = json.loads(record["body"])
        
        # Start synchronous execution
        response = sfn.start_sync_execution(
            stateMachineArn=STATE_MACHINE_ARN,
            input=json.dumps(message),
            name=f"ai-{message['messageId']}-{int(time.time())}",
        )
        
        if response["status"] == "FAILED":
            error = response.get("error", "Unknown")
            cause = response.get("cause", "")
            print(f"Pipeline failed for {message['messageId']}: {error} - {cause}")
            # Don't raise -- let SQS handle the retry via visibility timeout
            raise Exception(f"Pipeline failed: {error}")
        
        print(f"Pipeline completed for {message['messageId']}: {response['status']}")
```

### Concurrency Control

The Lambda trigger has reserved concurrency of 50. This means at most 50 Step Functions executions run simultaneously, which limits:
- Bedrock API calls to ~50 concurrent requests (within most model rate limits)
- OpenSearch indexing to ~50 concurrent bulk operations
- DynamoDB writes to manageable throughput

If the SQS queue depth exceeds the Lambda's processing rate, messages queue up and are processed in order. This natural backpressure prevents Bedrock throttling from causing cascading failures.

---

## Dead Letter Handling

### DLQ Per Queue

```
agentmail-ai-processing-dlq
    │
    │  Messages land here after 3 failed processing attempts
    │  MessageRetentionPeriod: 1209600 (14 days)
    │
    ▼
Lambda: agentmail-ai-dlq-processor (CloudWatch Events, rate: 5 min)
    │
    │  1. Read messages from DLQ
    │  2. Log failure details to CloudWatch
    │  3. Update message record: processing_status = "failed"
    │  4. Increment CloudWatch metric: AIProcessingDLQDepth
    │  5. If depth > 100: trigger P2 alarm
    │  6. Archive to S3: s3://agentmail-ai-dlq-archive/{date}/{messageId}.json
    │
    ▼
CloudWatch Alarm: agentmail-ai-dlq-depth
    Threshold: > 100 messages for 5 minutes
    Action: SNS → PagerDuty (P2)
```

### Per-Step Error Monitoring

```json
{
  "Metrics": [
    {
      "MetricName": "AITextExtractionErrors",
      "Namespace": "AgentMail/AI",
      "Dimensions": [{ "Name": "Step", "Value": "TextExtraction" }]
    },
    {
      "MetricName": "AIEmbeddingErrors",
      "Namespace": "AgentMail/AI",
      "Dimensions": [{ "Name": "Step", "Value": "Embedding" }]
    },
    {
      "MetricName": "AICategorizationErrors",
      "Namespace": "AgentMail/AI",
      "Dimensions": [{ "Name": "Step", "Value": "Categorization" }]
    },
    {
      "MetricName": "AIExtractionErrors",
      "Namespace": "AgentMail/AI",
      "Dimensions": [{ "Name": "Step", "Value": "DataExtraction" }]
    },
    {
      "MetricName": "AIProcessingLatency",
      "Namespace": "AgentMail/AI",
      "Unit": "Milliseconds"
    }
  ],
  "Alarms": [
    {
      "AlarmName": "agentmail-ai-dlq-depth",
      "MetricName": "ApproximateNumberOfMessagesVisible",
      "Namespace": "AWS/SQS",
      "Dimensions": [{ "Name": "QueueName", "Value": "agentmail-ai-processing-dlq" }],
      "Threshold": 100,
      "ComparisonOperator": "GreaterThanThreshold",
      "EvaluationPeriods": 1,
      "Period": 300
    },
    {
      "AlarmName": "agentmail-ai-processing-latency-p99",
      "MetricName": "AIProcessingLatency",
      "Namespace": "AgentMail/AI",
      "ExtendedStatistic": "p99",
      "Threshold": 10000,
      "ComparisonOperator": "GreaterThanThreshold",
      "EvaluationPeriods": 3,
      "Period": 300
    }
  ]
}
```

---

## Cost Optimization

### Model Routing

See [Categorization - Model Tiering](./categorization.md) and [Data Extraction - Model Selection](./data-extraction.md). Smart routing sends 60-70% of emails to Haiku, saving 60% on Bedrock costs.

### Batch Inference

For backfill operations (e.g., re-categorizing all emails after a label taxonomy change), Bedrock batch inference provides 50% discount with 24-hour turnaround. The pipeline detects batch mode via a flag and routes to S3-based batch instead of real-time InvokeModel.

### Prompt Caching

System prompts (categorization instructions, extraction schema definitions) are marked with `cache_control: ephemeral`. For inboxes processing >100 emails per 5 minutes, this saves ~30% on system prompt tokens.

### Per-Tenant Usage Limits

Organizations can set monthly limits on AI processing to control costs:

```json
{
  "orgId": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W",
  "limits": {
    "categorization_monthly": 100000,
    "extraction_monthly": 50000,
    "search_queries_monthly": 10000
  }
}
```

When a limit is hit, the feature is disabled for the remainder of the billing period. The API returns `429 Too Many Requests` with a `X-RateLimit-Reset` header.

---

## Complete Cost Breakdown

### Startup Tier (100K messages/day)

| Component | Monthly Cost |
|-----------|-------------|
| **Step Functions Express** (100K/day x 8 transitions) | $6 |
| **Lambda compute** (pipeline trigger + 6 functions) | $45 |
| **Text Extraction** (Lambda only, no LLM) | Included in Lambda |
| **Embeddings** (Titan V2, 50M tokens/mo) | $30 |
| **OpenSearch Serverless** (2 OCU minimum) | $350 |
| **Categorization - Haiku** (65% of 100K/day) | $585 |
| **Categorization - Sonnet** (35% of 100K/day) | $315 |
| **Data Extraction - Haiku** (50% of 100K/day) | $150 |
| **Data Extraction - Sonnet** (50% of 100K/day) | $450 |
| **SQS queues** | $5 |
| **DynamoDB writes** (processing status) | $20 |
| **Total** | **~$1,956/mo** |

### Growth Tier (1M messages/day)

| Component | Monthly Cost |
|-----------|-------------|
| **Step Functions Express** | $60 |
| **Lambda compute** | $450 |
| **Embeddings** (Titan V2) | $300 |
| **OpenSearch Serverless** (4 OCU) | $700 |
| **Categorization** (Haiku 65% + Sonnet 35%) | $9,000 |
| **Data Extraction** (Haiku 50% + Sonnet 50%) | $9,000 |
| **SQS + DynamoDB** | $250 |
| **Total** | **~$19,760/mo** |

### Full Scale Tier (10M messages/day)

| Component | Monthly Cost |
|-----------|-------------|
| **Step Functions Express** | $600 |
| **Lambda compute** | $4,500 |
| **Embeddings** (Titan V2) | $3,000 |
| **OpenSearch Serverless** (8 OCU) | $1,400 |
| **Categorization** (Haiku 65% + Sonnet 35%) | $90,000 |
| **Data Extraction** (Haiku 50% + Sonnet 50%) | $90,000 |
| **SQS + DynamoDB** | $2,500 |
| **Total** | **~$192,000/mo** |

### Cost Per Message

| Scale | Total Cost | Messages/Month | Cost/Message |
|-------|-----------|----------------|--------------|
| Startup | $1,956 | 3M | $0.00065 |
| Growth | $19,760 | 30M | $0.00066 |
| Full Scale | $192,000 | 300M | $0.00064 |

Cost per message is remarkably flat across scales because Bedrock pricing is per-token with no volume discounts. The fixed costs (OpenSearch, Step Functions) become negligible at scale. Bedrock inference dominates at every tier.

### Where the Money Goes (Full Scale)

```
Categorization (Bedrock)  ████████████████████████████  47%
Data Extraction (Bedrock) ████████████████████████████  47%
Lambda Compute            █                              2%
Embeddings (Titan V2)     █                              2%
OpenSearch Serverless      ░                              1%
Step Functions            ░                              <1%
SQS + DynamoDB            ░                              1%
```

Bedrock inference is 94% of the total cost at full scale. The most impactful optimization is model routing: every email routed from Sonnet to Haiku saves ~10x on that email's processing cost.
