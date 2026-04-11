# SDK Generation

AgentMail generates client SDKs for Python, Node.js, and Go from a single OpenAPI 3.1 specification. The generation pipeline runs automatically on spec changes via GitHub Actions and publishes packages to PyPI, npm, and Go modules.

---

## Architecture

```
OpenAPI 3.1 Spec (openapi.yaml)
        |
        v
  openapi-generator-cli
   |        |        |
   v        v        v
Python    Node.js    Go
SDK       SDK        SDK
   |        |        |
   v        v        v
 PyPI      npm     Go Modules
(agentmail) (@agentmail/sdk) (github.com/agentmail/agentmail-go)
```

---

## OpenAPI Specification

The OpenAPI 3.1 spec is the single source of truth for the API surface. It lives at `/api/openapi.yaml` in the repository and is used for:

1. SDK generation (this document)
2. API Gateway request validation
3. API documentation rendering
4. Contract testing

### Spec Structure

```
api/
  openapi.yaml          # Root spec file
  components/
    schemas/            # Shared data models
      organization.yaml
      inbox.yaml
      message.yaml
      thread.yaml
      draft.yaml
      domain.yaml
      webhook.yaml
      list.yaml
      api-key.yaml
      pod.yaml
      error.yaml
      pagination.yaml
    parameters/         # Shared parameters
      page-token.yaml
      limit.yaml
      ascending.yaml
    responses/          # Shared responses
      not-found.yaml
      unauthorized.yaml
      rate-limited.yaml
    security-schemes/
      api-key.yaml
  paths/
    agent.yaml
    organizations.yaml
    api-keys.yaml
    pods.yaml
    inboxes.yaml
    messages.yaml
    threads.yaml
    drafts.yaml
    domains.yaml
    webhooks.yaml
    lists.yaml
    metrics.yaml
    search.yaml
```

### Spec Excerpt

```yaml
openapi: "3.1.0"
info:
  title: AgentMail API
  version: "1.0.0"
  description: |
    Programmatic email for AI agents. Create inboxes, send and receive
    messages, manage threads, and search across your organization's email
    -- all via API.
  contact:
    name: AgentMail Support
    email: support@agentmail.aws
    url: https://docs.agentmail.aws
servers:
  - url: https://api.agentmail.aws/v1
    description: Production
  - url: https://api-sandbox.agentmail.aws/v1
    description: Sandbox (test keys only)

security:
  - ApiKeyHeader: []
  - BearerAuth: []

components:
  securitySchemes:
    ApiKeyHeader:
      type: apiKey
      in: header
      name: x-api-key
    BearerAuth:
      type: http
      scheme: bearer

  schemas:
    Inbox:
      type: object
      required: [id, email, status, created_at]
      properties:
        id:
          type: string
          description: ULID identifier
          example: "01HXYZ1234567890ABCDEFGHJA"
        email:
          type: string
          format: email
          example: "agent-47@mail.acme.com"
        display_name:
          type: string
          nullable: true
          example: "Support Agent 47"
        pod_id:
          type: string
          nullable: true
        status:
          type: string
          enum: [active, paused, deleted]
        message_count:
          type: integer
        unread_count:
          type: integer
        settings:
          $ref: "#/components/schemas/InboxSettings"
        created_at:
          type: string
          format: date-time
        updated_at:
          type: string
          format: date-time

    Error:
      type: object
      required: [error]
      properties:
        error:
          type: object
          required: [code, message]
          properties:
            code:
              type: string
              example: "RESOURCE_NOT_FOUND"
            message:
              type: string
              example: "Inbox 01HXYZ... not found."

    PaginatedResponse:
      type: object
      properties:
        next_page_token:
          type: string
          nullable: true
        has_more:
          type: boolean
```

---

## Generator Configuration

### openapi-generator-cli

We use [openapi-generator-cli](https://openapi-generator.tech/) version 7.x for all three languages.

### Python Configuration

```yaml
# config/python.yaml
generatorName: python
outputDir: sdks/python
additionalProperties:
  packageName: agentmail
  projectName: agentmail
  packageVersion: "1.0.0"
  library: urllib3
  generateSourceCodeOnly: false
  useOneOfDiscriminatorLookup: true
  disallowAdditionalPropertiesIfNotPresent: false
  enumUnknownDefaultCase: true
globalProperties:
  apiTests: true
  modelTests: true
typeMappings:
  DateTime: datetime
importMappings:
  datetime: datetime
```

### Node.js Configuration

```yaml
# config/nodejs.yaml
generatorName: typescript-node
outputDir: sdks/nodejs
additionalProperties:
  npmName: "@agentmail/sdk"
  npmVersion: "1.0.0"
  supportsES6: true
  withInterfaces: true
  enumPropertyNaming: original
  modelPropertyNaming: original
  paramNaming: original
globalProperties:
  apiTests: true
  modelTests: true
```

### Go Configuration

```yaml
# config/go.yaml
generatorName: go
outputDir: sdks/go
additionalProperties:
  packageName: agentmail
  packageVersion: "1.0.0"
  generateInterfaces: true
  structPrefix: true
  withGoMod: true
  isGoSubmodule: false
  enumClassPrefix: true
globalProperties:
  apiTests: true
  modelTests: true
```

---

## GitHub Actions Workflow

```yaml
# .github/workflows/sdk-generate.yaml
name: Generate and Publish SDKs

on:
  push:
    branches: [main]
    paths:
      - "api/openapi.yaml"
      - "api/components/**"
      - "api/paths/**"
  workflow_dispatch:
    inputs:
      version:
        description: "SDK version override (e.g., 1.2.3)"
        required: false

permissions:
  contents: write
  packages: write

env:
  OPENAPI_GENERATOR_VERSION: "7.4.0"

jobs:
  validate-spec:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate OpenAPI spec
        run: |
          npx @redocly/cli lint api/openapi.yaml --format=stylish
          npx @redocly/cli bundle api/openapi.yaml --output api/bundled.yaml

      - name: Upload bundled spec
        uses: actions/upload-artifact@v4
        with:
          name: openapi-spec
          path: api/bundled.yaml

  generate-python:
    needs: validate-spec
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download bundled spec
        uses: actions/download-artifact@v4
        with:
          name: openapi-spec
          path: api/

      - name: Generate Python SDK
        run: |
          docker run --rm \
            -v "$PWD:/workspace" \
            openapitools/openapi-generator-cli:v${{ env.OPENAPI_GENERATOR_VERSION }} \
            generate \
            -i /workspace/api/bundled.yaml \
            -c /workspace/config/python.yaml

      - name: Apply custom patches
        run: |
          # Add async client wrapper
          cp templates/python/async_client.py sdks/python/agentmail/async_client.py
          # Add WebSocket support
          cp templates/python/websocket.py sdks/python/agentmail/websocket.py
          # Add retry logic
          cp templates/python/retry.py sdks/python/agentmail/retry.py

      - name: Run tests
        run: |
          cd sdks/python
          pip install -e ".[dev]"
          pytest tests/ -v

      - name: Publish to PyPI
        if: github.ref == 'refs/heads/main'
        env:
          TWINE_USERNAME: __token__
          TWINE_PASSWORD: ${{ secrets.PYPI_TOKEN }}
        run: |
          cd sdks/python
          python -m build
          twine upload dist/*

  generate-nodejs:
    needs: validate-spec
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download bundled spec
        uses: actions/download-artifact@v4
        with:
          name: openapi-spec
          path: api/

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          registry-url: "https://registry.npmjs.org"

      - name: Generate Node.js SDK
        run: |
          docker run --rm \
            -v "$PWD:/workspace" \
            openapitools/openapi-generator-cli:v${{ env.OPENAPI_GENERATOR_VERSION }} \
            generate \
            -i /workspace/api/bundled.yaml \
            -c /workspace/config/nodejs.yaml

      - name: Apply custom patches
        run: |
          cp templates/nodejs/websocket.ts sdks/nodejs/src/websocket.ts
          cp templates/nodejs/retry.ts sdks/nodejs/src/retry.ts

      - name: Build and test
        run: |
          cd sdks/nodejs
          npm install
          npm run build
          npm test

      - name: Publish to npm
        if: github.ref == 'refs/heads/main'
        env:
          NODE_AUTH_TOKEN: ${{ secrets.NPM_TOKEN }}
        run: |
          cd sdks/nodejs
          npm publish --access public

  generate-go:
    needs: validate-spec
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Download bundled spec
        uses: actions/download-artifact@v4
        with:
          name: openapi-spec
          path: api/

      - uses: actions/setup-go@v5
        with:
          go-version: "1.22"

      - name: Generate Go SDK
        run: |
          docker run --rm \
            -v "$PWD:/workspace" \
            openapitools/openapi-generator-cli:v${{ env.OPENAPI_GENERATOR_VERSION }} \
            generate \
            -i /workspace/api/bundled.yaml \
            -c /workspace/config/go.yaml

      - name: Apply custom patches
        run: |
          cp templates/go/websocket.go sdks/go/websocket.go
          cp templates/go/retry.go sdks/go/retry.go

      - name: Test
        run: |
          cd sdks/go
          go test ./...

      - name: Tag and push
        if: github.ref == 'refs/heads/main'
        run: |
          VERSION=$(cat sdks/go/version.go | grep -oP 'Version = "\K[^"]+')
          git tag "sdks/go/v${VERSION}"
          git push origin "sdks/go/v${VERSION}"
```

---

## SDK Features

### Sync and Async Clients

All SDKs provide both synchronous and asynchronous clients.

**Python:**

```python
from agentmail import AgentMail, AsyncAgentMail

# Synchronous
client = AgentMail(api_key="am_live_...")
inboxes = client.inboxes.list(limit=10)

# Asynchronous
async_client = AsyncAgentMail(api_key="am_live_...")
inboxes = await async_client.inboxes.list(limit=10)
```

**Node.js:**

```typescript
import { AgentMail } from "@agentmail/sdk";

const client = new AgentMail({ apiKey: "am_live_..." });

// Promise-based (all methods return promises)
const inboxes = await client.inboxes.list({ limit: 10 });
```

**Go:**

```go
import "github.com/agentmail/agentmail-go"

client := agentmail.NewClient("am_live_...")

// Context-based
inboxes, err := client.Inboxes.List(ctx, &agentmail.ListInboxesParams{
    Limit: agentmail.Int(10),
})
```

### Retry with Exponential Backoff

All SDKs automatically retry on transient failures (429, 500, 502, 503, 504) with exponential backoff and jitter.

```python
# Default retry configuration
client = AgentMail(
    api_key="am_live_...",
    max_retries=3,           # Maximum retry attempts
    retry_delay=1.0,         # Initial delay in seconds
    retry_max_delay=30.0,    # Maximum delay between retries
    retry_backoff=2.0,       # Backoff multiplier
    retry_jitter=0.25,       # Random jitter factor (0-1)
)

# Retry logic pseudocode:
# delay = min(retry_delay * (retry_backoff ** attempt), retry_max_delay)
# delay = delay * (1 + random(-retry_jitter, retry_jitter))
# For 429: use Retry-After header if present, otherwise backoff
```

### Timeout Configuration

```python
client = AgentMail(
    api_key="am_live_...",
    timeout=30.0,            # Request timeout in seconds
    connect_timeout=5.0,     # Connection timeout in seconds
)

# Per-request timeout override
inbox = client.inboxes.get("01HXYZ...", timeout=10.0)
```

### Raw Response Access

All SDKs expose the raw HTTP response alongside the parsed model.

```python
# Python: raw response
response = client.inboxes.list(limit=10)
print(response.data)           # Parsed list of Inbox objects
print(response.status_code)    # 200
print(response.headers)        # Dict of response headers
print(response.rate_limit)     # RateLimit object with limit, remaining, reset
```

```typescript
// Node.js: raw response
const response = await client.inboxes.list({ limit: 10 }, { rawResponse: true });
console.log(response.data);         // Parsed array of Inbox objects
console.log(response.statusCode);   // 200
console.log(response.headers);      // Headers object
console.log(response.rateLimit);    // { limit, remaining, reset }
```

### WebSocket Support

All SDKs include first-class WebSocket support for real-time events.

```python
from agentmail import AgentMail

client = AgentMail(api_key="am_live_...")

# Connect and subscribe
ws = client.ws.connect()
ws.subscribe(["inbox:01HXYZ...", "org:01HXYZ..."])

# Event handler
@ws.on("message.received")
def on_message(event):
    print(f"New message from {event.data.from_address}")
    print(f"Subject: {event.data.subject}")

# Or iterate events
async for event in ws.events():
    if event.type == "message.received":
        print(f"New message: {event.data.subject}")
```

### Auto-Pagination

All SDKs support automatic pagination for list endpoints.

```python
# Python: auto-pagination
for inbox in client.inboxes.list_auto_paginate():
    print(inbox.email)

# With async
async for inbox in async_client.inboxes.list_auto_paginate():
    print(inbox.email)
```

```typescript
// Node.js: auto-pagination
for await (const inbox of client.inboxes.listAutoPaginate()) {
  console.log(inbox.email);
}
```

```go
// Go: auto-pagination
iter := client.Inboxes.ListAutoPaginate(ctx, nil)
for iter.Next() {
    inbox := iter.Current()
    fmt.Println(inbox.Email)
}
if err := iter.Err(); err != nil {
    log.Fatal(err)
}
```

---

## Versioning Strategy

### API Versioning

- The API version is encoded in the URL path (`/v1/`).
- Breaking changes require a new major version (`/v2/`).
- Non-breaking additions (new fields, new endpoints) do not require a version bump.
- Deprecated fields are marked in the OpenAPI spec and SDKs emit deprecation warnings.

### SDK Versioning

SDKs follow [Semantic Versioning](https://semver.org/):

- **Major** (1.0.0 -> 2.0.0): Breaking changes to the SDK interface (renamed methods, removed parameters). Typically aligned with API version bumps.
- **Minor** (1.0.0 -> 1.1.0): New endpoints, new optional parameters, new response fields.
- **Patch** (1.0.0 -> 1.0.1): Bug fixes, documentation updates, internal improvements.

### Version Mapping

| API Version | Python SDK | Node.js SDK | Go SDK |
|-------------|-----------|-------------|--------|
| v1 | 1.x.x | 1.x.x | v1.x.x |
| v2 (future) | 2.x.x | 2.x.x | v2.x.x |

### Deprecation Policy

- Deprecated API versions are supported for 12 months after the next version ships.
- SDKs emit compile-time or runtime deprecation warnings for deprecated fields/methods.
- The OpenAPI spec uses `deprecated: true` on deprecated operations and properties.

---

## Custom Templates

Generated SDKs are enhanced with custom code that cannot be auto-generated:

| Feature | Location | Description |
|---------|----------|-------------|
| Async client | `templates/{lang}/async_client.*` | Async wrapper around generated sync client |
| WebSocket | `templates/{lang}/websocket.*` | WebSocket connection, auth, subscribe, event handling |
| Retry logic | `templates/{lang}/retry.*` | Exponential backoff with jitter, Retry-After support |
| Auto-pagination | `templates/{lang}/pagination.*` | Iterator/generator for automatic cursor pagination |
| Rate limit helpers | `templates/{lang}/rate_limit.*` | Parse rate limit headers, expose on response object |
| Error classes | `templates/{lang}/errors.*` | Typed exceptions for each error code |

These files are copied over the generated code in the "Apply custom patches" step of the CI pipeline. They import and extend the generated base classes.
