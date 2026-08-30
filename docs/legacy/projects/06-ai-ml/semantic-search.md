# Semantic Search

AgentMail's semantic search enables AI agents and developers to find emails by meaning rather than exact keyword match. A query like "invoices from last month" finds messages about billing, payments, and receipts even if they never contain the word "invoice." The system combines vector similarity search (knn), keyword search (BM25), and metadata filters in a single query against Amazon OpenSearch Serverless.

---

## Embedding Model: Amazon Titan Embeddings V2 Text

### Why Titan Over Alternatives

| Factor | Titan V2 | Cohere Embed V3 | OpenAI ada-002 |
|--------|----------|-----------------|----------------|
| **Cost (on-demand)** | $0.00002/1K tokens | $0.0001/1K tokens | $0.0001/1K tokens |
| **Dimensions** | 256, 512, 1024 | 1024 | 1536 |
| **Bedrock native** | Yes (zero config) | Yes | No (external API) |
| **Batch pricing** | $0.00001/1K tokens | $0.00005/1K tokens | N/A |
| **Quality (MTEB avg)** | 0.63 | 0.68 | 0.65 |

Titan V2 is **5x cheaper** than Cohere and OpenAI. The quality gap (0.63 vs 0.68 MTEB) is not material for email search -- emails contain domain-specific vocabulary and metadata that compensate for minor embedding quality differences. Titan is also a native Bedrock model with zero integration overhead: no API keys, no external dependencies, no egress costs.

We use **512 dimensions** as the balance point between quality and cost. 256 dimensions lose too much information for long emails. 1024 dimensions provide marginal quality improvement at 2x the storage and search cost.

### Embedding Configuration

```python
import json
import boto3

bedrock_runtime = boto3.client("bedrock-runtime", region_name="us-east-1")

def generate_embedding(text: str, dimensions: int = 512) -> list[float]:
    """Generate a vector embedding for the given text using Titan V2.
    
    Args:
        text: Input text (max 8192 tokens, ~32K characters)
        dimensions: Output dimensions (256, 512, or 1024)
    
    Returns:
        List of float values representing the embedding vector
    """
    # Truncate to Titan V2's context window (~8192 tokens)
    if len(text) > 30000:
        text = text[:30000]
    
    response = bedrock_runtime.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "inputText": text,
            "dimensions": dimensions,
            "normalize": True,  # L2-normalize for cosine similarity
        }),
    )
    
    result = json.loads(response["body"].read())
    return result["embedding"]
```

### Token Estimation

Average email length: ~500 tokens (~2000 characters). At $0.00002/1K tokens:

| Scale | Emails/Day | Tokens/Day | Embedding Cost/Day | Monthly |
|-------|-----------|------------|-------------------|---------|
| Startup | 100K | 50M | $1.00 | $30 |
| Growth | 1M | 500M | $10.00 | $300 |
| Full Scale | 10M | 5B | $100.00 | $3,000 |

---

## Vector Database: Amazon OpenSearch Serverless

### Why OpenSearch Over Alternatives

| Factor | OpenSearch Serverless | pgvector (Aurora) | Pinecone |
|--------|---------------------|-------------------|----------|
| **Auto-scaling** | Yes (OCU-based) | Manual (instance sizing) | Yes (pod-based) |
| **Billion-scale** | Yes (nmslib/HNSW) | Degraded >10M rows | Yes |
| **Hybrid search** | knn + BM25 + filters in one query | knn only (separate FTS) | knn + metadata filters |
| **AWS native** | Yes (IAM, VPC, CloudWatch) | Yes | No (external dependency) |
| **Minimum cost** | $346/mo (2 OCU) | ~$50/mo (db.t4g.medium) | $70/mo (s1.x1) |
| **Operational overhead** | Zero (serverless) | Medium (connection pools, vacuuming) | Low (managed SaaS) |

**pgvector** is cheaper at small scale but does not scale to billions of vectors without significant operational work (partitioning, index maintenance, connection pooling with Lambda). It also lacks native hybrid search -- you need separate full-text search indexes.

**Pinecone** is a strong product but introduces an external dependency outside AWS. Data must egress to Pinecone's infrastructure, adding latency and cost. IAM integration requires custom auth. For an AWS Marketplace product, keeping everything in AWS reduces operational risk.

**OpenSearch Serverless** provides auto-scaling vector search with hybrid (knn + BM25) in a single query. The $346/mo minimum is the main cost at startup, but it is a fixed cost that does not increase until traffic demands more than 2 OCU.

### Index Design: Shared Collection with Mandatory org_id Filter

We use a single OpenSearch Serverless collection for all tenants with a mandatory `org_id` filter on every query. This is a critical design decision.

**Why not per-tenant collections?**

Each OpenSearch Serverless collection requires a minimum of 2 OCU (1 indexing + 1 search) at $0.24/OCU-hour = **$346/month per collection**. With 100 tenants, that is $34,600/month just for empty collections. With 10,000 tenants, it is $3.46M/month. Per-tenant collections are economically impossible at scale.

**Tenant isolation in a shared collection:**

- Every document includes `org_id` as a required field
- Every search query includes `org_id` as a mandatory filter
- The API layer enforces `org_id` injection -- customers cannot query without it
- OpenSearch's filter execution happens before knn scoring, so tenant data never leaks into another tenant's results

### Collection Configuration

```json
{
  "name": "agentmail-emails",
  "type": "VECTORSEARCH",
  "standbyReplicas": "ENABLED",
  "description": "Shared email embedding collection for all tenants"
}
```

### Access Policy

```json
[
  {
    "Rules": [
      {
        "ResourceType": "collection",
        "Resource": ["collection/agentmail-emails"],
        "Permission": ["aoss:CreateCollectionItems", "aoss:UpdateCollectionItems", 
                       "aoss:DescribeCollectionItems", "aoss:DeleteCollectionItems"]
      },
      {
        "ResourceType": "index",
        "Resource": ["index/agentmail-emails/*"],
        "Permission": ["aoss:CreateIndex", "aoss:UpdateIndex", "aoss:DescribeIndex",
                       "aoss:ReadDocument", "aoss:WriteDocument"]
      }
    ],
    "Principal": [
      "arn:aws:iam::ACCOUNT:role/agentmail-lambda-role",
      "arn:aws:iam::ACCOUNT:role/agentmail-search-role"
    ]
  }
]
```

### Complete Index Mapping

```json
PUT /emails
{
  "settings": {
    "index": {
      "knn": true,
      "knn.algo_param.ef_search": 512,
      "number_of_shards": 4,
      "number_of_replicas": 1
    }
  },
  "mappings": {
    "properties": {
      "message_id": {
        "type": "keyword"
      },
      "org_id": {
        "type": "keyword"
      },
      "pod_id": {
        "type": "keyword"
      },
      "inbox_id": {
        "type": "keyword"
      },
      "thread_id": {
        "type": "keyword"
      },
      "from_address": {
        "type": "keyword"
      },
      "to_addresses": {
        "type": "keyword"
      },
      "subject": {
        "type": "text",
        "analyzer": "standard",
        "fields": {
          "keyword": {
            "type": "keyword",
            "ignore_above": 512
          }
        }
      },
      "body_text": {
        "type": "text",
        "analyzer": "standard"
      },
      "embedding": {
        "type": "knn_vector",
        "dimension": 512,
        "method": {
          "name": "hnsw",
          "space_type": "cosinesimil",
          "engine": "nmslib",
          "parameters": {
            "ef_construction": 512,
            "m": 16
          }
        }
      },
      "labels": {
        "type": "keyword"
      },
      "has_attachments": {
        "type": "boolean"
      },
      "attachment_count": {
        "type": "integer"
      },
      "size_bytes": {
        "type": "long"
      },
      "received_at": {
        "type": "date",
        "format": "strict_date_optional_time"
      },
      "direction": {
        "type": "keyword"
      },
      "indexed_at": {
        "type": "date",
        "format": "strict_date_optional_time"
      }
    }
  }
}
```

---

## Embedding Generation Pipeline

New messages are embedded asynchronously after text extraction completes.

```
Step Functions (Text Extraction complete)
    │
    ▼ (parallel branch)
SQS: agentmail-embedding-queue
    │
    │  Batch size: 10
    │  Max batching window: 5 seconds
    │
    ▼
Lambda: agentmail-embedding-generator
    │
    │  1. For each message in batch:
    │     a. Read extracted_text from Step Functions output
    │     b. Concatenate: subject + "\n\n" + extracted_text
    │     c. Call Bedrock InvokeModel (Titan V2, 512 dims)
    │  2. Bulk index to OpenSearch
    │
    ▼
OpenSearch Serverless: POST /_bulk
```

### Embedding Generator Lambda

```python
import json
import os
import time
from datetime import datetime, timezone

import boto3
from opensearchpy import OpenSearch, RequestsHttpConnection
from requests_aws4auth import AWS4Auth

bedrock = boto3.client("bedrock-runtime")
session = boto3.Session()
credentials = session.get_credentials()
region = os.environ.get("AWS_REGION", "us-east-1")

awsauth = AWS4Auth(
    credentials.access_key,
    credentials.secret_key,
    region,
    "aoss",
    session_token=credentials.token,
)

opensearch = OpenSearch(
    hosts=[{"host": os.environ["OPENSEARCH_ENDPOINT"], "port": 443}],
    http_auth=awsauth,
    use_ssl=True,
    verify_certs=True,
    connection_class=RequestsHttpConnection,
    timeout=30,
)

INDEX_NAME = "emails"
EMBEDDING_DIMENSIONS = 512


def handler(event, context):
    """Generate embeddings for a batch of messages and index to OpenSearch."""
    bulk_body = []
    
    for record in event["Records"]:
        message = json.loads(record["body"])
        
        message_id = message["messageId"]
        org_id = message["orgId"]
        pod_id = message["podId"]
        inbox_id = message["inboxId"]
        subject = message.get("subject", "")
        extracted_text = message.get("extracted_text", "")
        
        # Combine subject + body for embedding
        text_to_embed = f"{subject}\n\n{extracted_text}".strip()
        
        if not text_to_embed:
            continue
        
        # Truncate to Titan V2 context window
        if len(text_to_embed) > 30000:
            text_to_embed = text_to_embed[:30000]
        
        # Generate embedding
        try:
            embedding = generate_embedding(text_to_embed, EMBEDDING_DIMENSIONS)
        except Exception as e:
            print(f"Embedding failed for {message_id}: {e}")
            continue
        
        # Prepare bulk index action
        doc = {
            "message_id": message_id,
            "org_id": org_id,
            "pod_id": pod_id,
            "inbox_id": inbox_id,
            "thread_id": message.get("threadId"),
            "from_address": message.get("from"),
            "to_addresses": message.get("to", []),
            "subject": subject,
            "body_text": extracted_text[:10000],  # Limit BM25 indexed text
            "embedding": embedding,
            "labels": message.get("labels", []),
            "has_attachments": message.get("hasAttachments", False),
            "attachment_count": message.get("attachmentCount", 0),
            "size_bytes": message.get("size", 0),
            "received_at": message.get("receivedAt"),
            "direction": message.get("direction", "inbound"),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        
        bulk_body.append({"index": {"_index": INDEX_NAME, "_id": message_id}})
        bulk_body.append(doc)
    
    # Bulk index
    if bulk_body:
        response = opensearch.bulk(body=bulk_body)
        
        if response.get("errors"):
            for item in response["items"]:
                if "error" in item.get("index", {}):
                    print(f"Index error: {item['index']['error']}")
        
        print(f"Indexed {len(bulk_body) // 2} documents")
    
    return {"indexed": len(bulk_body) // 2}
```

### Lambda Configuration

```json
{
  "FunctionName": "agentmail-embedding-generator",
  "Runtime": "python3.12",
  "Architectures": ["arm64"],
  "MemorySize": 1024,
  "Timeout": 120,
  "ReservedConcurrentExecutions": 20,
  "Environment": {
    "Variables": {
      "OPENSEARCH_ENDPOINT": "xxxxx.us-east-1.aoss.amazonaws.com",
      "AWS_REGION": "us-east-1"
    }
  },
  "EventSourceMapping": {
    "EventSourceArn": "arn:aws:sqs:us-east-1:ACCOUNT:agentmail-embedding-queue",
    "BatchSize": 10,
    "MaximumBatchingWindowInSeconds": 5,
    "FunctionResponseTypes": ["ReportBatchItemFailures"]
  },
  "VpcConfig": {
    "SubnetIds": ["subnet-private-1", "subnet-private-2"],
    "SecurityGroupIds": ["sg-lambda"]
  }
}
```

### Indexing Latency

| Stage | Time |
|-------|------|
| SQS batching window | 0-5 seconds |
| SQS to Lambda trigger | ~100ms |
| Bedrock InvokeModel (per email) | ~200ms |
| Bedrock InvokeModel (batch of 10, sequential) | ~2 seconds |
| OpenSearch _bulk index | ~100ms |
| **Total (10-message batch)** | **~2.5 seconds** |
| **Total (single message, no batch wait)** | **~500ms** |

Target: new messages indexed within 30 seconds. Actual: typically 3-8 seconds (dominated by SQS batching window).

---

## Query Flow

```
POST /v1/search
{
  "query": "invoices from last month",
  "inbox_ids": ["inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"],
  "date_from": "2026-03-01T00:00:00Z",
  "date_to": "2026-03-31T23:59:59Z",
  "limit": 20,
  "rerank": false
}
    │
    ▼
Lambda: agentmail-search
    │
    │  1. Embed the query text via Titan V2
    │  2. Build OpenSearch query (knn + BM25 + filters)
    │  3. Execute search
    │  4. Optional: re-rank top results with amazon-rerank-v1.0
    │  5. Return ranked message IDs with scores
    │
    ▼
Response:
{
  "results": [
    { "messageId": "msg_xxx", "score": 0.92, "subject": "Invoice #1234", "snippet": "..." },
    { "messageId": "msg_yyy", "score": 0.87, "subject": "Payment receipt", "snippet": "..." }
  ],
  "total": 15,
  "query_time_ms": 145
}
```

### Search Lambda

```python
def search(query_text: str, org_id: str, filters: dict, limit: int = 20, rerank: bool = False) -> dict:
    """Execute a hybrid semantic + keyword search.
    
    Args:
        query_text: Natural language search query
        org_id: Organization ID (mandatory filter)
        filters: Optional filters (inbox_ids, pod_ids, date_from, date_to, labels, direction)
        limit: Maximum results to return
        rerank: Whether to re-rank results with Bedrock reranker
    """
    # Step 1: Embed the query
    query_embedding = generate_embedding(query_text, EMBEDDING_DIMENSIONS)
    
    # Step 2: Build filter
    must_filters = [
        {"term": {"org_id": org_id}},  # MANDATORY: tenant isolation
    ]
    
    if filters.get("inbox_ids"):
        must_filters.append({"terms": {"inbox_id": filters["inbox_ids"]}})
    
    if filters.get("pod_ids"):
        must_filters.append({"terms": {"pod_id": filters["pod_ids"]}})
    
    if filters.get("date_from") or filters.get("date_to"):
        date_range = {}
        if filters.get("date_from"):
            date_range["gte"] = filters["date_from"]
        if filters.get("date_to"):
            date_range["lte"] = filters["date_to"]
        must_filters.append({"range": {"received_at": date_range}})
    
    if filters.get("labels"):
        must_filters.append({"terms": {"labels": filters["labels"]}})
    
    if filters.get("direction"):
        must_filters.append({"term": {"direction": filters["direction"]}})
    
    # Step 3: Build hybrid query (knn + BM25)
    search_body = {
        "size": limit if not rerank else 50,  # Fetch more for re-ranking
        "query": {
            "bool": {
                "must": must_filters,
                "should": [
                    # BM25 keyword match on subject and body
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["subject^3", "body_text"],
                            "type": "best_fields",
                            "boost": 0.3,
                        }
                    },
                ],
            }
        },
        "knn": {
            "embedding": {
                "vector": query_embedding,
                "k": limit if not rerank else 50,
                "filter": {
                    "bool": {
                        "must": must_filters,
                    }
                },
            }
        },
        "_source": {
            "includes": ["message_id", "subject", "body_text", "from_address",
                        "received_at", "labels", "has_attachments", "direction"]
        },
    }
    
    # Step 4: Execute search
    response = opensearch.search(index=INDEX_NAME, body=search_body)
    
    hits = response["hits"]["hits"]
    
    # Step 5: Optional re-ranking
    if rerank and len(hits) > 1:
        hits = rerank_results(query_text, hits, limit)
    
    # Step 6: Format response
    results = []
    for hit in hits[:limit]:
        source = hit["_source"]
        results.append({
            "messageId": source["message_id"],
            "score": round(hit["_score"], 4),
            "subject": source.get("subject", ""),
            "snippet": (source.get("body_text", ""))[:200],
            "from": source.get("from_address"),
            "receivedAt": source.get("received_at"),
            "labels": source.get("labels", []),
            "hasAttachments": source.get("has_attachments", False),
            "direction": source.get("direction"),
        })
    
    return {
        "results": results,
        "total": response["hits"]["total"]["value"],
        "query_time_ms": response["took"],
    }
```

### Re-ranking with Amazon Rerank

For premium tier customers, we optionally re-rank the top 50 results using `amazon.rerank-v1:0` to improve precision:

```python
def rerank_results(query: str, hits: list, top_k: int) -> list:
    """Re-rank search results using Bedrock's reranker model.
    
    Takes the top 50 results from hybrid search and re-orders them
    by relevance using a cross-encoder reranker.
    
    Cost: $0.001 per 1000 text units (1 text unit = 1 token pair)
    """
    documents = []
    for hit in hits:
        source = hit["_source"]
        text = f"{source.get('subject', '')} {source.get('body_text', '')[:500]}"
        documents.append({"textDocument": {"text": text}})
    
    response = bedrock.invoke_model(
        modelId="amazon.rerank-v1:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "query": query,
            "documents": documents,
            "topN": top_k,
        }),
    )
    
    result = json.loads(response["body"].read())
    
    # Reorder hits based on reranker scores
    reranked = []
    for item in result["results"]:
        idx = item["index"]
        hit = hits[idx]
        hit["_score"] = item["relevanceScore"]
        reranked.append(hit)
    
    return reranked
```

---

## Hybrid Search: knn + BM25 + Metadata

The search system combines three scoring signals:

### 1. Vector Similarity (knn)

The `knn` clause performs approximate nearest neighbor search using the HNSW algorithm with cosine similarity. This finds emails that are semantically similar to the query, even without keyword overlap.

- **Algorithm:** HNSW (Hierarchical Navigable Small World)
- **Space type:** cosinesimil
- **ef_search:** 512 (higher = more accurate but slower; 512 is a good balance)
- **k:** Number of nearest neighbors to return

### 2. Keyword Match (BM25)

The `should` clause with `multi_match` performs traditional keyword search on `subject` (3x boosted) and `body_text`. This catches exact keyword matches that vector search might miss (e.g., order numbers, email addresses, proper nouns).

- **Boost:** 0.3 relative to knn score (knn is the primary signal)
- **Fields:** subject (3x weight), body_text
- **Type:** best_fields (uses the best-matching field's score)

### 3. Metadata Filters

All `must` clauses in the `bool` query are filters. They do not affect scoring -- they only include or exclude documents. Filters are applied before knn scoring, so they reduce the search space and improve performance.

Filterable fields:
- `org_id` (mandatory)
- `inbox_id` / `pod_id`
- `received_at` (date range)
- `labels` (categorization results)
- `direction` (inbound/outbound)
- `has_attachments`
- `from_address`

### Complete Search Query Example

```json
{
  "size": 20,
  "query": {
    "bool": {
      "must": [
        { "term": { "org_id": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W" } },
        { "terms": { "inbox_id": ["inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"] } },
        { "range": { "received_at": { "gte": "2026-03-01T00:00:00Z", "lte": "2026-03-31T23:59:59Z" } } },
        { "terms": { "labels": ["billing"] } }
      ],
      "should": [
        {
          "multi_match": {
            "query": "invoices from last month",
            "fields": ["subject^3", "body_text"],
            "type": "best_fields",
            "boost": 0.3
          }
        }
      ]
    }
  },
  "knn": {
    "embedding": {
      "vector": [0.023, -0.156, 0.089, "...512 dimensions..."],
      "k": 20,
      "filter": {
        "bool": {
          "must": [
            { "term": { "org_id": "org_01JRQ4F8M2NXKB6P3C7D9E0H5W" } },
            { "terms": { "inbox_id": ["inbox_01JRQ4HA04QZLD8R5E9F1G2K7Y"] } },
            { "range": { "received_at": { "gte": "2026-03-01T00:00:00Z", "lte": "2026-03-31T23:59:59Z" } } }
          ]
        }
      }
    }
  },
  "_source": {
    "includes": ["message_id", "subject", "body_text", "from_address", "received_at", "labels", "has_attachments"]
  }
}
```

---

## Cost Breakdown

### OpenSearch Serverless

OpenSearch Serverless charges by OCU-hour (OpenSearch Compute Unit). Each OCU provides ~6 GB RAM and proportional CPU/storage.

| Component | Minimum OCU | Cost/OCU-hour | Monthly Minimum |
|-----------|-------------|---------------|-----------------|
| Indexing | 1 | $0.24 | $175 |
| Search | 1 | $0.24 | $175 |
| **Total minimum** | **2** | | **$350/mo** |

**Auto-scaling:** OCUs scale based on workload. The minimum is always 2 (1 indexing + 1 search). At 1M documents, we stay at 2 OCUs. At 100M documents, we may need 4-6 OCUs.

### Managed Storage

$0.024/GB-month for indexed data.

| Scale | Documents | Estimated Index Size | Storage Cost |
|-------|-----------|---------------------|-------------|
| Startup (100K/day, 30-day retention) | 3M | ~6 GB | $0.14/mo |
| Growth (1M/day, 90-day retention) | 90M | ~180 GB | $4.32/mo |
| Full Scale (10M/day, 90-day retention) | 900M | ~1.8 TB | $43.20/mo |

### Total Search Cost by Scale

| Scale | OpenSearch OCU | Storage | Embeddings (Titan) | Reranker (optional) | Total |
|-------|---------------|---------|-------------------|--------------------|----|
| **Startup** (100K/day) | $350/mo (2 OCU) | $0.14/mo | $30/mo | $0/mo | **~$380/mo** |
| **Growth** (1M/day) | $700/mo (4 OCU) | $4.32/mo | $300/mo | $50/mo | **~$1,054/mo** |
| **Full Scale** (10M/day) | $1,400/mo (8 OCU) | $43.20/mo | $3,000/mo | $500/mo | **~$4,943/mo** |

The $350/mo OpenSearch minimum is the dominant cost at startup. It is a fixed cost that does not scale linearly -- at full scale, the per-document cost drops from $0.00012 to $0.000005.
