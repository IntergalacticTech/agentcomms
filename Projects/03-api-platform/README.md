# API Platform

The AgentMail API Platform is the primary interface through which AI agents and developers interact with the system. Built on Amazon API Gateway (REST + WebSocket), AWS Lambda, and backed by DynamoDB, the platform exposes a RESTful JSON API with real-time WebSocket support, cursor-based pagination, and comprehensive rate limiting.

---

## Architecture Summary

```
Client (SDK / HTTP / WebSocket)
        |
   Route 53 (api.agentmail.aws)
        |
   CloudFront (edge caching for GET, TLS termination)
        |
   API Gateway (REST + WebSocket)
        |
   Lambda Authorizer (API key validation, scope resolution)
        |
   Lambda Functions (business logic, one per resource group)
        |
   +-----------+-----------+-----------+
   | DynamoDB  |    S3     |  Redis    |
   | (metadata)|  (bodies) | (cache)   |
   +-----------+-----------+-----------+
```

All API traffic enters through API Gateway, which delegates authentication to a Lambda authorizer. The authorizer validates API keys against a Redis cache (with DynamoDB fallback), resolves organizational scope, and returns an IAM policy that gates access to downstream Lambda functions. Each resource group (inboxes, messages, threads, etc.) is handled by a dedicated Lambda function to enable independent scaling and deployment.

---

## Sub-Documents

| Document | Description |
|----------|-------------|
| [API Design](./api-design.md) | Complete endpoint listing, request/response shapes, pagination, error handling, and query parameters |
| [Authentication](./authentication.md) | API key format, Lambda authorizer flow, OTP verification, key scoping, and rotation strategy |
| [Rate Limiting](./rate-limiting.md) | Three-tier rate limiting architecture: API Gateway usage plans, Redis sliding window, and WAF rules |
| [SDK Generation](./sdk-generation.md) | OpenAPI-driven SDK generation pipeline for Python, Node.js, and Go with CI/CD publishing |

---

## Key Design Decisions

1. **REST over GraphQL.** AI agents work best with predictable, discoverable endpoints. REST with consistent resource naming and cursor pagination is simpler to integrate than GraphQL for machine clients.

2. **Single API Gateway stage per environment.** Production, staging, and development each get their own API Gateway deployment. No stage variables or path-based routing between environments.

3. **Lambda-per-resource-group, not Lambda-per-endpoint.** Each resource group (e.g., all `/inboxes/*` routes) maps to a single Lambda function that handles internal routing. This balances cold-start performance (fewer functions to keep warm) against code isolation.

4. **Cursor-based pagination everywhere.** Offset-based pagination breaks under concurrent writes. All list endpoints use opaque `page_token` cursors backed by DynamoDB `ExclusiveStartKey` serialization.

5. **WebSocket for real-time, webhooks for reliability.** The WebSocket API provides instant push notifications for connected clients, while webhooks provide durable delivery with retry for disconnected integrations.

---

## API Gateway Configuration

| Property | Value |
|----------|-------|
| Type | REST API (regional) + WebSocket API |
| Endpoint | `https://api.agentmail.aws/v1/` |
| WebSocket | `wss://ws.agentmail.aws/v1/ws` |
| Auth | Lambda authorizer (request-based) |
| Throttle (default) | 10,000 rps burst, 5,000 rps sustained |
| Payload limit | 10 MB (API Gateway max) |
| Timeout | 29 seconds (API Gateway max) |
| Binary media | `application/octet-stream`, `multipart/form-data` |
| CORS | Enabled for `*` (API keys are not cookie-based) |
| Logging | Full request/response logging to CloudWatch |
| Tracing | X-Ray active tracing enabled |
