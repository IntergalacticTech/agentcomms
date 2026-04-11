# Email Categorization

Email categorization assigns customer-defined labels to incoming messages using Bedrock Claude models. A support inbox might categorize emails as "billing," "technical," "account," or "general." An e-commerce inbox might tag emails with "order-inquiry," "return-request," "shipping-question," and "complaint." The categorization system is fully configurable per inbox: customers define their own label taxonomies and prompt templates via the API, and AgentMail applies them to every incoming message.

---

## Model Tiering

Not every categorization task requires the same model. Simple 2-5 category classification works with the cheapest model. Complex multi-label classification with sentiment, urgency, and intent requires a more capable model. We route to the cheapest model that satisfies the task.

### Tier Selection

| Tier | Model | Cost/1K input tokens | Cost/1K output tokens | Use Case |
|------|-------|---------------------|----------------------|----------|
| **Haiku** | claude-3-5-haiku-20241022 | $0.001 | $0.005 | Simple categorization: 2-5 mutually exclusive labels, short emails |
| **Sonnet** | claude-sonnet-4-20250514 | $0.003 | $0.015 | Complex categorization: >5 labels, multi-label, sentiment + urgency + intent |

### Estimated Cost Per Email

| Model | Avg Input Tokens | Avg Output Tokens | Cost/Email |
|-------|-----------------|-------------------|------------|
| Haiku | 800 (prompt + email) | 50 (labels JSON) | ~$0.0003 |
| Sonnet | 800 (prompt + email) | 100 (labels + sentiment JSON) | ~$0.003 |

### Model Routing Logic

```python
def select_model(config: dict, email_text: str) -> str:
    """Select the cheapest model that can handle this categorization task.
    
    Routes to Haiku (60-70% of emails) when:
    - Number of categories <= 5
    - Single-label classification (not multi-label)
    - Email length < 2000 characters
    - No additional extraction (sentiment, urgency, intent)
    
    Routes to Sonnet (30-40% of emails) when:
    - Number of categories > 5
    - Multi-label classification
    - Email length >= 2000 characters (needs better comprehension)
    - Additional extraction requested (sentiment, urgency, intent, custom fields)
    """
    labels = config.get("labels", [])
    multi_label = config.get("multi_label", False)
    extract_sentiment = config.get("extract_sentiment", False)
    extract_urgency = config.get("extract_urgency", False)
    extract_intent = config.get("extract_intent", False)
    
    # Complexity score
    complexity = 0
    
    if len(labels) > 5:
        complexity += 2
    
    if multi_label:
        complexity += 2
    
    if len(email_text) > 2000:
        complexity += 1
    
    if extract_sentiment or extract_urgency or extract_intent:
        complexity += 2
    
    if complexity >= 3:
        return "claude-sonnet-4-20250514"
    else:
        return "claude-3-5-haiku-20241022"
```

---

## Prompt Template System

Each inbox has a categorization configuration stored in DynamoDB. The configuration includes the label taxonomy, prompt template, and model routing preferences.

### DynamoDB Configuration Record

```
Entity: InboxCategorizationConfig
  PK: INBOX#{inboxId}
  SK: CONFIG#categorization

  Attributes:
    inboxId:           "inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"
    orgId:             "org_01JRQ4F8M2NXKB6P3C7D9E0H5W"
    enabled:           true
    labels:            ["billing", "technical", "account", "shipping", "general"]
    multi_label:        false
    extract_sentiment:  false
    extract_urgency:    true
    extract_intent:     false
    prompt_template:    "... (see below)"
    model_override:     null  (null = auto-select; "haiku" or "sonnet" to force)
    created_at:        "2026-04-01T00:00:00Z"
    updated_at:        "2026-04-10T12:00:00Z"
```

### Prompt Template Variables

Templates support these variables, resolved at runtime:

| Variable | Description | Example |
|----------|-------------|---------|
| `{{subject}}` | Email subject line | "Order #12345 question" |
| `{{extracted_text}}` | Clean email body (after text extraction) | "Hi, I have a question about..." |
| `{{from}}` | Sender email address | "customer@example.com" |
| `{{to}}` | Recipient email address | "support@company.com" |
| `{{labels}}` | JSON array of allowed labels | `["billing", "technical", "general"]` |
| `{{date}}` | Email received date | "2026-04-10T14:30:00Z" |
| `{{has_attachments}}` | Whether email has attachments | "true" |
| `{{thread_length}}` | Number of messages in the thread | "3" |
| `{{inbox_name}}` | Name of the inbox | "Customer Support" |

### Default Prompt Template

```
You are an email categorization system for {{inbox_name}}. Classify the following email into exactly one of these categories: {{labels}}.

Rules:
- Respond with ONLY a JSON object, no other text.
- The "label" field must be exactly one of the provided categories.
- If the email does not clearly fit any category, use "general".
{{#extract_urgency}}
- Also classify urgency as "low", "medium", or "high".
{{/extract_urgency}}

Email:
From: {{from}}
Subject: {{subject}}
Date: {{date}}

{{extracted_text}}

Respond with JSON:
```

### Complete Prompt Examples

**Simple categorization (Haiku):**

```
System: You are an email categorization system for Customer Support. Classify the following email into exactly one of these categories: ["billing", "technical", "account", "shipping", "general"].

Rules:
- Respond with ONLY a JSON object, no other text.
- The "label" field must be exactly one of the provided categories.
- If the email does not clearly fit any category, use "general".

Email:
From: jane@example.com
Subject: Can't reset my password
Date: 2026-04-10T14:30:00Z

Hi, I've been trying to reset my password for the last hour but the reset email never arrives. I've checked my spam folder. Can someone help?

Respond with JSON:
```

Expected response:
```json
{ "label": "account" }
```

**Complex multi-label with urgency (Sonnet):**

```
System: You are an email categorization system for E-Commerce Support. Classify the following email. You may assign MULTIPLE labels from this list: ["order-inquiry", "return-request", "shipping-question", "product-question", "complaint", "billing", "account", "compliment", "general"].

Rules:
- Respond with ONLY a JSON object, no other text.
- The "labels" field must be an array of one or more of the provided categories.
- Classify urgency as "low", "medium", or "high".
- Classify sentiment as "positive", "neutral", or "negative".
- If the email does not clearly fit any category, use ["general"].

Email:
From: frustrated_customer@example.com
Subject: URGENT - Wrong item shipped AND charged twice!!
Date: 2026-04-10T14:30:00Z

I ordered a blue widget (order #98765) but received a red gadget instead. To make matters worse, I was charged twice for this order! I need this resolved immediately as this was a gift for my daughter's birthday tomorrow. I've been a loyal customer for 5 years and I'm very disappointed.

Respond with JSON:
```

Expected response:
```json
{
  "labels": ["complaint", "shipping-question", "billing"],
  "urgency": "high",
  "sentiment": "negative"
}
```

---

## Processing Pipeline

```
SQS: agentmail-categorization-queue
    │
    │  Batch size: 1 (one email per invocation for isolation)
    │  Visibility timeout: 120s
    │
    ▼
Lambda: agentmail-categorizer
    │
    │  1. Load inbox categorization config from DynamoDB (cached)
    │  2. Check result cache (hash of template + text)
    │  3. If cache miss:
    │     a. Select model (Haiku or Sonnet)
    │     b. Render prompt template with email variables
    │     c. Call Bedrock InvokeModel
    │     d. Parse and validate JSON response
    │     e. On invalid: retry once with stricter prompt
    │     f. On second failure: assign "uncategorized"
    │  4. Write result to DynamoDB message record
    │  5. Write to result cache
    │
    ▼
DynamoDB: Update message record with categorization results
```

### Categorizer Lambda

```python
import json
import hashlib
import os
import time
from typing import Any

import boto3

bedrock = boto3.client("bedrock-runtime")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])

# In-memory cache for inbox configs (refreshed every 5 minutes)
_config_cache = {}
_config_cache_ttl = 300


def handler(event: dict, context: Any) -> dict:
    """Categorize a single email using Bedrock Claude."""
    for record in event["Records"]:
        message = json.loads(record["body"])
        
        message_id = message["messageId"]
        inbox_id = message["inboxId"]
        org_id = message["orgId"]
        
        # Step 1: Load inbox categorization config
        config = get_categorization_config(inbox_id)
        if not config or not config.get("enabled"):
            return {"status": "skipped", "reason": "categorization not enabled"}
        
        extracted_text = message.get("extracted_text", "")
        subject = message.get("subject", "")
        
        # Step 2: Check result cache
        cache_key = compute_cache_key(config, extracted_text, subject)
        cached_result = get_cached_result(cache_key)
        if cached_result:
            update_message_categorization(message_id, org_id, inbox_id, cached_result, "cache_hit")
            return {"status": "cached", "result": cached_result}
        
        # Step 3: Select model
        model_id = config.get("model_override")
        if not model_id:
            model_id = select_model(config, extracted_text)
        elif model_id == "haiku":
            model_id = "claude-3-5-haiku-20241022"
        elif model_id == "sonnet":
            model_id = "claude-sonnet-4-20250514"
        
        # Step 4: Render prompt
        prompt = render_prompt(config, message)
        
        # Step 5: Call Bedrock
        result = None
        for attempt in range(2):
            try:
                response = bedrock.invoke_model(
                    modelId=model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps({
                        "anthropic_version": "bedrock-2023-05-31",
                        "max_tokens": 200,
                        "temperature": 0,
                        "system": "You are a precise email categorization system. Respond with only valid JSON.",
                        "messages": [
                            {"role": "user", "content": prompt},
                        ],
                    }),
                )
                
                response_body = json.loads(response["body"].read())
                response_text = response_body["content"][0]["text"].strip()
                
                # Step 6: Parse and validate
                result = validate_categorization_response(response_text, config)
                
                if result is not None:
                    break  # Valid result
                
                # Invalid result -- retry with stricter prompt
                if attempt == 0:
                    prompt = render_strict_prompt(config, message, response_text)
                    
            except Exception as e:
                print(f"Bedrock error (attempt {attempt + 1}): {e}")
                if attempt == 0:
                    time.sleep(1)  # Brief backoff before retry
        
        # Step 7: Fallback to "uncategorized"
        if result is None:
            if config.get("multi_label"):
                result = {"labels": ["uncategorized"]}
            else:
                result = {"label": "uncategorized"}
        
        # Step 8: Write results
        update_message_categorization(message_id, org_id, inbox_id, result, model_id)
        cache_result(cache_key, result)
        
        # Step 9: Track usage
        track_usage(org_id, model_id)
        
        return {"status": "categorized", "result": result, "model": model_id}


def validate_categorization_response(response_text: str, config: dict) -> dict | None:
    """Validate that the model's response matches the expected schema.
    
    Returns the parsed result if valid, None if invalid.
    """
    try:
        # Parse JSON (handle markdown code blocks)
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        
        result = json.loads(text)
    except json.JSONDecodeError:
        return None
    
    allowed_labels = set(config.get("labels", []))
    
    if config.get("multi_label"):
        # Multi-label: expect {"labels": [...]}
        labels = result.get("labels")
        if not isinstance(labels, list) or not labels:
            return None
        
        # Validate each label
        valid_labels = [l for l in labels if l in allowed_labels]
        if not valid_labels:
            return None
        
        result["labels"] = valid_labels
    else:
        # Single-label: expect {"label": "..."}
        label = result.get("label")
        if not isinstance(label, str):
            return None
        
        if label not in allowed_labels:
            # Try case-insensitive match
            label_lower = label.lower()
            for allowed in allowed_labels:
                if allowed.lower() == label_lower:
                    result["label"] = allowed
                    break
            else:
                return None
    
    # Validate optional fields
    if config.get("extract_urgency"):
        urgency = result.get("urgency", "medium")
        if urgency not in ("low", "medium", "high"):
            result["urgency"] = "medium"
    
    if config.get("extract_sentiment"):
        sentiment = result.get("sentiment", "neutral")
        if sentiment not in ("positive", "neutral", "negative"):
            result["sentiment"] = "neutral"
    
    return result


def render_prompt(config: dict, message: dict) -> str:
    """Render the prompt template with message variables."""
    template = config.get("prompt_template", DEFAULT_PROMPT_TEMPLATE)
    
    variables = {
        "{{subject}}": message.get("subject", ""),
        "{{extracted_text}}": message.get("extracted_text", ""),
        "{{from}}": message.get("from", ""),
        "{{to}}": message.get("to", ""),
        "{{labels}}": json.dumps(config.get("labels", [])),
        "{{date}}": message.get("receivedAt", ""),
        "{{has_attachments}}": str(message.get("hasAttachments", False)).lower(),
        "{{thread_length}}": str(message.get("threadLength", 1)),
        "{{inbox_name}}": config.get("inbox_name", "Inbox"),
    }
    
    prompt = template
    for var, value in variables.items():
        prompt = prompt.replace(var, value)
    
    # Handle conditional blocks
    if config.get("extract_urgency"):
        prompt = prompt.replace("{{#extract_urgency}}", "").replace("{{/extract_urgency}}", "")
    else:
        # Remove urgency block
        import re
        prompt = re.sub(r"{{#extract_urgency}}.*?{{/extract_urgency}}", "", prompt, flags=re.DOTALL)
    
    return prompt


def render_strict_prompt(config: dict, message: dict, invalid_response: str) -> str:
    """Render a stricter prompt after an invalid first response.
    
    Includes the invalid response and explicit instructions to fix it.
    """
    prompt = render_prompt(config, message)
    prompt += f"\n\nYour previous response was invalid:\n{invalid_response}\n\n"
    prompt += f"You MUST respond with valid JSON. The 'label' field MUST be exactly one of: {json.dumps(config.get('labels', []))}. "
    prompt += "Do not include any text outside the JSON object."
    return prompt
```

---

## Caching

### Result Cache

Identical emails (e.g., newsletters, automated notifications) produce identical categorizations. We cache results to avoid redundant Bedrock calls.

```python
def compute_cache_key(config: dict, extracted_text: str, subject: str) -> str:
    """Compute a deterministic cache key from the categorization inputs.
    
    The key is a hash of:
    - The prompt template (identifies the categorization schema)
    - The email text (identifies the content)
    - The subject line
    """
    template = config.get("prompt_template", "")
    labels = json.dumps(sorted(config.get("labels", [])))
    
    content = f"{template}:{labels}:{subject}:{extracted_text}"
    return f"cat_cache:{hashlib.sha256(content.encode()).hexdigest()}"


def get_cached_result(cache_key: str) -> dict | None:
    """Check DynamoDB for a cached categorization result."""
    try:
        response = table.get_item(
            Key={"PK": cache_key, "SK": "RESULT"},
            ProjectionExpression="result_json",
        )
        if "Item" in response:
            return json.loads(response["Item"]["result_json"])
    except Exception:
        pass
    return None


def cache_result(cache_key: str, result: dict) -> None:
    """Cache a categorization result in DynamoDB with 24-hour TTL."""
    try:
        table.put_item(Item={
            "PK": cache_key,
            "SK": "RESULT",
            "result_json": json.dumps(result),
            "ttl": int(time.time()) + 86400,  # 24-hour TTL
        })
    except Exception as e:
        print(f"Cache write failed: {e}")
```

### Expected Cache Hit Rates

| Email Type | Hit Rate | Reason |
|-----------|----------|--------|
| Newsletters | 80-95% | Identical content across recipients |
| Automated notifications | 50-70% | Similar structure, different details |
| Transactional emails | 20-40% | Template-based with variable data |
| Personal emails | 0-5% | Unique content |
| **Weighted average** | **5-15%** | Most inboxes receive primarily unique emails |

---

## Cost Optimization

### 1. Bedrock Prompt Caching

Bedrock supports prompt caching for Claude models. The system prompt (which includes the label taxonomy and instructions) is the same for all emails in a given inbox. By marking it as cacheable, we save ~30% on the system prompt tokens.

```python
# With prompt caching enabled
body = {
    "anthropic_version": "bedrock-2023-05-31",
    "max_tokens": 200,
    "temperature": 0,
    "system": [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},  # Cache this block
        }
    ],
    "messages": [
        {"role": "user", "content": user_prompt},
    ],
}
```

**Savings:**
- System prompt: ~300 tokens (shared across all emails for an inbox)
- Cache write: 25% premium on first call
- Cache read: 90% discount on subsequent calls within 5 minutes
- Net savings at 100+ emails/5min per inbox: ~30% on system prompt tokens

### 2. Batch Inference

For non-urgent categorization (e.g., backfill, bulk import), Bedrock batch inference provides a 50% discount:

```python
# Submit batch job
bedrock_batch = boto3.client("bedrock")

response = bedrock_batch.create_model_invocation_job(
    modelId="claude-3-5-haiku-20241022",
    jobName=f"categorize-backfill-{int(time.time())}",
    roleArn="arn:aws:iam::ACCOUNT:role/agentmail-bedrock-batch-role",
    inputDataConfig={
        "s3InputDataConfig": {
            "s3Uri": "s3://agentmail-batch/input/categorize-batch-001.jsonl",
        }
    },
    outputDataConfig={
        "s3OutputDataConfig": {
            "s3Uri": "s3://agentmail-batch/output/",
        }
    },
)
```

Batch pricing: 50% of on-demand. Results delivered within 24 hours.

### 3. Model Routing Savings

| Routing Strategy | Haiku % | Sonnet % | Avg Cost/Email | vs All-Sonnet |
|------------------|---------|----------|----------------|---------------|
| All Sonnet | 0% | 100% | $0.003 | baseline |
| All Haiku | 100% | 0% | $0.0003 | -90% |
| Smart routing | 65% | 35% | $0.0012 | -60% |

Smart routing achieves 60% savings over Sonnet-only with minimal quality loss on simple tasks.

---

## Per-Tenant Usage Tracking

Every Bedrock invocation is tracked per organization for billing and quota enforcement.

```python
def track_usage(org_id: str, model_id: str) -> None:
    """Increment per-org usage counter using atomic DynamoDB update.
    
    Tracks:
    - Total invocations per model per day
    - Used for metering/billing and quota enforcement
    """
    today = time.strftime("%Y-%m-%d", time.gmtime())
    model_short = "haiku" if "haiku" in model_id else "sonnet"
    
    table.update_item(
        Key={
            "PK": f"USAGE#{org_id}",
            "SK": f"CAT#{today}#{model_short}",
        },
        UpdateExpression="ADD invocations :one SET #ttl = :ttl",
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={
            ":one": 1,
            ":ttl": int(time.time()) + (90 * 86400),  # 90-day retention
        },
    )
```

### Quota Enforcement

Organizations can set monthly categorization limits. The Lambda checks usage before invoking Bedrock:

```python
def check_quota(org_id: str) -> bool:
    """Check if the organization has remaining categorization quota."""
    # Get current month's total usage
    month_prefix = time.strftime("%Y-%m", time.gmtime())
    
    response = table.query(
        KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
        ExpressionAttributeValues={
            ":pk": f"USAGE#{org_id}",
            ":prefix": f"CAT#{month_prefix}",
        },
    )
    
    total = sum(item.get("invocations", 0) for item in response.get("Items", []))
    
    # Get org quota
    org = table.get_item(Key={"PK": f"ORG#{org_id}", "SK": "META"})
    quota = org.get("Item", {}).get("categorization_quota", float("inf"))
    
    return total < quota
```
