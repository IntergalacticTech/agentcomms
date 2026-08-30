# Structured Data Extraction

Structured data extraction transforms unstructured email content into customer-defined JSON objects. An e-commerce inbox can extract `order_id`, `total_amount`, and `items[]` from order confirmation emails. A recruiting inbox can extract `candidate_name`, `position`, `years_experience`, and `skills[]` from application emails. Customers define JSON schemas per inbox via the API, and Bedrock Claude processes each email against the schema using tool_use/structured output mode for guaranteed valid JSON.

---

## Customer-Defined JSON Schemas

Customers define extraction schemas per inbox via the API. Each schema specifies the fields to extract, their types, and whether they are required.

### API: Create/Update Extraction Schema

```
POST /v1/inboxes/{inboxId}/extraction-schema
Content-Type: application/json

{
  "name": "Order Extraction",
  "description": "Extract order details from e-commerce emails",
  "schema": {
    "type": "object",
    "properties": {
      "order_id": {
        "type": "string",
        "description": "The order or confirmation number"
      },
      "total_amount": {
        "type": "number",
        "description": "Total order amount in dollars"
      },
      "currency": {
        "type": "string",
        "description": "Currency code (e.g., USD, EUR)",
        "default": "USD"
      },
      "order_date": {
        "type": "string",
        "description": "Date the order was placed (ISO 8601 format)"
      },
      "customer_name": {
        "type": "string",
        "description": "Customer's full name"
      },
      "shipping_address": {
        "type": "object",
        "description": "Shipping address",
        "properties": {
          "street": { "type": "string" },
          "city": { "type": "string" },
          "state": { "type": "string" },
          "zip": { "type": "string" },
          "country": { "type": "string", "default": "US" }
        }
      },
      "items": {
        "type": "array",
        "description": "List of items in the order",
        "items": {
          "type": "object",
          "properties": {
            "name": { "type": "string", "description": "Product name" },
            "quantity": { "type": "integer", "description": "Quantity ordered" },
            "unit_price": { "type": "number", "description": "Price per unit" },
            "sku": { "type": "string", "description": "Product SKU if available" }
          },
          "required": ["name"]
        }
      },
      "tracking_number": {
        "type": "string",
        "description": "Shipping tracking number if available"
      }
    },
    "required": ["order_id"]
  }
}
```

### Response

```json
{
  "id": "exs_01JRWXA1B2CDEF3G4H5J6K7L8M",
  "inboxId": "inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y",
  "name": "Order Extraction",
  "schema": { "...as submitted..." },
  "fieldCount": 8,
  "status": "active",
  "createdAt": "2026-04-10T12:00:00.000Z"
}
```

### DynamoDB Storage

```
Entity: ExtractionSchema
  PK: INBOX#{inboxId}
  SK: CONFIG#extraction

  Attributes:
    inboxId:     "inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"
    orgId:       "org_01JRQ4F8M2NXKB6P3C7D9E0H5W"
    schemaId:    "exs_01JRWXA1B2CDEF3G4H5J6K7L8M"
    name:        "Order Extraction"
    description: "Extract order details from e-commerce emails"
    schema:      { ... JSON Schema ... }
    fieldCount:  8
    status:      "active"
    createdAt:   "2026-04-10T12:00:00.000Z"
    updatedAt:   "2026-04-10T12:00:00.000Z"
```

---

## Prompt Construction

The extraction prompt combines a system prompt (instructions + schema) with the email content. We use Bedrock Claude's `tool_use` mode to guarantee structured JSON output.

### System Prompt

```
You are a structured data extraction system. Extract information from the email below according to the provided schema. Be precise and only extract information that is explicitly stated in the email. Do not infer or guess values that are not present.

Rules:
- Extract only information explicitly present in the email
- Use null for fields where the information is not available
- For required fields, make your best effort to extract a value
- Dates should be in ISO 8601 format (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ)
- Numbers should be numeric values, not strings (e.g., 29.99 not "$29.99")
- For arrays, include all matching items found in the email
```

### Tool Definition (for tool_use mode)

The customer's JSON schema is converted into a Bedrock Claude tool definition:

```python
def schema_to_tool(schema: dict, name: str = "extract_data") -> dict:
    """Convert a customer JSON schema into a Bedrock Claude tool definition.
    
    This leverages Claude's tool_use mode to guarantee the response
    is valid JSON conforming to the schema.
    """
    return {
        "name": name,
        "description": "Extract structured data from the email according to the schema.",
        "input_schema": schema,
    }
```

### Complete Bedrock Request

```python
def extract_data(email_text: str, subject: str, from_address: str, 
                 schema: dict, model_id: str) -> dict:
    """Extract structured data from an email using Bedrock Claude.
    
    Uses tool_use mode for guaranteed valid JSON output.
    """
    tool = schema_to_tool(schema)
    
    user_message = f"""Extract data from this email:

From: {from_address}
Subject: {subject}

{email_text}"""
    
    response = bedrock.invoke_model(
        modelId=model_id,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4096,
            "temperature": 0,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": user_message},
            ],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "extract_data"},
        }),
    )
    
    result = json.loads(response["body"].read())
    
    # Extract the tool_use response
    for content_block in result["content"]:
        if content_block["type"] == "tool_use" and content_block["name"] == "extract_data":
            return content_block["input"]
    
    raise ValueError("No tool_use response from model")
```

### Why tool_use Over Free-Form JSON

| Approach | Validity | Parse Success | Schema Conformance |
|----------|----------|---------------|-------------------|
| Free-form "respond with JSON" | ~90% | ~95% (may have markdown wrapping) | ~80% (may add/omit fields) |
| `tool_use` with `tool_choice: any` | ~99% | ~99.5% | ~95% |
| `tool_use` with `tool_choice: {name}` | ~99.9% | ~99.9% | ~99% |

By forcing the model to call a specific tool (`tool_choice: {type: "tool", name: "extract_data"}`), the response is guaranteed to be a valid JSON object conforming to the tool's `input_schema`. The model cannot respond with free text, markdown, or malformed JSON.

---

## Validation Pipeline

Even with tool_use mode, validation is necessary to catch edge cases (wrong types from type coercion, missing required fields that the model set to null).

```python
import jsonschema


def validate_extraction(extracted: dict, schema: dict) -> tuple[dict, list[str]]:
    """Validate extracted data against the JSON schema.
    
    Returns:
        (cleaned_data, list_of_warnings)
    """
    warnings = []
    
    # Step 1: JSON Schema validation
    try:
        jsonschema.validate(instance=extracted, schema=schema)
    except jsonschema.ValidationError as e:
        warnings.append(f"Schema validation error: {e.message}")
        # Don't fail -- try to salvage what we can
    
    # Step 2: Type coercion for common issues
    cleaned = coerce_types(extracted, schema)
    
    # Step 3: Required field check
    required_fields = schema.get("required", [])
    for field in required_fields:
        if field not in cleaned or cleaned[field] is None:
            warnings.append(f"Required field '{field}' is missing or null")
    
    # Step 4: Clean up null values for optional fields
    properties = schema.get("properties", {})
    for key in list(cleaned.keys()):
        if key not in properties:
            # Remove fields not in schema (model hallucinated extra fields)
            del cleaned[key]
            warnings.append(f"Removed unexpected field '{key}'")
    
    return cleaned, warnings


def coerce_types(data: dict, schema: dict) -> dict:
    """Coerce values to match expected types.
    
    Common issues:
    - Model returns "29.99" (string) for a number field
    - Model returns "3" (string) for an integer field
    - Model returns "true" (string) for a boolean field
    """
    properties = schema.get("properties", {})
    coerced = {}
    
    for key, value in data.items():
        if key not in properties:
            coerced[key] = value
            continue
        
        expected_type = properties[key].get("type")
        
        if value is None:
            coerced[key] = None
            continue
        
        if expected_type == "number" and isinstance(value, str):
            # "$29.99" -> 29.99
            cleaned = value.replace("$", "").replace(",", "").replace("€", "").replace("£", "").strip()
            try:
                coerced[key] = float(cleaned)
            except ValueError:
                coerced[key] = value
        elif expected_type == "integer" and isinstance(value, str):
            try:
                coerced[key] = int(value.replace(",", "").strip())
            except ValueError:
                coerced[key] = value
        elif expected_type == "integer" and isinstance(value, float):
            coerced[key] = int(value)
        elif expected_type == "boolean" and isinstance(value, str):
            coerced[key] = value.lower() in ("true", "yes", "1")
        elif expected_type == "array" and isinstance(value, list):
            # Recursively coerce array items
            item_schema = properties[key].get("items", {})
            if item_schema.get("type") == "object":
                coerced[key] = [coerce_types(item, item_schema) for item in value if isinstance(item, dict)]
            else:
                coerced[key] = value
        elif expected_type == "object" and isinstance(value, dict):
            # Recursively coerce nested objects
            coerced[key] = coerce_types(value, properties[key])
        else:
            coerced[key] = value
    
    return coerced
```

### Retry Logic

```python
def extract_with_retry(email_text: str, subject: str, from_address: str,
                       schema: dict, model_id: str) -> dict:
    """Extract data with validation and retry.
    
    Attempt 1: Standard extraction
    Attempt 2: Stricter prompt with explicit field requirements
    Fallback: Return partial data with validation warnings
    """
    # Attempt 1
    try:
        extracted = extract_data(email_text, subject, from_address, schema, model_id)
        cleaned, warnings = validate_extraction(extracted, schema)
        
        # If required fields are missing, retry
        required = schema.get("required", [])
        missing_required = [f for f in required if f not in cleaned or cleaned[f] is None]
        
        if not missing_required:
            return {
                "extracted_data": cleaned,
                "warnings": warnings,
                "attempt": 1,
                "status": "complete" if not warnings else "partial",
            }
    except Exception as e:
        print(f"Extraction attempt 1 failed: {e}")
        cleaned = {}
        missing_required = schema.get("required", [])
    
    # Attempt 2: Stricter prompt
    try:
        strict_prompt_suffix = (
            f"\n\nIMPORTANT: You MUST extract values for these required fields: "
            f"{json.dumps(missing_required)}. "
            f"Look carefully in the email for any mention of these fields. "
            f"If truly not present, use your best judgment to provide a reasonable value."
        )
        
        extracted = extract_data(
            email_text + strict_prompt_suffix, subject, from_address, schema, model_id
        )
        cleaned, warnings = validate_extraction(extracted, schema)
        
        return {
            "extracted_data": cleaned,
            "warnings": warnings,
            "attempt": 2,
            "status": "complete" if not warnings else "partial",
        }
    except Exception as e:
        print(f"Extraction attempt 2 failed: {e}")
    
    # Fallback: return whatever we have
    return {
        "extracted_data": cleaned,
        "warnings": warnings + ["All extraction attempts produced incomplete results"],
        "attempt": 2,
        "status": "failed",
    }
```

---

## Storage

Extracted data is stored as a `Map` attribute on the DynamoDB message record.

```
Entity: Message (updated after extraction)
  PK: INBOX#{inboxId}
  SK: MSG#{messageId}

  Updated Attributes:
    extracted_data: {
      "order_id": "ORD-98765",
      "total_amount": 149.97,
      "currency": "USD",
      "order_date": "2026-04-10",
      "customer_name": "Jane Smith",
      "shipping_address": {
        "street": "123 Main St",
        "city": "Portland",
        "state": "OR",
        "zip": "97201",
        "country": "US"
      },
      "items": [
        { "name": "Blue Widget", "quantity": 2, "unit_price": 49.99, "sku": "WDG-BLU-001" },
        { "name": "Red Gadget", "quantity": 1, "unit_price": 49.99, "sku": "GDG-RED-002" }
      ],
      "tracking_number": null
    }
    extraction_status:  "complete" | "partial" | "failed"
    extraction_warnings: ["tracking_number not found in email"]
    extraction_model:   "claude-3-5-haiku-20241022"
    extraction_time_ms: 1200
    extracted_at:       "2026-04-10T14:30:03.456Z"
```

### API Access

Customers access extracted data via the message API:

```
GET /v1/inboxes/{inboxId}/messages/{messageId}

Response includes:
{
  "id": "msg_01JRWX6E7MNKD3P4Q8R2S5T9V1",
  "subject": "Order Confirmation #ORD-98765",
  "from": "orders@shop.example.com",
  "extractedData": {
    "order_id": "ORD-98765",
    "total_amount": 149.97,
    "items": [...]
  },
  "extractionStatus": "complete"
}
```

---

## Model Selection

```python
def select_extraction_model(schema: dict, email_text: str) -> str:
    """Select the cheapest model that can handle this extraction task.
    
    Haiku for simple schemas (<=3 top-level fields, no nesting)
    Sonnet for complex schemas (>3 fields, nested objects, arrays of objects)
    """
    properties = schema.get("properties", {})
    field_count = len(properties)
    
    # Check for nested complexity
    has_nested_objects = any(
        prop.get("type") == "object" and prop.get("properties")
        for prop in properties.values()
    )
    
    has_array_of_objects = any(
        prop.get("type") == "array" and 
        prop.get("items", {}).get("type") == "object"
        for prop in properties.values()
    )
    
    # Complexity assessment
    if field_count <= 3 and not has_nested_objects and not has_array_of_objects:
        return "claude-3-5-haiku-20241022"
    
    if field_count <= 5 and not has_array_of_objects:
        # Medium complexity: Haiku can still handle this
        if len(email_text) < 3000:
            return "claude-3-5-haiku-20241022"
    
    # Complex schema or long email: use Sonnet
    return "claude-sonnet-4-20250514"
```

---

## Cost Analysis

### Per-Email Cost by Complexity

| Schema Complexity | Model | Avg Input Tokens | Avg Output Tokens | Cost/Email |
|-------------------|-------|-----------------|-------------------|------------|
| Simple (1-3 fields) | Haiku | 600 | 100 | ~$0.0001 |
| Medium (4-5 fields) | Haiku | 800 | 200 | ~$0.0019 |
| Complex (6+ fields, nested) | Sonnet | 1000 | 400 | ~$0.009 |
| Very complex (10+ fields, arrays) | Sonnet | 1500 | 800 | ~$0.017 |

### Monthly Cost by Scale

| Scale | Emails/Day | Simple (70%) | Complex (30%) | Total/Month |
|-------|-----------|-------------|---------------|-------------|
| Startup | 100K | 70K x $0.0011 | 30K x $0.009 | ~$270/mo |
| Growth | 1M | 700K x $0.0011 | 300K x $0.009 | **~$10,800/mo** |
| Full Scale | 10M | 7M x $0.0011 | 3M x $0.009 | **~$108,000/mo** |

### Cost Per Extracted Field

At the median schema (5 fields), extraction costs ~$0.003/email or ~$0.0006/field. This is competitive with purpose-built extraction APIs (AWS Textract at $0.015/page, Google Document AI at $0.01/page) and significantly more flexible since customers define their own schemas.

### Cost Reduction Strategies

| Strategy | Savings | Trade-off |
|----------|---------|-----------|
| Model routing (Haiku for simple) | 60-70% | Slightly lower accuracy on edge cases |
| Prompt caching (system prompt) | ~30% on system tokens | Requires >100 emails/5min per inbox |
| Batch inference (backfill) | 50% | 24-hour latency (not real-time) |
| Result caching (identical emails) | 5-15% | Stale results if schema changes |
| Skip extraction for short emails (<50 chars) | 5-10% | May miss brief but information-rich emails |
