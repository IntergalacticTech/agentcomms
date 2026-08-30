# AI/ML Features

AgentMail's AI/ML layer transforms raw email into structured, searchable, categorized intelligence. Every inbound message passes through an orchestrated processing pipeline that extracts clean text, generates vector embeddings, categorizes against customer-defined taxonomies, and extracts structured data from unstructured email content. The entire pipeline runs on managed AWS services -- Bedrock for LLM inference, OpenSearch Serverless for vector search, Step Functions for orchestration -- with no self-hosted models, no GPU instances, and no ML ops overhead.

---

## Architecture

```
                              Inbound Message Stored
                                      │
                                      ▼
                             EventBridge Rule
                             (source = "ses-inbound")
                                      │
                                      ▼
                            ┌──────────────────┐
                            │  SQS Buffer Queue │
                            │  (rate limiting)   │
                            └────────┬───────────┘
                                     │
                                     ▼
                     ┌───────────────────────────────┐
                     │   Step Functions Express       │
                     │   AI Processing Workflow        │
                     │                                 │
                     │   ┌─────────────────────────┐   │
                     │   │  1. Text Extraction      │   │
                     │   │     (no LLM, <50ms)      │   │
                     │   └────────────┬────────────┘   │
                     │                │                 │
                     │         ┌──────┴──────┐         │
                     │         │  Parallel    │         │
                     │   ┌─────┤  Branch      ├─────┐  │
                     │   │     └─────────────┘     │  │
                     │   ▼           ▼             ▼  │
                     │ ┌──────┐ ┌──────────┐ ┌──────┐ │
                     │ │Embed │ │Categorize│ │Extract│ │
                     │ │      │ │          │ │      │ │
                     │ │Titan │ │ Haiku/   │ │Haiku/│ │
                     │ │V2    │ │ Sonnet   │ │Sonnet│ │
                     │ │      │ │          │ │      │ │
                     │ │ ▼    │ │  ▼       │ │ ▼    │ │
                     │ │Open  │ │DynamoDB  │ │Dynamo│ │
                     │ │Search│ │(labels)  │ │(data)│ │
                     │ └──────┘ └──────────┘ └──────┘ │
                     │                │                 │
                     │         ┌──────┴──────┐         │
                     │         │ Update       │         │
                     │         │ Processing   │         │
                     │         │ Status       │         │
                     │         └──────┬──────┘         │
                     │                │                 │
                     │         ┌──────┴──────┐         │
                     │         │ Fire Event   │         │
                     │         │ message.     │         │
                     │         │ ai_processed │         │
                     │         └─────────────┘         │
                     └───────────────────────────────┘
                                     │
                                     ▼
                         Kinesis (agentmail-events)
                         → Webhooks / WebSockets
```

---

## Sub-Documents

| Document | Description |
|----------|-------------|
| [Text Extraction](./text-extraction.md) | MIME parsing, quoted reply removal (all major email clients), HTML-to-text conversion, and complete Python extraction pipeline |
| [Semantic Search](./semantic-search.md) | Amazon Titan Embeddings V2, OpenSearch Serverless vector engine, hybrid search (knn + BM25 + filters), index design, query flow, and cost analysis |
| [Categorization](./categorization.md) | Bedrock Claude model tiering (Haiku/Sonnet), prompt template system, response validation, caching, batch inference, and cost optimization |
| [Data Extraction](./data-extraction.md) | Customer-defined JSON schemas, Bedrock Claude structured output, validation pipeline, and storage |
| [Processing Pipeline](./processing-pipeline.md) | Step Functions Express orchestration, error handling, queue architecture, dead letter handling, cost breakdown |

---

## Key Design Decisions

1. **Step Functions Express over Standard.** Express Workflows cost $0.000025 per state transition (vs $0.025 for Standard). At 1M messages/day with ~8 state transitions each, Express costs $200/mo vs $200,000/mo for Standard. Express Workflows are synchronous and limited to 5 minutes, but our pipeline completes in <10 seconds.

2. **Model tiering: cheapest model that works.** Not every email needs Sonnet. Simple categorization (2-5 labels) works with Haiku at $0.0003/email. Complex multi-label categorization and nested data extraction use Sonnet at $0.003/email. A routing function selects the cheapest model that satisfies the customer's configuration. This saves 60-70% on Bedrock costs.

3. **Text extraction without LLMs.** Stripping quoted replies and extracting clean text from MIME is a deterministic parsing problem, not a language understanding problem. Using regex and established libraries (quotequail, html2text) is faster (<50ms vs 1-2s for an LLM), cheaper (zero cost vs $0.0003+ per email), and more reliable (no hallucination, no rate limits).

4. **Shared OpenSearch collection with org_id filter.** OpenSearch Serverless charges a $346/mo minimum per collection (2 OCU). Creating a collection per tenant is prohibitively expensive. A shared collection with a mandatory `org_id` filter on every query provides tenant isolation at a fraction of the cost. At startup, one collection serves all tenants.

5. **SQS buffering before Step Functions.** Bedrock has per-model rate limits (tokens per minute, requests per minute). SQS queues between event sources and Step Functions provide natural backpressure. When Bedrock throttles, Lambda consumers slow down via SQS visibility timeout backoff rather than failing loudly.

6. **Prompt caching for system prompts.** Bedrock supports prompt caching for Claude models, reducing cost by ~30% on the system prompt portion. Since all emails for a given inbox use the same system prompt (categorization taxonomy, extraction schema), the cache hit rate is high.

---

## Feature Availability

Not all features are enabled for every inbox. Customers configure which AI features are active per inbox via the API.

| Feature | Default | Requires Config | Billable |
|---------|---------|-----------------|----------|
| Text Extraction | Enabled (all inboxes) | No | Included |
| Embedding / Search | Enabled (all inboxes) | No | Per search query |
| Categorization | Disabled | Yes (labels + prompt template) | Per message |
| Data Extraction | Disabled | Yes (JSON schema) | Per message |

---

## Cost Summary

| Scale | Text Extract | Embeddings | OpenSearch | Categorization | Data Extraction | Step Functions | Total |
|-------|-------------|------------|-----------|----------------|-----------------|---------------|-------|
| Startup (100K/day) | $45/mo | $60/mo | $692/mo | $720/mo | $270/mo | $6/mo | **~$1,800/mo** |
| Growth (1M/day) | $450/mo | $600/mo | $1,382/mo | $10,800/mo | $10,800/mo | $60/mo | **~$24,000/mo** |
| Full Scale (10M/day) | $2,250/mo | $3,000/mo | $2,765/mo | $50,000/mo | $65,000/mo | $600/mo | **~$124,000/mo** |

Categorization and data extraction dominate costs at scale. These features are only billed when enabled by the customer, and model tiering (Haiku for simple, Sonnet for complex) keeps costs as low as possible.
