# AgentComms Phase 1: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-04-17-agentcomms-pivot-design.md`

**Goal:** Land the new Agent-centric data model, `ChannelAdapter` SDK, and the first adapter (Email) — producing a working hub where a user can create an Agent, provision an email channel, and send/receive email through the new unified-inbox abstraction. Every later phase depends on what Phase 1 ships.

**Architecture:** New `core/` package holds hub-generic code (data models, adapter base/registry, address router, REST handlers, authorizer). New `adapters/` package holds per-channel plugins, starting with `adapters/email/`. New DynamoDB table `agentcomms` deployed in parallel to the existing `victorymail` table (no data migration in this phase — that's Phase 5). New CDK stacks `agentcomms-data-stack`, `agentcomms-api-stack`, `agentcomms-adapters-stack` deployed alongside existing victorymail stacks.

**Tech Stack:** Python 3.12, Pydantic v2, boto3, pytest + moto (AWS mocking), AWS CDK v2 (TypeScript), AWS Lambda, DynamoDB, SES, S3, Kinesis.

**Phase 1 exit criteria (validated at Task 54):**
- New `agentcomms` DynamoDB table deployed with all 7 GSIs
- `POST /v1/agents` with email provisioning creates Agent + Channel + SES identity
- Inbound email → adapter `ingest()` → `UnifiedMessage` written with `is_dm=true` → appears on GSI3
- Outbound: `POST /v1/agents/{id}/messages {to: "...@x.com", body: "..."}` → address router → Email adapter → SES `SendRawEmail`
- `GET /v1/agents/{id}/messages` returns unified inbox via one DynamoDB Query on GSI3
- All Phase 1 Python unit + integration tests pass (target: ~120 tests)
- CDK synth + assertion tests pass

**What Phase 1 does NOT ship** (deferred to later phases):
- Any channel other than email (Phase 2 SMS/Push, Phase 3 Slack/Telegram)
- Data migration from `victorymail` table (Phase 5)
- Repo rename or OSS packaging (Phase 4)
- Cutover of `api.victorymail.dev` (Phase 5)

---

## File Structure

### New Python packages (created in this phase)

```
core/                                    # hub-generic code
├── __init__.py
├── adapters/
│   ├── __init__.py
│   ├── base.py                          # ChannelAdapter ABC + support types
│   └── registry.py                      # manifest.toml scanning + entry_points loading
├── data/
│   ├── __init__.py
│   ├── models.py                        # Pydantic v2 models: Org, Agent, Channel, UnifiedMessage, ApiKey, Thread, Draft, Webhook, Attachment
│   ├── repo.py                          # DynamoDB single-table access layer
│   └── ulid_.py                         # ULID generator wrapper (reuse lambdas/shared/ulid.py style)
├── router/
│   ├── __init__.py
│   └── address.py                       # address-format → channel inference
└── api/
    ├── __init__.py
    ├── authorizer.py                    # Lambda authorizer (new scope model)
    ├── agents_handler.py                # /v1/agents/* routes
    ├── channels_handler.py              # /v1/agents/{id}/channels/* routes
    ├── messages_handler.py              # /v1/agents/{id}/messages/* routes
    ├── threads_handler.py
    ├── drafts_handler.py
    ├── webhooks_handler.py
    ├── wait_handler.py
    ├── otp_handler.py
    └── _common.py                       # shared request/response helpers (reuse response.py pattern)

adapters/                                # per-channel plugins
├── __init__.py
└── email/
    ├── __init__.py
    ├── manifest.toml                    # adapter registration
    ├── adapter.py                       # EmailAdapter(ChannelAdapter)
    ├── normalize.py                     # MIME parse, quoted-reply strip, threading extraction
    ├── ingest.py                        # Lambda handler (SES → SNS → this)
    ├── outbound.py                      # Lambda handler for SES SendRawEmail
    ├── stack.py                         # CDK fragment for email-specific AWS resources
    └── tests/
        ├── __init__.py
        ├── test_adapter.py
        ├── test_normalize.py
        └── fixtures/
            ├── inbound_simple.eml
            ├── inbound_with_attachment.eml
            └── inbound_gmail_reply.eml

tests/                                   # shared test tree (existing structure expanded)
├── conftest.py                          # MODIFIED: add agentcomms table fixture, Pydantic factories
├── core/
│   ├── __init__.py
│   ├── test_models.py                   # Pydantic roundtrip + validation
│   ├── test_repo.py                     # DynamoDB CRUD against moto
│   ├── test_router.py                   # address-format inference
│   ├── test_registry.py                 # adapter discovery
│   └── test_authorizer.py
├── api/
│   ├── __init__.py
│   ├── test_agents.py
│   ├── test_channels.py
│   ├── test_messages.py                 # unified inbox GSI3 behavior
│   ├── test_threads.py
│   ├── test_drafts.py
│   ├── test_webhooks.py
│   ├── test_wait.py
│   └── test_otp.py
└── e2e/
    ├── __init__.py
    └── test_email_roundtrip.py          # provision agent → send → receive → query inbox
```

### New CDK stacks

```
cdk/lib/stacks/
├── agentcomms-data-stack.ts             # NEW — agentcomms table + S3 buckets
├── agentcomms-api-stack.ts              # NEW — API Gateway + authorizer + handler Lambdas
├── agentcomms-adapters-stack.ts         # NEW — iterates adapters/*/manifest.toml, calls adapter.cdk_wiring()
└── [existing victorymail-* stacks stay untouched]
```

### Modifications to existing files

- `pyproject.toml` — add `core` + `adapters` packages; add test dependencies (moto, faker)
- `cdk/bin/app.ts` — add agentcomms stacks alongside victorymail stacks
- `requirements.txt` — no new top-level deps (Pydantic, boto3 already present); pin versions

### Files explicitly NOT touched in Phase 1

- `lambdas/*` — existing handlers keep running victorymail traffic
- `cdk/lib/stacks/data-stack.ts`, `api-stack.ts`, `queue-stack.ts`, `email-stack.ts` (victorymail-* stacks) — untouched
- `console/*`, `sdks/*`, `mcp/*` — Phase 4 work
- `docs/*` (except spec+plan files) — Phase 4

---

## Baseline assumption

All current FreeMail tests pass at the start of Phase 1 on the `phase1-foundation` feature branch. Task 1 verifies this.

---

## Task 1: Create feature branch and verify baseline

**Files:**
- No file changes; git-only.

- [ ] **Step 1: Create feature branch**

```bash
cd /Users/jwc/code/Victory/FreeMail.ai
git checkout -b phase1-foundation
git status
```

Expected: on branch `phase1-foundation`, working tree may have the pre-pivot uncommitted work from `git status` (those changes stay unstaged throughout Phase 1 — they're for Phase 2).

- [ ] **Step 2: Run the full existing test suite**

```bash
source .venv/bin/activate 2>/dev/null || python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest pytest-cov moto faker
pytest -x -q
```

Expected: all current tests pass. If not, stop and fix before proceeding — a Phase 1 that starts on red can't be trusted.

- [ ] **Step 3: Verify CDK synth on existing stacks**

```bash
cd cdk && npx cdk synth --all > /dev/null && echo OK
cd ..
```

Expected: `OK`. CDK synth produces no errors.

- [ ] **Step 4: Commit a marker (empty) to start Phase 1 history cleanly**

```bash
git commit --allow-empty -m "chore: start Phase 1 (AgentComms foundation)"
```

---

## Task 2: Scaffold `core/` and `adapters/` Python packages

**Files:**
- Create: `core/__init__.py`
- Create: `core/adapters/__init__.py`
- Create: `core/data/__init__.py`
- Create: `core/router/__init__.py`
- Create: `core/api/__init__.py`
- Create: `adapters/__init__.py`
- Create: `adapters/email/__init__.py`
- Create: `adapters/email/tests/__init__.py`
- Create: `adapters/email/tests/fixtures/.gitkeep`
- Create: `tests/core/__init__.py`
- Create: `tests/api/__init__.py`
- Create: `tests/e2e/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create package directory structure**

```bash
mkdir -p core/adapters core/data core/router core/api \
         adapters/email/tests/fixtures \
         tests/core tests/api tests/e2e
```

- [ ] **Step 2: Create `__init__.py` files**

```bash
for f in core core/adapters core/data core/router core/api \
         adapters adapters/email adapters/email/tests \
         tests/core tests/api tests/e2e; do
  touch "$f/__init__.py"
done
touch adapters/email/tests/fixtures/.gitkeep
```

- [ ] **Step 3: Update `pyproject.toml`**

Add `core` and `adapters` to the packages list. If `pyproject.toml` doesn't declare packages yet, add this block:

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["core*", "adapters*", "lambdas*"]
exclude = ["tests*", "cdk*", "console*", "sdks*", "mcp*", "docs*"]

[tool.pytest.ini_options]
testpaths = ["tests", "adapters/*/tests"]
python_files = ["test_*.py"]
```

Read the current `pyproject.toml` first; if it already has these sections, merge rather than overwrite.

- [ ] **Step 4: Verify Python can import the new packages**

```bash
python -c "import core, core.adapters, core.data, core.router, core.api, adapters, adapters.email; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add core/ adapters/ tests/core/__init__.py tests/api/__init__.py tests/e2e/__init__.py pyproject.toml
git commit -m "feat(phase1): scaffold core/ and adapters/ packages"
```

---

## Task 3: Add shared test fixtures (moto-backed DynamoDB + SES + S3 + SNS + Kinesis)

**Files:**
- Create: `tests/conftest.py` (may exist; merge carefully)
- Test: runs implicitly against later tasks

- [ ] **Step 1: Read existing `tests/conftest.py` if present**

```bash
[ -f tests/conftest.py ] && cat tests/conftest.py || echo "does not exist"
```

If it exists, open it in your editor. Do NOT clobber existing fixtures — add to them. If it doesn't exist, create fresh.

- [ ] **Step 2: Write the failing fixture-consumer test**

Create `tests/core/test_fixtures_smoke.py`:

```python
import pytest

def test_agentcomms_table_fixture_exists(agentcomms_table):
    """Fixture provides a moto-backed DynamoDB table named 'agentcomms' with all 7 GSIs."""
    assert agentcomms_table.table_name == "agentcomms"
    gsi_names = {gsi["IndexName"] for gsi in agentcomms_table.global_secondary_indexes}
    assert gsi_names == {"GSI1", "GSI2", "GSI3", "GSI4", "GSI5", "GSI6", "GSI7"}

def test_ses_client_fixture_exists(ses_client):
    """Fixture provides a moto-backed SES client."""
    response = ses_client.list_identities()
    assert "Identities" in response

def test_s3_buckets_fixture_exists(s3_buckets):
    """Fixture provides the three agentcomms S3 buckets."""
    assert set(s3_buckets.keys()) == {"raw_inbound", "bodies", "attachments"}
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
pytest tests/core/test_fixtures_smoke.py -v
```

Expected: FAIL with `fixture 'agentcomms_table' not found` (or similar).

- [ ] **Step 4: Implement the fixtures in `tests/conftest.py`**

```python
# tests/conftest.py
import os
import pytest
import boto3
from moto import mock_aws

# Force moto to intercept all AWS calls
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AGENTCOMMS_TABLE", "agentcomms")


_AGENTCOMMS_TABLE_SCHEMA = {
    "TableName": "agentcomms",
    "AttributeDefinitions": [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
        {"AttributeName": "gsi1_pk", "AttributeType": "S"},
        {"AttributeName": "gsi1_sk", "AttributeType": "S"},
        {"AttributeName": "gsi2_pk", "AttributeType": "S"},
        {"AttributeName": "gsi2_sk", "AttributeType": "S"},
        {"AttributeName": "gsi3_pk", "AttributeType": "S"},
        {"AttributeName": "gsi3_sk", "AttributeType": "S"},
        {"AttributeName": "gsi4_pk", "AttributeType": "S"},
        {"AttributeName": "gsi4_sk", "AttributeType": "S"},
        {"AttributeName": "gsi5_pk", "AttributeType": "S"},
        {"AttributeName": "gsi5_sk", "AttributeType": "S"},
        {"AttributeName": "gsi6_pk", "AttributeType": "S"},
        {"AttributeName": "gsi6_sk", "AttributeType": "S"},
        {"AttributeName": "gsi7_pk", "AttributeType": "S"},
        {"AttributeName": "gsi7_sk", "AttributeType": "S"},
    ],
    "KeySchema": [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ],
    "BillingMode": "PAY_PER_REQUEST",
    "GlobalSecondaryIndexes": [
        {
            "IndexName": f"GSI{i}",
            "KeySchema": [
                {"AttributeName": f"gsi{i}_pk", "KeyType": "HASH"},
                {"AttributeName": f"gsi{i}_sk", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
        for i in range(1, 8)
    ],
}


@pytest.fixture
def aws_mock():
    """Activate moto for all AWS clients in the test."""
    with mock_aws():
        yield


@pytest.fixture
def agentcomms_table(aws_mock):
    """Moto-backed DynamoDB table 'agentcomms' with all 7 GSIs."""
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(**_AGENTCOMMS_TABLE_SCHEMA)
    table = dynamodb.Table("agentcomms")
    table.wait_until_exists()
    return table


@pytest.fixture
def ses_client(aws_mock):
    return boto3.client("ses", region_name="us-east-1")


@pytest.fixture
def s3_buckets(aws_mock):
    s3 = boto3.client("s3", region_name="us-east-1")
    buckets = {
        "raw_inbound": "agentcomms-raw-inbound-test",
        "bodies": "agentcomms-bodies-test",
        "attachments": "agentcomms-attachments-test",
    }
    for name in buckets.values():
        s3.create_bucket(Bucket=name)
    os.environ["AGENTCOMMS_BUCKET_RAW_INBOUND"] = buckets["raw_inbound"]
    os.environ["AGENTCOMMS_BUCKET_BODIES"] = buckets["bodies"]
    os.environ["AGENTCOMMS_BUCKET_ATTACHMENTS"] = buckets["attachments"]
    return buckets


@pytest.fixture
def sns_topic(aws_mock):
    sns = boto3.client("sns", region_name="us-east-1")
    resp = sns.create_topic(Name="agentcomms-events-test")
    return resp["TopicArn"]


@pytest.fixture
def kinesis_stream(aws_mock):
    kinesis = boto3.client("kinesis", region_name="us-east-1")
    kinesis.create_stream(StreamName="agentcomms-events-test", ShardCount=1)
    os.environ["AGENTCOMMS_EVENT_STREAM"] = "agentcomms-events-test"
    return "agentcomms-events-test"
```

If `tests/conftest.py` already exists with other fixtures, merge by appending rather than replacing.

- [ ] **Step 5: Run the test to verify it passes**

```bash
pytest tests/core/test_fixtures_smoke.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/core/test_fixtures_smoke.py
git commit -m "test(phase1): add agentcomms DynamoDB + SES + S3 + SNS + Kinesis moto fixtures"
```

---

## Task 4: Organization Pydantic model

**Files:**
- Create: `core/data/models.py` (will accumulate models through Tasks 4-10)
- Create: `tests/core/test_models.py` (will accumulate tests)

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_models.py`:

```python
import pytest
from datetime import datetime, timezone
from core.data.models import Organization, OrgPlan


def test_organization_create_with_defaults():
    org = Organization(org_id="org_01HABC", name="Acme")
    assert org.org_id == "org_01HABC"
    assert org.name == "Acme"
    assert org.plan == OrgPlan.FREE
    assert isinstance(org.created_at, datetime)
    assert org.created_at.tzinfo is timezone.utc
    assert org.quotas == {}
    assert org.settings == {}


def test_organization_roundtrip_via_dynamodb_item():
    org = Organization(org_id="org_01HABC", name="Acme", plan=OrgPlan.PRO)
    item = org.to_dynamodb_item()
    assert item["PK"] == "ORG#org_01HABC"
    assert item["SK"] == "META"
    assert item["name"] == "Acme"
    assert item["plan"] == "pro"
    restored = Organization.from_dynamodb_item(item)
    assert restored == org


def test_organization_plan_validation_rejects_unknown():
    with pytest.raises(ValueError):
        Organization(org_id="org_x", name="x", plan="unobtainium")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/core/test_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'core.data.models'`.

- [ ] **Step 3: Implement `Organization` in `core/data/models.py`**

```python
# core/data/models.py
"""
Pydantic v2 models for AgentComms DynamoDB single-table entities.

Every model implements:
  - to_dynamodb_item() → dict ready for boto3 put_item
  - from_dynamodb_item(item) → model
  - PK/SK keys are generated from the model (never hand-stitched at call sites)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class OrgPlan(str, Enum):
    FREE = "free"
    DEVELOPER = "developer"
    TEAM = "team"
    BUSINESS = "business"
    ENTERPRISE = "enterprise"
    # Legacy tiers kept to accept migrated data; new orgs should not use these.
    STARTER = "starter"
    PRO = "pro"


class Organization(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    org_id: str
    name: str
    plan: OrgPlan = OrgPlan.FREE
    quotas: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"ORG#{self.org_id}",
            "SK": "META",
            "entity": "organization",
            "org_id": self.org_id,
            "name": self.name,
            "plan": self.plan.value,
            "quotas": self.quotas,
            "settings": self.settings,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Organization:
        return cls(
            org_id=item["org_id"],
            name=item["name"],
            plan=OrgPlan(item["plan"]),
            quotas=item.get("quotas") or {},
            settings=item.get("settings") or {},
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/core/test_models.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/data/models.py tests/core/test_models.py
git commit -m "feat(phase1): Organization Pydantic model with DynamoDB roundtrip"
```

---

## Task 5: Agent Pydantic model

**Files:**
- Modify: `core/data/models.py` (append)
- Modify: `tests/core/test_models.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_models.py`:

```python
from core.data.models import Agent


def test_agent_create_with_defaults():
    agent = Agent(agent_id="agt_01HABC", org_id="org_01HDEF", name="InvoiceBot")
    assert agent.agent_id == "agt_01HABC"
    assert agent.org_id == "org_01HDEF"
    assert agent.name == "InvoiceBot"
    assert agent.metadata == {}
    assert agent.status == "active"


def test_agent_dynamodb_item_has_correct_keys():
    agent = Agent(agent_id="agt_01HABC", org_id="org_01HDEF", name="Bot")
    item = agent.to_dynamodb_item()
    assert item["PK"] == "ORG#org_01HDEF"
    assert item["SK"] == "AGT#agt_01HABC"


def test_agent_roundtrip():
    agent = Agent(
        agent_id="agt_01HABC",
        org_id="org_01HDEF",
        name="Bot",
        metadata={"team": "ops"},
    )
    restored = Agent.from_dynamodb_item(agent.to_dynamodb_item())
    assert restored == agent
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/core/test_models.py::test_agent_create_with_defaults -v
```

Expected: FAIL with `ImportError: cannot import name 'Agent'`.

- [ ] **Step 3: Implement `Agent` in `core/data/models.py`**

Append:

```python
class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    org_id: str
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "active"
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"ORG#{self.org_id}",
            "SK": f"AGT#{self.agent_id}",
            "entity": "agent",
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "name": self.name,
            "metadata": self.metadata,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Agent:
        return cls(
            agent_id=item["agent_id"],
            org_id=item["org_id"],
            name=item["name"],
            metadata=item.get("metadata") or {},
            status=item.get("status") or "active",
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/core/test_models.py -v
```

Expected: 6 passed (3 new + 3 from Task 4).

- [ ] **Step 5: Commit**

```bash
git add core/data/models.py tests/core/test_models.py
git commit -m "feat(phase1): Agent Pydantic model"
```

---

## Task 6: Channel Pydantic model

**Files:**
- Modify: `core/data/models.py` (append)
- Modify: `tests/core/test_models.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_models.py`:

```python
from core.data.models import Channel, ChannelMode, ChannelStatus, ChannelType


def test_channel_email_provision_defaults():
    ch = Channel(
        channel_id="chan_em_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
    )
    assert ch.channel == ChannelType.EMAIL
    assert ch.status == ChannelStatus.PROVISIONING


def test_channel_dynamodb_keys_and_gsi2():
    ch = Channel(
        channel_id="chan_em_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
    )
    item = ch.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01HDEF"
    assert item["SK"] == "CHAN#email#chan_em_01HABC"
    assert item["gsi2_pk"] == "ADDR#email#bot@agentcomms.dev"
    assert item["gsi2_sk"] == "CHAN#chan_em_01HABC"


def test_channel_without_address_index_value_has_no_gsi2():
    ch = Channel(
        channel_id="chan_sl_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.SLACK,
        mode=ChannelMode.BRIDGE,
        config={},
    )
    item = ch.to_dynamodb_item()
    assert "gsi2_pk" not in item


def test_channel_roundtrip():
    ch = Channel(
        channel_id="chan_em_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    )
    restored = Channel.from_dynamodb_item(ch.to_dynamodb_item())
    assert restored == ch
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/core/test_models.py::test_channel_email_provision_defaults -v
```

Expected: FAIL — `Channel` does not exist yet.

- [ ] **Step 3: Implement `Channel` in `core/data/models.py`**

Append:

```python
class ChannelType(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    SLACK = "slack"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    POSTAL = "postal"
    FAX = "fax"
    VOICE = "voice"


class ChannelMode(str, Enum):
    PROVISION = "provision"
    BRIDGE = "bridge"


class ChannelStatus(str, Enum):
    PROVISIONING = "provisioning"
    PENDING_OAUTH = "pending_oauth"
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    DISABLED = "disabled"
    FAILED = "failed"


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str
    agent_id: str
    org_id: str
    channel: ChannelType
    mode: ChannelMode
    config: dict[str, Any] = Field(default_factory=dict)
    status: ChannelStatus = ChannelStatus.PROVISIONING
    address_index_value: str | None = None  # projects to GSI2 for inbound routing
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "PK": f"AGT#{self.agent_id}",
            "SK": f"CHAN#{self.channel.value}#{self.channel_id}",
            "entity": "channel",
            "channel_id": self.channel_id,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "channel": self.channel.value,
            "mode": self.mode.value,
            "config": self.config,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
        if self.address_index_value:
            item["gsi2_pk"] = f"ADDR#{self.channel.value}#{self.address_index_value}"
            item["gsi2_sk"] = f"CHAN#{self.channel_id}"
            item["address_index_value"] = self.address_index_value
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Channel:
        return cls(
            channel_id=item["channel_id"],
            agent_id=item["agent_id"],
            org_id=item["org_id"],
            channel=ChannelType(item["channel"]),
            mode=ChannelMode(item["mode"]),
            config=item.get("config") or {},
            status=ChannelStatus(item.get("status", "provisioning")),
            address_index_value=item.get("address_index_value"),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_models.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add core/data/models.py tests/core/test_models.py
git commit -m "feat(phase1): Channel Pydantic model with GSI2 sparse projection"
```

---

## Task 7: UnifiedMessage Pydantic model

**Files:**
- Modify: `core/data/models.py` (append)
- Modify: `tests/core/test_models.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_models.py`:

```python
from core.data.models import (
    UnifiedMessage, MessageDirection, MessageStatus, Party
)


def _email_message():
    return UnifiedMessage(
        message_id="msg_01HABC",
        agent_id="agt_01HDEF",
        org_id="org_01HGHI",
        channel_id="chan_em_01HJKL",
        channel=ChannelType.EMAIL,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="alice@example.com", display_name="Alice"),
        to=[Party(address="bot@agentcomms.dev")],
        subject="hi",
        body_text="hello",
        is_dm=True,
        thread_key="thr_01HMNO",
        received_at=datetime(2026, 4, 17, tzinfo=timezone.utc),
        channel_native={"message_id_header": "<abc@x>"},
        external_id="<abc@x>",
    )


def test_unified_message_is_dm_projects_to_gsi3():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01HDEF"
    assert item["SK"].startswith("MSG#")
    assert item["gsi3_pk"] == "AGT_DM#agt_01HDEF"
    assert item["gsi3_sk"] == item["SK"]


def test_unified_message_not_dm_omits_gsi3():
    msg = _email_message()
    msg.is_dm = False
    item = msg.to_dynamodb_item()
    assert "gsi3_pk" not in item
    assert "gsi3_sk" not in item


def test_unified_message_populates_gsi4_channel():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["gsi4_pk"] == "CHAN#chan_em_01HJKL"


def test_unified_message_populates_gsi5_thread_when_present():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["gsi5_pk"] == "THR#thr_01HMNO"


def test_unified_message_populates_gsi6_external_id():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    assert item["gsi6_pk"] == "EXTID#email#<abc@x>"


def test_unified_message_sort_key_uses_timestamp_ms_then_id():
    msg = _email_message()
    item = msg.to_dynamodb_item()
    expected_ts_ms = int(msg.received_at.timestamp() * 1000)
    assert item["SK"] == f"MSG#{expected_ts_ms}#msg_01HABC"


def test_unified_message_roundtrip():
    msg = _email_message()
    restored = UnifiedMessage.from_dynamodb_item(msg.to_dynamodb_item())
    assert restored == msg
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_models.py::test_unified_message_is_dm_projects_to_gsi3 -v
```

Expected: FAIL — `UnifiedMessage` not defined.

- [ ] **Step 3: Implement in `core/data/models.py`**

Append:

```python
class MessageDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class MessageStatus(str, Enum):
    RECEIVED = "received"
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    BOUNCED = "bounced"
    FAILED = "failed"
    REJECTED = "rejected"


class Party(BaseModel):
    """One endpoint of a message (sender or recipient)."""
    model_config = ConfigDict(extra="forbid")

    address: str
    display_name: str | None = None
    platform_user_id: str | None = None


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attachment_id: str
    filename: str
    content_type: str
    size: int
    s3_key: str


class UnifiedMessage(BaseModel):
    """
    The normalized message shape for every channel. Written to DynamoDB under
    PK=AGT#{agent_id} SK=MSG#{timestamp_ms}#{message_id}.

    `is_dm=True` projects into GSI3 (unified inbox). Non-DM traffic is read via
    channel-native surfaces (GSI4).
    """
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    message_id: str
    agent_id: str
    org_id: str
    channel_id: str
    channel: ChannelType
    direction: MessageDirection
    status: MessageStatus
    from_: Party = Field(alias="from")
    to: list[Party] = Field(default_factory=list)
    subject: str | None = None
    body_text: str = ""
    body_html: str | None = None
    body_s3_key: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    thread_key: str | None = None
    is_dm: bool = False
    received_at: datetime = Field(default_factory=_now_utc)
    channel_native: dict[str, Any] = Field(default_factory=dict)
    external_id: str | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def _sort_key(self) -> str:
        ts_ms = int(self.received_at.timestamp() * 1000)
        return f"MSG#{ts_ms}#{self.message_id}"

    def to_dynamodb_item(self) -> dict[str, Any]:
        sk = self._sort_key()
        item: dict[str, Any] = {
            "PK": f"AGT#{self.agent_id}",
            "SK": sk,
            "entity": "message",
            "message_id": self.message_id,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "channel_id": self.channel_id,
            "channel": self.channel.value,
            "direction": self.direction.value,
            "status": self.status.value,
            "from": self.from_.model_dump(exclude_none=True),
            "to": [p.model_dump(exclude_none=True) for p in self.to],
            "subject": self.subject,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "body_s3_key": self.body_s3_key,
            "attachments": [a.model_dump() for a in self.attachments],
            "thread_key": self.thread_key,
            "is_dm": self.is_dm,
            "received_at": self.received_at.isoformat(),
            "channel_native": self.channel_native,
            "external_id": self.external_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # GSI4: channel-native listing
            "gsi4_pk": f"CHAN#{self.channel_id}",
            "gsi4_sk": sk,
        }
        # GSI3: sparse — only if is_dm=True
        if self.is_dm:
            item["gsi3_pk"] = f"AGT_DM#{self.agent_id}"
            item["gsi3_sk"] = sk
        # GSI5: threading
        if self.thread_key:
            item["gsi5_pk"] = f"THR#{self.thread_key}"
            item["gsi5_sk"] = sk
        # GSI6: external-id idempotency
        if self.external_id:
            item["gsi6_pk"] = f"EXTID#{self.channel.value}#{self.external_id}"
            item["gsi6_sk"] = f"MSG#{self.message_id}"
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> UnifiedMessage:
        return cls(
            message_id=item["message_id"],
            agent_id=item["agent_id"],
            org_id=item["org_id"],
            channel_id=item["channel_id"],
            channel=ChannelType(item["channel"]),
            direction=MessageDirection(item["direction"]),
            status=MessageStatus(item["status"]),
            **{"from": Party(**item["from"])},
            to=[Party(**p) for p in item.get("to") or []],
            subject=item.get("subject"),
            body_text=item.get("body_text") or "",
            body_html=item.get("body_html"),
            body_s3_key=item.get("body_s3_key"),
            attachments=[Attachment(**a) for a in item.get("attachments") or []],
            thread_key=item.get("thread_key"),
            is_dm=bool(item.get("is_dm", False)),
            received_at=datetime.fromisoformat(item["received_at"]),
            channel_native=item.get("channel_native") or {},
            external_id=item.get("external_id"),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_models.py -v
```

Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add core/data/models.py tests/core/test_models.py
git commit -m "feat(phase1): UnifiedMessage Pydantic model with GSI3/4/5/6 projections"
```

---

## Task 8: ApiKey + Thread + Draft + Webhook Pydantic models

**Files:**
- Modify: `core/data/models.py` (append)
- Modify: `tests/core/test_models.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/core/test_models.py`:

```python
from core.data.models import ApiKey, ApiKeyScope, Thread, Draft, Webhook


def test_api_key_projects_gsi1():
    key = ApiKey(
        key_id="key_01HABC",
        key_hash="sha256:deadbeef",
        org_id="org_01HDEF",
        scope=ApiKeyScope.AGENT,
        agent_id="agt_01HGHI",
        name="bot key",
    )
    item = key.to_dynamodb_item()
    assert item["PK"] == "ORG#org_01HDEF"
    assert item["SK"] == "APIKEY#sha256:deadbeef"
    assert item["gsi1_pk"] == "APIKEY#sha256:deadbeef"
    assert item["gsi1_sk"] == "ORG#org_01HDEF"


def test_api_key_roundtrip():
    key = ApiKey(key_id="k", key_hash="h", org_id="o", scope=ApiKeyScope.ORG, name="n")
    assert ApiKey.from_dynamodb_item(key.to_dynamodb_item()) == key


def test_thread_keys():
    t = Thread(
        thread_key="thr_01H",
        agent_id="agt_01H",
        org_id="org_01H",
        channel=ChannelType.EMAIL,
        native_thread_id="<root@x>",
        subject="Re: ping",
    )
    item = t.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01H"
    assert item["SK"] == "THR#email#<root@x>"


def test_draft_keys():
    d = Draft(
        draft_id="drf_01H",
        agent_id="agt_01H",
        org_id="org_01H",
        channel=ChannelType.EMAIL,
        to=[Party(address="x@y.z")],
        body_text="hi",
    )
    item = d.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01H"
    assert item["SK"] == "DRF#email#drf_01H"


def test_webhook_keys_and_channel_filter():
    w = Webhook(
        webhook_id="whk_01H",
        agent_id="agt_01H",
        org_id="org_01H",
        url="https://example.com/hook",
        events=["message.received"],
        channels=["email", "slack"],
        secret="sek",
    )
    item = w.to_dynamodb_item()
    assert item["PK"] == "AGT#agt_01H"
    assert item["SK"] == "WHK#whk_01H"
    assert item["channels"] == ["email", "slack"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_models.py::test_api_key_projects_gsi1 -v
```

Expected: FAIL (imports missing).

- [ ] **Step 3: Implement in `core/data/models.py`**

Append:

```python
class ApiKeyScope(str, Enum):
    ORG = "org"
    AGENT = "agent"
    CHANNEL = "channel"


class ApiKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str
    key_hash: str  # sha256 hex; plaintext shown once at creation
    org_id: str
    scope: ApiKeyScope
    name: str
    agent_id: str | None = None
    channel_id: str | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    last_used_at: datetime | None = None

    def to_dynamodb_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "PK": f"ORG#{self.org_id}",
            "SK": f"APIKEY#{self.key_hash}",
            "entity": "api_key",
            "key_id": self.key_id,
            "key_hash": self.key_hash,
            "org_id": self.org_id,
            "scope": self.scope.value,
            "name": self.name,
            "agent_id": self.agent_id,
            "channel_id": self.channel_id,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "gsi1_pk": f"APIKEY#{self.key_hash}",
            "gsi1_sk": f"ORG#{self.org_id}",
        }
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> ApiKey:
        return cls(
            key_id=item["key_id"],
            key_hash=item["key_hash"],
            org_id=item["org_id"],
            scope=ApiKeyScope(item["scope"]),
            name=item["name"],
            agent_id=item.get("agent_id"),
            channel_id=item.get("channel_id"),
            created_at=datetime.fromisoformat(item["created_at"]),
            last_used_at=datetime.fromisoformat(item["last_used_at"]) if item.get("last_used_at") else None,
        )


class Thread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_key: str
    agent_id: str
    org_id: str
    channel: ChannelType
    native_thread_id: str
    subject: str | None = None
    last_message_at: datetime | None = None
    message_count: int = 0
    participants: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"AGT#{self.agent_id}",
            "SK": f"THR#{self.channel.value}#{self.native_thread_id}",
            "entity": "thread",
            "thread_key": self.thread_key,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "channel": self.channel.value,
            "native_thread_id": self.native_thread_id,
            "subject": self.subject,
            "last_message_at": self.last_message_at.isoformat() if self.last_message_at else None,
            "message_count": self.message_count,
            "participants": self.participants,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Thread:
        return cls(
            thread_key=item["thread_key"],
            agent_id=item["agent_id"],
            org_id=item["org_id"],
            channel=ChannelType(item["channel"]),
            native_thread_id=item["native_thread_id"],
            subject=item.get("subject"),
            last_message_at=datetime.fromisoformat(item["last_message_at"]) if item.get("last_message_at") else None,
            message_count=int(item.get("message_count") or 0),
            participants=item.get("participants") or [],
            created_at=datetime.fromisoformat(item["created_at"]),
        )


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_id: str
    agent_id: str
    org_id: str
    channel: ChannelType
    to: list[Party] = Field(default_factory=list)
    subject: str | None = None
    body_text: str = ""
    body_html: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"AGT#{self.agent_id}",
            "SK": f"DRF#{self.channel.value}#{self.draft_id}",
            "entity": "draft",
            "draft_id": self.draft_id,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "channel": self.channel.value,
            "to": [p.model_dump(exclude_none=True) for p in self.to],
            "subject": self.subject,
            "body_text": self.body_text,
            "body_html": self.body_html,
            "attachments": [a.model_dump() for a in self.attachments],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Draft:
        return cls(
            draft_id=item["draft_id"],
            agent_id=item["agent_id"],
            org_id=item["org_id"],
            channel=ChannelType(item["channel"]),
            to=[Party(**p) for p in item.get("to") or []],
            subject=item.get("subject"),
            body_text=item.get("body_text") or "",
            body_html=item.get("body_html"),
            attachments=[Attachment(**a) for a in item.get("attachments") or []],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )


class Webhook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    webhook_id: str
    agent_id: str
    org_id: str
    url: str
    events: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=lambda: ["*"])
    secret: str
    status: str = "active"
    created_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"AGT#{self.agent_id}",
            "SK": f"WHK#{self.webhook_id}",
            "entity": "webhook",
            "webhook_id": self.webhook_id,
            "agent_id": self.agent_id,
            "org_id": self.org_id,
            "url": self.url,
            "events": self.events,
            "channels": self.channels,
            "secret": self.secret,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Webhook:
        return cls(
            webhook_id=item["webhook_id"],
            agent_id=item["agent_id"],
            org_id=item["org_id"],
            url=item["url"],
            events=item.get("events") or [],
            channels=item.get("channels") or ["*"],
            secret=item["secret"],
            status=item.get("status") or "active",
            created_at=datetime.fromisoformat(item["created_at"]),
        )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_models.py -v
```

Expected: 22 passed.

- [ ] **Step 5: Commit**

```bash
git add core/data/models.py tests/core/test_models.py
git commit -m "feat(phase1): ApiKey, Thread, Draft, Webhook Pydantic models"
```

---

## Task 9: ULID generator wrapper

**Files:**
- Create: `core/data/ulid_.py`
- Create: `tests/core/test_ulid.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_ulid.py
import re
from core.data.ulid_ import new_id


def test_new_id_agent():
    v = new_id("agt")
    assert re.match(r"^agt_[0-9A-HJKMNP-TV-Z]{26}$", v), v


def test_new_id_channel_with_suffix():
    v = new_id("chan", suffix="em")
    assert v.startswith("chan_em_")


def test_new_id_monotonic_when_called_rapidly():
    vals = sorted(new_id("msg") for _ in range(100))
    # ULIDs at the same ms are lex-ordered by the random part, so sorted order
    # should match insertion order within a single ms window. We test
    # uniqueness here; full monotonic ordering is a nice-to-have, not a
    # requirement.
    assert len(set(vals)) == 100
```

- [ ] **Step 2: Run test, expect fail**

```bash
pytest tests/core/test_ulid.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/data/ulid_.py`**

```python
# core/data/ulid_.py
"""Thin wrapper around python-ulid with project ID-prefix conventions."""
from __future__ import annotations

from ulid import ULID


def new_id(prefix: str, suffix: str | None = None) -> str:
    """Return a new prefixed ULID: '{prefix}_{suffix}_{ULID26}' or '{prefix}_{ULID26}'."""
    ulid_str = str(ULID())
    if suffix:
        return f"{prefix}_{suffix}_{ulid_str}"
    return f"{prefix}_{ulid_str}"
```

If the current repo uses a different ULID library (check `lambdas/shared/ulid.py`), align to it:

```bash
cat lambdas/shared/ulid.py
```

If a different implementation exists, reuse it (import from there) rather than taking a new dependency.

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_ulid.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/data/ulid_.py tests/core/test_ulid.py
git commit -m "feat(phase1): ULID generator with typed prefixes (agt_, chan_, msg_, etc.)"
```

---

## Task 10: DynamoDB single-table repository — put and get for Org + Agent + Channel

**Files:**
- Create: `core/data/repo.py`
- Create: `tests/core/test_repo.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_repo.py
import pytest
from core.data.models import (
    Organization, Agent, Channel, ChannelType, ChannelMode, OrgPlan
)
from core.data.repo import Repo


@pytest.fixture
def repo(agentcomms_table):
    return Repo(table=agentcomms_table)


def test_put_and_get_organization(repo):
    org = Organization(org_id="org_X", name="Acme", plan=OrgPlan.DEVELOPER)
    repo.put_organization(org)
    got = repo.get_organization("org_X")
    assert got == org


def test_get_organization_missing_returns_none(repo):
    assert repo.get_organization("org_nope") is None


def test_put_and_get_agent(repo):
    agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
    repo.put_agent(agent)
    got = repo.get_agent(org_id="org_X", agent_id="agt_1")
    assert got == agent


def test_list_agents_in_org(repo):
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="a"))
    repo.put_agent(Agent(agent_id="agt_2", org_id="org_X", name="b"))
    repo.put_agent(Agent(agent_id="agt_3", org_id="org_Y", name="c"))
    got = repo.list_agents(org_id="org_X")
    assert {a.agent_id for a in got} == {"agt_1", "agt_2"}


def test_put_and_get_channel(repo):
    ch = Channel(
        channel_id="chan_em_1",
        agent_id="agt_1",
        org_id="org_X",
        channel=ChannelType.EMAIL,
        mode=ChannelMode.PROVISION,
        config={"address": "bot@x.com"},
        address_index_value="bot@x.com",
    )
    repo.put_channel(ch)
    got = repo.get_channel(agent_id="agt_1", channel="email", channel_id="chan_em_1")
    assert got == ch


def test_list_channels_for_agent(repo):
    for cid in ["chan_em_1", "chan_em_2"]:
        repo.put_channel(Channel(
            channel_id=cid, agent_id="agt_1", org_id="org_X",
            channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION, config={},
        ))
    repo.put_channel(Channel(
        channel_id="chan_sm_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.SMS, mode=ChannelMode.PROVISION, config={},
    ))
    got = repo.list_channels(agent_id="agt_1")
    assert len(got) == 3
    assert {c.channel_id for c in got} == {"chan_em_1", "chan_em_2", "chan_sm_1"}


def test_lookup_channel_by_address(repo):
    ch = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@x.com"}, address_index_value="bot@x.com",
    )
    repo.put_channel(ch)
    got = repo.lookup_channel_by_address(channel="email", address="bot@x.com")
    assert got == ch


def test_lookup_channel_by_address_missing(repo):
    assert repo.lookup_channel_by_address(channel="email", address="nope@x.com") is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_repo.py -v
```

Expected: FAIL — `Repo` module not found.

- [ ] **Step 3: Implement `core/data/repo.py`**

```python
# core/data/repo.py
"""
Single-table repository for AgentComms DynamoDB.

Encapsulates all DynamoDB access so handlers never build PK/SK strings or touch
boto3 directly. Use this in Lambda handlers by instantiating with a real
DynamoDB Table; use in tests with a moto-backed Table fixture.
"""
from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Key

from core.data.models import (
    Agent, ApiKey, Channel, Draft, Organization, Thread, UnifiedMessage,
    Webhook,
)


class Repo:
    def __init__(self, table):
        self.table = table

    # ─── Organizations ──────────────────────────────────────────────
    def put_organization(self, org: Organization) -> None:
        self.table.put_item(Item=org.to_dynamodb_item())

    def get_organization(self, org_id: str) -> Organization | None:
        resp = self.table.get_item(Key={"PK": f"ORG#{org_id}", "SK": "META"})
        item = resp.get("Item")
        return Organization.from_dynamodb_item(item) if item else None

    # ─── Agents ──────────────────────────────────────────────────────
    def put_agent(self, agent: Agent) -> None:
        self.table.put_item(Item=agent.to_dynamodb_item())

    def get_agent(self, *, org_id: str, agent_id: str) -> Agent | None:
        resp = self.table.get_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"AGT#{agent_id}"}
        )
        item = resp.get("Item")
        return Agent.from_dynamodb_item(item) if item else None

    def list_agents(self, *, org_id: str, limit: int = 100) -> list[Agent]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"ORG#{org_id}")
                & Key("SK").begins_with("AGT#"),
            Limit=limit,
        )
        return [Agent.from_dynamodb_item(i) for i in resp.get("Items", [])]

    # ─── Channels ────────────────────────────────────────────────────
    def put_channel(self, channel: Channel) -> None:
        self.table.put_item(Item=channel.to_dynamodb_item())

    def get_channel(self, *, agent_id: str, channel: str, channel_id: str) -> Channel | None:
        resp = self.table.get_item(
            Key={"PK": f"AGT#{agent_id}", "SK": f"CHAN#{channel}#{channel_id}"}
        )
        item = resp.get("Item")
        return Channel.from_dynamodb_item(item) if item else None

    def list_channels(self, *, agent_id: str) -> list[Channel]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"AGT#{agent_id}")
                & Key("SK").begins_with("CHAN#"),
        )
        return [Channel.from_dynamodb_item(i) for i in resp.get("Items", [])]

    def lookup_channel_by_address(self, *, channel: str, address: str) -> Channel | None:
        """GSI2 lookup: resolve a channel address (email, phone, slack user) → Channel.
        This is the hot path for inbound routing."""
        resp = self.table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("gsi2_pk").eq(f"ADDR#{channel}#{address}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        # GSI2 SK is CHAN#{channel_id}; need the full item, so re-fetch by PK/SK
        channel_id = items[0]["channel_id"]
        agent_id = items[0]["agent_id"]
        return self.get_channel(agent_id=agent_id, channel=channel, channel_id=channel_id)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_repo.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add core/data/repo.py tests/core/test_repo.py
git commit -m "feat(phase1): Repo put/get/list for Org, Agent, Channel + GSI2 address lookup"
```

---

## Task 11: Repository — Messages put + unified inbox query + external-id idempotency

**Files:**
- Modify: `core/data/repo.py` (append methods)
- Modify: `tests/core/test_repo.py` (append tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/core/test_repo.py`:

```python
from datetime import datetime, timedelta, timezone
from core.data.models import UnifiedMessage, MessageDirection, MessageStatus, Party


def _msg(agent_id="agt_1", msg_id="msg_1", is_dm=True, channel_id="chan_em_1",
         received_at=None, external_id=None, channel="email"):
    return UnifiedMessage(
        message_id=msg_id,
        agent_id=agent_id,
        org_id="org_X",
        channel_id=channel_id,
        channel=channel,
        direction=MessageDirection.INBOUND,
        status=MessageStatus.RECEIVED,
        from_=Party(address="alice@x.com"),
        to=[Party(address="bot@agentcomms.dev")],
        body_text="hi",
        is_dm=is_dm,
        received_at=received_at or datetime(2026, 4, 17, 12, tzinfo=timezone.utc),
        external_id=external_id,
    )


def test_put_message_and_query_unified_inbox(repo):
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    repo.put_message(_msg(msg_id="msg_1", received_at=t0))
    repo.put_message(_msg(msg_id="msg_2", received_at=t0 + timedelta(minutes=1)))
    repo.put_message(_msg(msg_id="msg_3", is_dm=False, received_at=t0 + timedelta(minutes=2)))

    inbox = repo.list_unified_inbox(agent_id="agt_1")
    # Only the two is_dm=True messages, newest first
    ids = [m.message_id for m in inbox]
    assert ids == ["msg_2", "msg_1"]


def test_unified_inbox_since_filter(repo):
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    repo.put_message(_msg(msg_id="msg_old", received_at=t0))
    repo.put_message(_msg(msg_id="msg_new", received_at=t0 + timedelta(hours=1)))
    inbox = repo.list_unified_inbox(agent_id="agt_1", since=t0 + timedelta(minutes=30))
    assert [m.message_id for m in inbox] == ["msg_new"]


def test_list_channel_messages(repo):
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    repo.put_message(_msg(msg_id="m_em", channel_id="chan_em", received_at=t0))
    repo.put_message(_msg(msg_id="m_sl", channel_id="chan_sl", received_at=t0 + timedelta(minutes=1)))
    got = repo.list_channel_messages(channel_id="chan_em")
    assert [m.message_id for m in got] == ["m_em"]


def test_lookup_message_by_external_id_returns_existing(repo):
    msg = _msg(msg_id="msg_ext", external_id="<abc@x>")
    repo.put_message(msg)
    got = repo.lookup_message_by_external_id(channel="email", external_id="<abc@x>")
    assert got is not None
    assert got.message_id == "msg_ext"


def test_lookup_message_by_external_id_missing(repo):
    assert repo.lookup_message_by_external_id(channel="email", external_id="<nope@x>") is None


def test_get_message_by_id(repo):
    msg = _msg(msg_id="msg_42")
    repo.put_message(msg)
    got = repo.get_message(agent_id="agt_1", received_at_ms=int(msg.received_at.timestamp() * 1000), message_id="msg_42")
    assert got == msg
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_repo.py -v -k "message or inbox or channel_messages or external"
```

Expected: FAIL — methods not found.

- [ ] **Step 3: Implement in `core/data/repo.py`**

Append to the `Repo` class:

```python
    # ─── Messages ────────────────────────────────────────────────────
    def put_message(self, msg: UnifiedMessage) -> None:
        self.table.put_item(Item=msg.to_dynamodb_item())

    def get_message(self, *, agent_id: str, received_at_ms: int, message_id: str) -> UnifiedMessage | None:
        resp = self.table.get_item(
            Key={
                "PK": f"AGT#{agent_id}",
                "SK": f"MSG#{received_at_ms}#{message_id}",
            }
        )
        item = resp.get("Item")
        return UnifiedMessage.from_dynamodb_item(item) if item else None

    def list_unified_inbox(
        self, *, agent_id: str, since=None, until=None,
        channel_filter: list[str] | None = None, limit: int = 50,
    ) -> list[UnifiedMessage]:
        """
        Query GSI3 (sparse) for all is_dm=True messages, newest first.
        Optional filters:
          - since / until: datetimes
          - channel_filter: list of channel names; post-query filter
        """
        key_cond = Key("gsi3_pk").eq(f"AGT_DM#{agent_id}")
        if since and until:
            since_ms = int(since.timestamp() * 1000)
            until_ms = int(until.timestamp() * 1000)
            key_cond = key_cond & Key("gsi3_sk").between(f"MSG#{since_ms}", f"MSG#{until_ms}z")
        elif since:
            since_ms = int(since.timestamp() * 1000)
            key_cond = key_cond & Key("gsi3_sk").gte(f"MSG#{since_ms}")
        resp = self.table.query(
            IndexName="GSI3",
            KeyConditionExpression=key_cond,
            ScanIndexForward=False,  # newest first
            Limit=limit * 3 if channel_filter else limit,  # over-fetch if filtering
        )
        msgs = [UnifiedMessage.from_dynamodb_item(i) for i in resp.get("Items", [])]
        if channel_filter:
            msgs = [m for m in msgs if m.channel.value in channel_filter]
        return msgs[:limit]

    def list_channel_messages(
        self, *, channel_id: str, limit: int = 50,
    ) -> list[UnifiedMessage]:
        """GSI4 — list ALL messages (DM or not) on a single channel. Use for
        channel-native sub-surfaces like Slack workspace channel listings."""
        resp = self.table.query(
            IndexName="GSI4",
            KeyConditionExpression=Key("gsi4_pk").eq(f"CHAN#{channel_id}"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [UnifiedMessage.from_dynamodb_item(i) for i in resp.get("Items", [])]

    def lookup_message_by_external_id(
        self, *, channel: str, external_id: str,
    ) -> UnifiedMessage | None:
        """GSI6 — idempotency lookup. Used by adapters to dedupe inbound events."""
        resp = self.table.query(
            IndexName="GSI6",
            KeyConditionExpression=Key("gsi6_pk").eq(f"EXTID#{channel}#{external_id}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        item = items[0]
        # GSI6 item is the message itself (projection=ALL), return directly
        return UnifiedMessage.from_dynamodb_item(item)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_repo.py -v
```

Expected: 14 passed (8 old + 6 new).

- [ ] **Step 5: Commit**

```bash
git add core/data/repo.py tests/core/test_repo.py
git commit -m "feat(phase1): Repo message put + unified inbox (GSI3) + channel listing (GSI4) + dedup (GSI6)"
```

---

## Task 12: `ChannelAdapter` ABC + support types

**Files:**
- Create: `core/adapters/base.py`
- Create: `tests/core/test_adapter_base.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_adapter_base.py
import pytest
from core.adapters.base import (
    ChannelAdapter, IngestPayload, OutboundMessage, HealthStatus,
    ProvisionResult, BridgeStart,
)


class _StubAdapter(ChannelAdapter):
    channel_name = "stub"
    supports_modes = ["provision"]

    def provision(self, *, agent, config):
        return ProvisionResult(status="active", channel_id="chan_stub_1", details={})

    def teardown(self, *, channel):
        pass

    def health_check(self, *, channel):
        return HealthStatus(ok=True, last_success_at="2026-01-01T00:00:00Z")

    def ingest(self, *, payload):
        return None

    def send(self, *, channel, message):
        from core.adapters.base import SendResult
        return SendResult(channel_native_id="x", status="sent")


def test_abstract_methods_required():
    """Instantiating ChannelAdapter without implementing abstract methods raises."""
    class Broken(ChannelAdapter):
        channel_name = "broken"
        supports_modes = []
    with pytest.raises(TypeError):
        Broken()


def test_stub_adapter_instantiates():
    a = _StubAdapter()
    assert a.channel_name == "stub"


def test_bridge_methods_default_raise_not_implemented():
    a = _StubAdapter()
    with pytest.raises(NotImplementedError):
        a.bridge_start(agent=None, config={})
    with pytest.raises(NotImplementedError):
        a.bridge_complete(channel=None, callback_params={})


def test_list_native_containers_defaults_empty():
    a = _StubAdapter()
    assert a.list_native_containers(channel=None) == []


def test_ingest_payload_construction():
    p = IngestPayload(source="sns", headers={"a": "b"}, body=b"x", path_params={})
    assert p.source == "sns"


def test_outbound_message_construction():
    o = OutboundMessage(to="x@y.com", body_text="hi")
    assert o.to == "x@y.com"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_adapter_base.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/adapters/base.py`**

```python
# core/adapters/base.py
"""
ChannelAdapter contract and support types.

Every channel plugin implements ChannelAdapter. The hub core interacts with
adapters only through this interface. Adapters never touch DynamoDB or Kinesis
directly — they return normalized data and the core does persistence.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from core.data.models import Agent, Channel, UnifiedMessage


class IngestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    source: str               # "sns" | "api_gateway" | "s3_event"
    headers: dict[str, str] = {}
    body: bytes | dict[str, Any]
    path_params: dict[str, str] = {}


class OutboundMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str | dict[str, Any]
    body_text: str
    body_html: str | None = None
    subject: str | None = None
    attachments: list[dict[str, Any]] = []
    thread_key: str | None = None
    channel_native_overrides: dict[str, Any] = {}


class SendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel_native_id: str
    status: str                 # "sent" | "queued" | "failed"
    error: str | None = None


class NativeContainer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    type: str
    metadata: dict[str, Any] = {}


class ProvisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    channel_id: str
    details: dict[str, Any]


class BridgeStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    oauth_url: str
    state: str
    instructions: str = ""


class BridgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    channel_id: str
    details: dict[str, Any]


class HealthStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    last_success_at: str
    error: str | None = None


class ChannelAdapter(ABC):
    """Every channel adapter implements this."""

    channel_name: str
    supports_modes: list[Literal["provision", "bridge"]]

    # ── Lifecycle ─────────────────────────────────────────────────
    @abstractmethod
    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult: ...

    def bridge_start(self, *, agent: Agent, config: dict[str, Any]) -> BridgeStart:
        raise NotImplementedError(f"{self.channel_name} does not support bridge mode")

    def bridge_complete(
        self, *, channel: Channel, callback_params: dict[str, Any]
    ) -> BridgeResult:
        raise NotImplementedError(f"{self.channel_name} does not support bridge mode")

    @abstractmethod
    def teardown(self, *, channel: Channel) -> None: ...

    @abstractmethod
    def health_check(self, *, channel: Channel) -> HealthStatus: ...

    # ── Messaging ─────────────────────────────────────────────────
    @abstractmethod
    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None: ...

    @abstractmethod
    def send(
        self, *, channel: Channel, message: OutboundMessage
    ) -> SendResult: ...

    # ── Native sub-surfaces (optional) ────────────────────────────
    def list_native_containers(self, *, channel: Channel) -> list[NativeContainer]:
        return []

    def list_native_messages(
        self, *, channel: Channel, container_id: str, **filters: Any
    ) -> list[UnifiedMessage]:
        return []

    def send_to_native_target(
        self, *, channel: Channel, target: dict[str, Any], message: OutboundMessage,
    ) -> SendResult:
        return self.send(channel=channel, message=message)

    # ── CDK wiring (deploy time) ──────────────────────────────────
    def cdk_wiring(self, *, stack: Any, context: Any) -> None:
        """Override in subclasses that need CDK-level AWS resources."""
        return None
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_adapter_base.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add core/adapters/base.py tests/core/test_adapter_base.py
git commit -m "feat(phase1): ChannelAdapter ABC + IngestPayload/OutboundMessage/SendResult types"
```

---

## Task 13: Adapter registry (scans `adapters/*/manifest.toml`)

**Files:**
- Create: `core/adapters/registry.py`
- Create: `tests/core/test_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_registry.py
import pytest
from pathlib import Path
from core.adapters.registry import load_registry, AdapterEntry


def test_load_registry_scans_manifests(tmp_path, monkeypatch):
    # Create a fake adapters directory
    adapters_dir = tmp_path / "adapters"
    fake_adapter_dir = adapters_dir / "fakechan"
    fake_adapter_dir.mkdir(parents=True)
    (fake_adapter_dir / "__init__.py").write_text("")
    (fake_adapter_dir / "manifest.toml").write_text("""
[adapter]
channel = "fakechan"
class = "adapters.fakechan.adapter:FakeAdapter"
modes = ["provision"]
min_hub_version = "0.1"

[webhook_routes]

[ssm_secrets]
""")
    (fake_adapter_dir / "adapter.py").write_text("""
from core.adapters.base import ChannelAdapter, ProvisionResult, HealthStatus

class FakeAdapter(ChannelAdapter):
    channel_name = "fakechan"
    supports_modes = ["provision"]
    def provision(self, *, agent, config):
        return ProvisionResult(status="active", channel_id="chan_fake_1", details={})
    def teardown(self, *, channel): pass
    def health_check(self, *, channel): return HealthStatus(ok=True, last_success_at="x")
    def ingest(self, *, payload): return None
    def send(self, *, channel, message):
        from core.adapters.base import SendResult
        return SendResult(channel_native_id="x", status="sent")
""")

    monkeypatch.syspath_prepend(str(tmp_path))
    registry = load_registry(adapters_root=adapters_dir)
    assert "fakechan" in registry
    entry = registry["fakechan"]
    assert isinstance(entry, AdapterEntry)
    assert entry.channel == "fakechan"
    assert entry.modes == ["provision"]
    assert entry.adapter.channel_name == "fakechan"


def test_load_registry_skips_missing_manifest(tmp_path):
    adapters_dir = tmp_path / "adapters"
    adapters_dir.mkdir()
    (adapters_dir / "notes.txt").write_text("not an adapter")
    registry = load_registry(adapters_root=adapters_dir)
    assert registry == {}


def test_adapter_entry_webhook_routes(tmp_path, monkeypatch):
    adapters_dir = tmp_path / "adapters"
    fake = adapters_dir / "hooked"
    fake.mkdir(parents=True)
    (fake / "__init__.py").write_text("")
    (fake / "manifest.toml").write_text("""
[adapter]
channel = "hooked"
class = "adapters.hooked.adapter:HookedAdapter"
modes = ["provision"]

[webhook_routes]
inbound = { path = "/webhooks/hooked", method = "POST" }
""")
    (fake / "adapter.py").write_text("""
from core.adapters.base import ChannelAdapter, ProvisionResult, HealthStatus, SendResult
class HookedAdapter(ChannelAdapter):
    channel_name = "hooked"
    supports_modes = ["provision"]
    def provision(self, *, agent, config): return ProvisionResult(status="active", channel_id="x", details={})
    def teardown(self, *, channel): pass
    def health_check(self, *, channel): return HealthStatus(ok=True, last_success_at="x")
    def ingest(self, *, payload): return None
    def send(self, *, channel, message): return SendResult(channel_native_id="x", status="sent")
""")
    monkeypatch.syspath_prepend(str(tmp_path))
    registry = load_registry(adapters_root=adapters_dir)
    assert registry["hooked"].webhook_routes == {
        "inbound": {"path": "/webhooks/hooked", "method": "POST"}
    }
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_registry.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/adapters/registry.py`**

```python
# core/adapters/registry.py
"""
Discovers channel adapters in two ways:
  1. In-repo: scans `adapters/*/manifest.toml` at the supplied root.
  2. Third-party: scans Python entry points in the `agentcomms.adapters` group.

Returns a dict keyed by channel name.
"""
from __future__ import annotations

import importlib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.adapters.base import ChannelAdapter


@dataclass
class AdapterEntry:
    channel: str
    adapter: ChannelAdapter
    modes: list[str]
    min_hub_version: str = "0.1"
    webhook_routes: dict[str, dict[str, str]] = field(default_factory=dict)
    ssm_secrets: dict[str, str] = field(default_factory=dict)
    cdk_stack_ref: str | None = None


def _load_class(dotted: str) -> type:
    module_path, class_name = dotted.split(":")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _entry_from_manifest(manifest_path: Path) -> AdapterEntry | None:
    with manifest_path.open("rb") as f:
        manifest = tomllib.load(f)
    adapter_cfg = manifest.get("adapter")
    if not adapter_cfg:
        return None
    cls = _load_class(adapter_cfg["class"])
    instance = cls()
    return AdapterEntry(
        channel=adapter_cfg["channel"],
        adapter=instance,
        modes=adapter_cfg.get("modes", []),
        min_hub_version=adapter_cfg.get("min_hub_version", "0.1"),
        webhook_routes=manifest.get("webhook_routes", {}),
        ssm_secrets=manifest.get("ssm_secrets", {}),
        cdk_stack_ref=adapter_cfg.get("cdk_stack"),
    )


def load_registry(
    adapters_root: Path | None = None,
    *,
    load_entry_points: bool = True,
) -> dict[str, AdapterEntry]:
    if adapters_root is None:
        adapters_root = Path(__file__).resolve().parents[2] / "adapters"
    registry: dict[str, AdapterEntry] = {}
    if adapters_root.exists():
        for child in sorted(adapters_root.iterdir()):
            manifest = child / "manifest.toml"
            if not manifest.is_file():
                continue
            entry = _entry_from_manifest(manifest)
            if entry is not None:
                registry[entry.channel] = entry

    if load_entry_points:
        try:
            from importlib.metadata import entry_points
            eps = entry_points(group="agentcomms.adapters")
        except Exception:
            eps = []
        for ep in eps:
            cls = ep.load()
            instance = cls()
            if instance.channel_name not in registry:
                registry[instance.channel_name] = AdapterEntry(
                    channel=instance.channel_name,
                    adapter=instance,
                    modes=list(instance.supports_modes),
                )

    return registry
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_registry.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add core/adapters/registry.py tests/core/test_registry.py
git commit -m "feat(phase1): adapter registry — scans adapters/*/manifest.toml + entry_points"
```

---

## Task 14: Address-format router (`core/router/address.py`)

**Files:**
- Create: `core/router/address.py`
- Create: `tests/core/test_router.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_router.py
import pytest
from core.router.address import infer_channel, AmbiguousAddressError


@pytest.mark.parametrize("address,expected", [
    ("alice@example.com", "email"),
    ("+15551234567", "sms"),
    ("slack:T123:U456", "slack"),
    ("discord:123456789:987654321", "discord"),
    ("telegram:chat:123456", "telegram"),
    ("push:apns:arn:aws:sns:us-east-1:123:app/APNS/x/endpoint/y", "push"),
    ("push:fcm:arn:aws:sns:us-east-1:123:app/FCM/x/endpoint/y", "push"),
])
def test_infer_channel_unambiguous(address, expected):
    assert infer_channel(address) == expected


def test_infer_channel_invalid_raises():
    with pytest.raises(AmbiguousAddressError):
        infer_channel("not-really-anything")


def test_infer_channel_sms_rejects_non_e164():
    with pytest.raises(AmbiguousAddressError):
        infer_channel("5551234567")  # missing '+' prefix


def test_infer_channel_email_rejects_malformed():
    with pytest.raises(AmbiguousAddressError):
        infer_channel("not@valid@address")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/core/test_router.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/router/address.py`**

```python
# core/router/address.py
"""
Address-format → channel inference.

Used on the outbound hot path: POST /v1/agents/{id}/messages {to: "..."}
Address prefixes disambiguate chat platforms; email and SMS use format regexes.
"""
from __future__ import annotations

import re


class AmbiguousAddressError(ValueError):
    pass


_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+$"
)
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

_PREFIXED_CHANNELS = {
    "slack:": "slack",
    "discord:": "discord",
    "telegram:": "telegram",
    "push:apns:": "push",
    "push:fcm:": "push",
}


def infer_channel(address: str) -> str:
    if not isinstance(address, str) or not address:
        raise AmbiguousAddressError(f"empty or non-string address: {address!r}")
    for prefix, channel in _PREFIXED_CHANNELS.items():
        if address.startswith(prefix):
            return channel
    if _EMAIL_RE.match(address):
        return "email"
    if _E164_RE.match(address):
        return "sms"
    raise AmbiguousAddressError(
        f"cannot infer channel from address: {address!r}. "
        f"Supported formats: email (user@domain.tld), sms (+15551234567), "
        f"slack:TEAM:USER, discord:GUILD:USER, telegram:chat:ID, "
        f"push:apns:ARN, push:fcm:ARN."
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_router.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add core/router/address.py tests/core/test_router.py
git commit -m "feat(phase1): address-format router (email/sms/slack/discord/telegram/push)"
```

---

## Task 15: CDK data stack (`agentcomms-data-stack.ts`)

**Files:**
- Create: `cdk/lib/stacks/agentcomms-data-stack.ts`
- Create: `cdk/test/agentcomms-data-stack.test.ts`
- Modify: `cdk/bin/app.ts` (add stack instantiation)

- [ ] **Step 1: Write failing CDK assertion test**

```typescript
// cdk/test/agentcomms-data-stack.test.ts
import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { AgentCommsDataStack } from '../lib/stacks/agentcomms-data-stack';

describe('AgentCommsDataStack', () => {
  const app = new App();
  const stack = new AgentCommsDataStack(app, 'Test');
  const template = Template.fromStack(stack);

  test('creates DynamoDB table named agentcomms with PAY_PER_REQUEST', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      TableName: 'agentcomms',
      BillingMode: 'PAY_PER_REQUEST',
    });
  });

  test('has 7 GSIs named GSI1..GSI7', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      GlobalSecondaryIndexes: expect.arrayContaining([
        expect.objectContaining({ IndexName: 'GSI1' }),
        expect.objectContaining({ IndexName: 'GSI7' }),
      ]),
    });
    const tables = template.findResources('AWS::DynamoDB::Table');
    const table = Object.values(tables)[0] as any;
    expect(table.Properties.GlobalSecondaryIndexes).toHaveLength(7);
  });

  test('creates 3 S3 buckets with agentcomms prefix', () => {
    template.resourceCountIs('AWS::S3::Bucket', 3);
    template.hasResourceProperties('AWS::S3::Bucket', {
      BucketName: expect.stringContaining('agentcomms-raw-inbound'),
    });
  });

  test('DynamoDB point-in-time recovery enabled', () => {
    template.hasResourceProperties('AWS::DynamoDB::Table', {
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true },
    });
  });
});
```

- [ ] **Step 2: Run test to verify fail**

```bash
cd cdk && npx jest agentcomms-data-stack.test.ts
cd ..
```

Expected: FAIL — file not found.

- [ ] **Step 3: Implement `cdk/lib/stacks/agentcomms-data-stack.ts`**

```typescript
// cdk/lib/stacks/agentcomms-data-stack.ts
import { Stack, StackProps, RemovalPolicy, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import {
  Table, AttributeType, BillingMode, ProjectionType, TableEncryption,
} from 'aws-cdk-lib/aws-dynamodb';
import {
  Bucket, BucketEncryption, BlockPublicAccess, LifecycleRule,
  StorageClass, Transition,
} from 'aws-cdk-lib/aws-s3';

export interface AgentCommsDataStackProps extends StackProps {
  envName?: string;    // "prod" | "staging" | "dev"; affects bucket names
}

export class AgentCommsDataStack extends Stack {
  public readonly table: Table;
  public readonly rawInboundBucket: Bucket;
  public readonly bodiesBucket: Bucket;
  public readonly attachmentsBucket: Bucket;

  constructor(scope: Construct, id: string, props: AgentCommsDataStackProps = {}) {
    super(scope, id, props);
    const envName = props.envName ?? 'prod';

    // ── DynamoDB single table ──
    this.table = new Table(this, 'AgentCommsTable', {
      tableName: 'agentcomms',
      partitionKey: { name: 'PK', type: AttributeType.STRING },
      sortKey:      { name: 'SK', type: AttributeType.STRING },
      billingMode:  BillingMode.PAY_PER_REQUEST,
      encryption:   TableEncryption.AWS_MANAGED,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.RETAIN,
      timeToLiveAttribute: 'ttl',
    });
    for (const i of [1, 2, 3, 4, 5, 6, 7]) {
      this.table.addGlobalSecondaryIndex({
        indexName:    `GSI${i}`,
        partitionKey: { name: `gsi${i}_pk`, type: AttributeType.STRING },
        sortKey:      { name: `gsi${i}_sk`, type: AttributeType.STRING },
        projectionType: ProjectionType.ALL,
      });
    }

    // ── S3 buckets ──
    const lifecycle: LifecycleRule = {
      transitions: [
        { storageClass: StorageClass.INFREQUENT_ACCESS, transitionAfter: Duration.days(30) },
        { storageClass: StorageClass.GLACIER,            transitionAfter: Duration.days(90) },
      ],
    };
    this.rawInboundBucket = new Bucket(this, 'RawInbound', {
      bucketName: `agentcomms-raw-inbound-${envName}-${this.account}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [lifecycle],
      removalPolicy: RemovalPolicy.RETAIN,
      versioned: false,
    });
    this.bodiesBucket = new Bucket(this, 'Bodies', {
      bucketName: `agentcomms-bodies-${envName}-${this.account}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [lifecycle],
      removalPolicy: RemovalPolicy.RETAIN,
    });
    this.attachmentsBucket = new Bucket(this, 'Attachments', {
      bucketName: `agentcomms-attachments-${envName}-${this.account}`,
      encryption: BucketEncryption.S3_MANAGED,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      lifecycleRules: [lifecycle],
      removalPolicy: RemovalPolicy.RETAIN,
    });
  }
}
```

- [ ] **Step 4: Wire into `cdk/bin/app.ts`**

Read current `cdk/bin/app.ts`, then add:

```typescript
import { AgentCommsDataStack } from '../lib/stacks/agentcomms-data-stack';

// existing victorymail-* stacks stay as-is
new AgentCommsDataStack(app, 'AgentCommsData', {
  env: { account: '732770059798', region: 'us-east-1' },
  envName: 'prod',
});
```

Do NOT remove or rename existing stacks — they stay live until Phase 5 cutover.

- [ ] **Step 5: Run CDK synth and assertion tests**

```bash
cd cdk
npx cdk synth AgentCommsData > /tmp/synth.yaml && head -50 /tmp/synth.yaml
npx jest agentcomms-data-stack.test.ts
cd ..
```

Expected: synth completes without error; 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add cdk/lib/stacks/agentcomms-data-stack.ts cdk/test/agentcomms-data-stack.test.ts cdk/bin/app.ts
git commit -m "feat(phase1): AgentComms CDK data stack (DynamoDB + S3 + 7 GSIs)"
```

---

## Task 16: Port email MIME normalizer

**Files:**
- Create: `adapters/email/normalize.py`
- Create: `adapters/email/tests/fixtures/inbound_simple.eml`
- Create: `adapters/email/tests/fixtures/inbound_gmail_reply.eml`
- Create: `adapters/email/tests/test_normalize.py`

- [ ] **Step 1: Inspect existing MIME handling to port from**

```bash
grep -l "email.parser\|parse_mime\|quotequail\|extract_body" lambdas/ -r
```

Expected: hits in `lambdas/inbound_processor/handler.py`. Read it and understand the current parsing logic — especially which headers it grabs, how it strips quoted replies, and which libraries are used. The port must not lose any behavior.

- [ ] **Step 2: Create fixture `adapters/email/tests/fixtures/inbound_simple.eml`**

```
From: Alice <alice@example.com>
To: bot@agentcomms.dev
Subject: March invoice
Message-ID: <abc123@example.com>
Date: Fri, 17 Apr 2026 09:12:03 +0000
Content-Type: text/plain; charset=utf-8

Hi bot, please see the attached invoice.

Thanks,
Alice
```

- [ ] **Step 3: Create fixture `adapters/email/tests/fixtures/inbound_gmail_reply.eml`**

```
From: Alice <alice@example.com>
To: bot@agentcomms.dev
Subject: Re: March invoice
Message-ID: <def456@example.com>
In-Reply-To: <abc123@example.com>
References: <abc123@example.com>
Date: Fri, 17 Apr 2026 10:00:00 +0000
Content-Type: text/plain; charset=utf-8

Thanks for the invoice.

On Fri, Apr 17, 2026 at 9:12 AM bot <bot@agentcomms.dev> wrote:
> Here is the invoice.
```

- [ ] **Step 4: Write failing test**

```python
# adapters/email/tests/test_normalize.py
from pathlib import Path
from adapters.email.normalize import parse_mime_bytes, ParsedEmail

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_simple_email():
    raw = (FIXTURES / "inbound_simple.eml").read_bytes()
    p: ParsedEmail = parse_mime_bytes(raw)
    assert p.from_address == "alice@example.com"
    assert p.from_display_name == "Alice"
    assert p.to_addresses == ["bot@agentcomms.dev"]
    assert p.subject == "March invoice"
    assert p.message_id_header == "<abc123@example.com>"
    assert p.in_reply_to is None
    assert "Hi bot" in p.body_text
    assert p.attachments == []


def test_parse_reply_extracts_threading_headers_and_strips_quote():
    raw = (FIXTURES / "inbound_gmail_reply.eml").read_bytes()
    p = parse_mime_bytes(raw)
    assert p.in_reply_to == "<abc123@example.com>"
    assert p.references == ["<abc123@example.com>"]
    # Quoted original should be removed from body_text
    assert "Thanks for the invoice." in p.body_text
    assert "Here is the invoice" not in p.body_text
    assert "bot@agentcomms.dev wrote" not in p.body_text


def test_parse_invalid_bytes_raises_valueerror():
    import pytest
    with pytest.raises(ValueError):
        parse_mime_bytes(b"")
```

- [ ] **Step 5: Run to verify fail**

```bash
pytest adapters/email/tests/test_normalize.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 6: Implement `adapters/email/normalize.py`**

```python
# adapters/email/normalize.py
"""
Parse raw MIME into the AgentComms normalized form.

Ports the MIME parsing and quoted-reply stripping that the existing FreeMail
`lambdas/inbound_processor/handler.py` implements. The output shape is the
adapter's private intermediate representation, converted to UnifiedMessage in
adapter.py.
"""
from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from email.message import Message
from email.utils import getaddresses, parseaddr
from typing import Any


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    size: int
    content: bytes


@dataclass
class ParsedEmail:
    from_address: str
    from_display_name: str | None
    to_addresses: list[str]
    cc_addresses: list[str] = field(default_factory=list)
    subject: str = ""
    message_id_header: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    body_text: str = ""
    body_html: str | None = None
    attachments: list[ParsedAttachment] = field(default_factory=list)


_GMAIL_QUOTE_RE = re.compile(
    r"\n+On .+ wrote:\s*\n(?:>.*\n?)+", flags=re.DOTALL,
)
_OUTLOOK_QUOTE_RE = re.compile(
    r"\n+-----Original Message-----.*", flags=re.DOTALL,
)
_APPLE_QUOTE_RE = re.compile(
    r"\n+On .+, .+ <.+@.+> wrote:\s*\n(?:>.*\n?)+", flags=re.DOTALL,
)


def strip_quoted_reply(text: str) -> str:
    for pat in (_APPLE_QUOTE_RE, _GMAIL_QUOTE_RE, _OUTLOOK_QUOTE_RE):
        text = pat.sub("", text)
    return text.rstrip() + "\n" if text.strip() else ""


def _references_list(msg: Message) -> list[str]:
    raw = msg.get("References") or ""
    return [r.strip() for r in raw.split() if r.strip()]


def _extract_body(msg: Message) -> tuple[str, str | None]:
    text: str = ""
    html: str | None = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and not text:
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif ctype == "text/html" and not html:
                payload = part.get_payload(decode=True) or b""
                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True) or b""
        decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html":
            html = decoded
        else:
            text = decoded
    return strip_quoted_reply(text), html


def _extract_attachments(msg: Message) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        attachments.append(ParsedAttachment(
            filename=part.get_filename() or "attachment",
            content_type=part.get_content_type(),
            size=len(payload),
            content=payload,
        ))
    return attachments


def parse_mime_bytes(raw: bytes) -> ParsedEmail:
    if not raw:
        raise ValueError("empty MIME bytes")
    msg = email.message_from_bytes(raw)
    if msg.keys() == []:
        raise ValueError("no MIME headers found")
    from_display, from_addr = parseaddr(msg.get("From") or "")
    to_addresses = [a for _, a in getaddresses([msg.get("To") or ""]) if a]
    cc_addresses = [a for _, a in getaddresses([msg.get("Cc") or ""]) if a]
    text, html = _extract_body(msg)
    return ParsedEmail(
        from_address=from_addr,
        from_display_name=from_display or None,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=msg.get("Subject", "") or "",
        message_id_header=msg.get("Message-ID"),
        in_reply_to=msg.get("In-Reply-To"),
        references=_references_list(msg),
        body_text=text,
        body_html=html,
        attachments=_extract_attachments(msg),
    )
```

- [ ] **Step 7: Run tests**

```bash
pytest adapters/email/tests/test_normalize.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add adapters/email/normalize.py adapters/email/tests/
git commit -m "feat(phase1): email adapter — MIME normalizer with quoted-reply stripping"
```

---

## Task 17: `EmailAdapter(ChannelAdapter)` — provision, send, ingest, teardown, health

**Files:**
- Create: `adapters/email/adapter.py`
- Create: `adapters/email/tests/test_adapter.py`

- [ ] **Step 1: Write failing test**

```python
# adapters/email/tests/test_adapter.py
from datetime import datetime, timezone
from pathlib import Path
import pytest

from core.data.models import Agent, Channel, ChannelType, ChannelMode, ChannelStatus
from core.adapters.base import IngestPayload, OutboundMessage
from adapters.email.adapter import EmailAdapter


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def adapter():
    return EmailAdapter()


def test_channel_name_and_modes(adapter):
    assert adapter.channel_name == "email"
    assert adapter.supports_modes == ["provision"]


def test_provision_returns_pending_until_dkim_verified(adapter, ses_client):
    agent = Agent(agent_id="agt_1", org_id="org_X", name="bot")
    result = adapter.provision(agent=agent, config={
        "local_part": "bot", "domain": "agentcomms.dev",
    })
    # Provision creates SES identity; returns pending until DKIM succeeds out-of-band
    assert result.status in ("pending_verification", "active")
    assert result.details["address"] == "bot@agentcomms.dev"
    assert "dkim_tokens" in result.details


def test_ingest_routes_by_recipient(adapter, agentcomms_table, s3_buckets, repo_fixture):
    # Seed a channel whose inbound address matches the fixture recipient
    from core.data.models import Channel, ChannelType, ChannelMode
    channel = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    )
    repo_fixture.put_channel(channel)

    raw = (FIXTURES / "inbound_simple.eml").read_bytes()
    payload = IngestPayload(source="sns", headers={}, body=raw, path_params={})
    msg = adapter.ingest(payload=payload)

    assert msg is not None
    assert msg.channel.value == "email"
    assert msg.direction.value == "inbound"
    assert msg.agent_id == "agt_1"
    assert msg.channel_id == "chan_em_1"
    assert msg.is_dm is True
    assert msg.subject == "March invoice"
    assert msg.from_.address == "alice@example.com"
    assert msg.to[0].address == "bot@agentcomms.dev"
    assert msg.external_id == "<abc123@example.com>"
    assert msg.channel_native["message_id_header"] == "<abc123@example.com>"


def test_ingest_returns_none_for_unknown_recipient(adapter, agentcomms_table, s3_buckets, repo_fixture):
    raw = (FIXTURES / "inbound_simple.eml").read_bytes()
    payload = IngestPayload(source="sns", headers={}, body=raw, path_params={})
    # No channel registered for bot@agentcomms.dev
    msg = adapter.ingest(payload=payload)
    assert msg is None


def test_send_builds_mime_and_calls_ses(adapter, ses_client, repo_fixture):
    # Verify identity first (SES requires for sending)
    ses_client.verify_domain_identity(Domain="agentcomms.dev")
    channel = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    )
    msg = OutboundMessage(
        to="alice@example.com",
        body_text="Hello",
        subject="Test",
    )
    result = adapter.send(channel=channel, message=msg)
    assert result.status == "sent"
    assert result.channel_native_id  # some SES MessageId


def test_health_check(adapter, ses_client, repo_fixture):
    channel = Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        status=ChannelStatus.ACTIVE,
    )
    status = adapter.health_check(channel=channel)
    assert status.ok is True
```

Add a `repo_fixture` in `tests/conftest.py`:

```python
@pytest.fixture
def repo_fixture(agentcomms_table):
    from core.data.repo import Repo
    return Repo(table=agentcomms_table)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest adapters/email/tests/test_adapter.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `adapters/email/adapter.py`**

```python
# adapters/email/adapter.py
"""
Email channel adapter for AgentComms.

Wraps SES (outbound via SendRawEmail) and SES Inbound (parsed by normalize.py).
Implements the ChannelAdapter contract.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import boto3

from core.adapters.base import (
    BridgeResult, BridgeStart, ChannelAdapter, HealthStatus, IngestPayload,
    OutboundMessage, ProvisionResult, SendResult,
)
from core.data.models import (
    Agent, Channel, ChannelType, MessageDirection, MessageStatus, Party,
    UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id

from adapters.email.normalize import parse_mime_bytes


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    table_name = os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


class EmailAdapter(ChannelAdapter):
    channel_name = "email"
    supports_modes = ["provision"]

    # ── provision / teardown / health ──
    def provision(self, *, agent: Agent, config: dict[str, Any]) -> ProvisionResult:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        domain = config["domain"]
        local_part = config["local_part"]
        address = f"{local_part}@{domain}"

        # Ensure the domain is a verified identity (creates if absent).
        try:
            resp = ses.verify_domain_dkim(Domain=domain)
            dkim_tokens = resp["DkimTokens"]
        except ses.exceptions.ClientError:
            dkim_tokens = []

        channel_id = new_id("chan", suffix="em")
        status = "pending_verification" if dkim_tokens else "active"
        return ProvisionResult(
            status=status,
            channel_id=channel_id,
            details={
                "address": address,
                "domain": domain,
                "dkim_tokens": dkim_tokens,
                "dkim_verified": False,
            },
        )

    def teardown(self, *, channel: Channel) -> None:
        # Releasing a per-agent email is low-impact: we don't delete SES domain
        # identity (shared across agents); we just mark the Channel disabled in
        # the repo. The core layer handles that — no SES call needed.
        return None

    def health_check(self, *, channel: Channel) -> HealthStatus:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        try:
            ses.get_send_quota()
            return HealthStatus(
                ok=True,
                last_success_at=datetime.now(timezone.utc).isoformat(),
            )
        except Exception as e:
            return HealthStatus(
                ok=False,
                last_success_at=datetime.now(timezone.utc).isoformat(),
                error=str(e),
            )

    # ── ingest (inbound) ──
    def ingest(self, *, payload: IngestPayload) -> UnifiedMessage | None:
        raw = payload.body if isinstance(payload.body, bytes) else bytes(payload.body)
        parsed = parse_mime_bytes(raw)

        # Resolve which agent+channel this email is for by the recipient.
        repo = Repo(_get_table())
        target_channel: Channel | None = None
        for recipient in parsed.to_addresses:
            target_channel = repo.lookup_channel_by_address(
                channel="email", address=recipient,
            )
            if target_channel:
                break
        if target_channel is None:
            return None  # no agent owns this address → drop

        # Idempotency: if we've seen this Message-ID before, drop.
        if parsed.message_id_header:
            existing = repo.lookup_message_by_external_id(
                channel="email", external_id=parsed.message_id_header,
            )
            if existing:
                return None

        msg = UnifiedMessage(
            message_id=new_id("msg"),
            agent_id=target_channel.agent_id,
            org_id=target_channel.org_id,
            channel_id=target_channel.channel_id,
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            from_=Party(
                address=parsed.from_address,
                display_name=parsed.from_display_name,
            ),
            to=[Party(address=a) for a in parsed.to_addresses],
            subject=parsed.subject or None,
            body_text=parsed.body_text,
            body_html=parsed.body_html,
            thread_key=None,  # thread resolution handled by core after persist
            is_dm=True,       # every email to an agent inbox is direct
            received_at=datetime.now(timezone.utc),
            channel_native={
                "message_id_header": parsed.message_id_header,
                "in_reply_to": parsed.in_reply_to,
                "references": parsed.references,
            },
            external_id=parsed.message_id_header,
        )
        return msg

    # ── send (outbound) ──
    def send(self, *, channel: Channel, message: OutboundMessage) -> SendResult:
        ses = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        from_address = channel.config["address"]
        to_address = message.to if isinstance(message.to, str) else message.to.get("address")

        if message.body_html:
            root = MIMEMultipart("alternative")
            root.attach(MIMEText(message.body_text, "plain", "utf-8"))
            root.attach(MIMEText(message.body_html, "html", "utf-8"))
        else:
            root = MIMEText(message.body_text, "plain", "utf-8")
        root["From"] = from_address
        root["To"] = to_address
        if message.subject:
            root["Subject"] = message.subject

        try:
            resp = ses.send_raw_email(
                Source=from_address,
                Destinations=[to_address],
                RawMessage={"Data": root.as_bytes()},
            )
            return SendResult(
                channel_native_id=resp["MessageId"],
                status="sent",
            )
        except Exception as e:
            return SendResult(
                channel_native_id="",
                status="failed",
                error=str(e),
            )
```

- [ ] **Step 4: Run tests**

```bash
pytest adapters/email/tests/test_adapter.py -v
```

Expected: 6 passed. If the `ses_client` fixture (moto) doesn't support all SES APIs the adapter calls, adjust the test to stub those calls via `mock.patch` on the adapter's client; don't weaken the adapter.

- [ ] **Step 5: Commit**

```bash
git add adapters/email/adapter.py adapters/email/tests/test_adapter.py tests/conftest.py
git commit -m "feat(phase1): EmailAdapter — provision, send, ingest, teardown, health"
```

---

## Task 18: Email adapter manifest + email ingest Lambda handler

**Files:**
- Create: `adapters/email/manifest.toml`
- Create: `adapters/email/ingest.py`
- Create: `adapters/email/outbound.py`

- [ ] **Step 1: Create `adapters/email/manifest.toml`**

```toml
[adapter]
channel = "email"
class = "adapters.email.adapter:EmailAdapter"
modes = ["provision"]
cdk_stack = "adapters.email.stack:EmailAdapterStack"
min_hub_version = "0.1"

[webhook_routes]
# Email ingest is via SES → SNS → Lambda, not an API Gateway webhook.
# No entries here.

[ssm_secrets]
# No per-deploy secrets needed for email beyond what CDK auto-wires.
```

- [ ] **Step 2: Create `adapters/email/ingest.py` (Lambda handler)**

```python
# adapters/email/ingest.py
"""
Lambda entry point for inbound email.

SES deposits raw MIME to S3, then publishes an SNS event that triggers this
Lambda. We fetch the raw MIME from S3, run it through EmailAdapter.ingest(),
persist the UnifiedMessage, and publish message.received to Kinesis.
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import IngestPayload
from core.data.repo import Repo
from adapters.email.adapter import EmailAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = EmailAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def _publish_event(event_type: str, msg_dict: dict) -> None:
    stream = os.environ.get("AGENTCOMMS_EVENT_STREAM")
    if not stream:
        return
    kinesis = boto3.client("kinesis")
    kinesis.put_record(
        StreamName=stream,
        PartitionKey=msg_dict["agent_id"],
        Data=json.dumps({"type": event_type, "data": msg_dict}).encode("utf-8"),
    )


def handler(event: dict, context) -> dict:
    """SES-SNS trigger. Each record contains an SES notification with a mail
    action that has already placed the raw MIME in S3."""
    s3 = boto3.client("s3")
    repo = Repo(_get_table())
    processed = 0

    for record in event.get("Records", []):
        sns = record.get("Sns", {})
        message = json.loads(sns.get("Message", "{}"))
        # SES notification payload contains {mail: {...}, receipt: {...}}
        receipt = message.get("receipt", {})
        actions = receipt.get("action", {})
        # If configured via a LambdaAction preceded by S3Action, the raw MIME
        # is at the S3 object referenced by the SES messageId.
        bucket = os.environ.get("AGENTCOMMS_BUCKET_RAW_INBOUND")
        key = message.get("mail", {}).get("messageId")  # SES uses this as S3 key
        if not (bucket and key):
            logger.warning("no S3 pointer in SES notification; skipping")
            continue
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            raw = obj["Body"].read()
        except Exception as e:
            logger.exception("failed to fetch raw MIME: %s", e)
            continue

        payload = IngestPayload(
            source="sns",
            headers={k: v for k, v in sns.items() if isinstance(v, str)},
            body=raw,
            path_params={},
        )
        msg = _adapter.ingest(payload=payload)
        if msg is None:
            continue
        repo.put_message(msg)
        _publish_event("message.received", json.loads(msg.model_dump_json(by_alias=True)))
        processed += 1

    return {"processed": processed}
```

- [ ] **Step 3: Create `adapters/email/outbound.py`**

```python
# adapters/email/outbound.py
"""
Outbound SQS-triggered Lambda.

Core API writes {agent_id, channel_id, outbound_message_dict} to the outbound
SQS queue. This Lambda reads from the queue, loads the channel, calls
EmailAdapter.send(), and updates the stored UnifiedMessage with the SES
MessageId + status.
"""
from __future__ import annotations

import json
import logging
import os

import boto3

from core.adapters.base import OutboundMessage
from core.data.models import ChannelType, MessageStatus
from core.data.repo import Repo
from adapters.email.adapter import EmailAdapter

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_adapter = EmailAdapter()


def _get_table():
    region = os.environ.get("AWS_REGION", "us-east-1")
    return boto3.resource("dynamodb", region_name=region).Table(
        os.environ["AGENTCOMMS_TABLE"]
    )


def handler(event: dict, context) -> dict:
    repo = Repo(_get_table())
    processed = 0

    for record in event.get("Records", []):
        body = json.loads(record["body"])
        agent_id = body["agent_id"]
        channel_id = body["channel_id"]
        msg_id = body["message_id"]
        received_at_ms = body["received_at_ms"]
        outbound_dict = body["outbound_message"]

        channel = repo.get_channel(
            agent_id=agent_id,
            channel=ChannelType.EMAIL.value,
            channel_id=channel_id,
        )
        if channel is None:
            logger.error("channel %s/%s not found", agent_id, channel_id)
            continue

        result = _adapter.send(channel=channel, message=OutboundMessage(**outbound_dict))

        # Update the stored UnifiedMessage: status + external_id
        stored = repo.get_message(
            agent_id=agent_id, received_at_ms=received_at_ms, message_id=msg_id,
        )
        if stored:
            stored.status = MessageStatus.SENT if result.status == "sent" else MessageStatus.FAILED
            stored.external_id = result.channel_native_id or stored.external_id
            repo.put_message(stored)

        processed += 1
    return {"processed": processed}
```

- [ ] **Step 4: Sanity-import both handlers**

```bash
python -c "from adapters.email import ingest, outbound; print('OK')"
```

Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add adapters/email/manifest.toml adapters/email/ingest.py adapters/email/outbound.py
git commit -m "feat(phase1): email adapter — manifest, SES→SNS inbound handler, SQS outbound worker"
```

---

## Task 19: Email adapter CDK stack fragment (`adapters/email/stack.py` equivalent in TS)

**Files:**
- Create: `cdk/lib/adapters/email-adapter-stack.ts` (adapter CDK code lives in TS alongside other CDK)

Because the CDK is TypeScript but the adapter is Python, the `cdk_stack` reference in `manifest.toml` points to a TypeScript construct. The Python `cdk_wiring()` method is left as a no-op for email (its resources are declared in TS). Document this.

- [ ] **Step 1: Create `cdk/lib/adapters/email-adapter-stack.ts`**

```typescript
// cdk/lib/adapters/email-adapter-stack.ts
//
// Email adapter AWS resources:
//   - SES receipt rule set that captures inbound mail for the configured domains
//   - S3 action → agentcomms-raw-inbound bucket
//   - SNS action → AgentComms email-ingest topic
//   - Lambda subscribed to SNS topic → adapters/email/ingest.py handler
//   - SQS queue for outbound sends → adapters/email/outbound.py Lambda consumer
//   - SES configuration set for outbound bounces/complaints
//
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Bucket } from 'aws-cdk-lib/aws-s3';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import { Function as LambdaFn, Runtime, Code } from 'aws-cdk-lib/aws-lambda';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { Topic } from 'aws-cdk-lib/aws-sns';
import { SqsEventSource, SnsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { ReceiptRuleSet } from 'aws-cdk-lib/aws-ses';
import { S3, Sns, AddHeader } from 'aws-cdk-lib/aws-ses-actions';
import { Stream } from 'aws-cdk-lib/aws-kinesis';

export interface EmailAdapterStackProps extends StackProps {
  table: Table;
  rawInboundBucket: Bucket;
  bodiesBucket: Bucket;
  attachmentsBucket: Bucket;
  eventStream: Stream;
  inboundDomains: string[];    // e.g. ['agentcomms.dev']
}

export class EmailAdapterStack extends Stack {
  public readonly ingestFunction: LambdaFn;
  public readonly outboundFunction: LambdaFn;
  public readonly outboundQueue: Queue;

  constructor(scope: Construct, id: string, props: EmailAdapterStackProps) {
    super(scope, id, props);

    // SNS topic SES publishes to
    const inboundTopic = new Topic(this, 'EmailInboundTopic', {
      topicName: 'agentcomms-email-inbound',
    });

    // Ingest Lambda
    this.ingestFunction = new LambdaFn(this, 'EmailIngestFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.email.ingest.handler',
      code: Code.fromAsset('..', {
        exclude: ['cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '*.md'],
      }),
      timeout: Duration.seconds(30),
      memorySize: 1024,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_BUCKET_RAW_INBOUND: props.rawInboundBucket.bucketName,
        AGENTCOMMS_BUCKET_BODIES: props.bodiesBucket.bucketName,
        AGENTCOMMS_BUCKET_ATTACHMENTS: props.attachmentsBucket.bucketName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      },
    });
    this.ingestFunction.addEventSource(new SnsEventSource(inboundTopic));
    props.table.grantReadWriteData(this.ingestFunction);
    props.rawInboundBucket.grantRead(this.ingestFunction);
    props.eventStream.grantWrite(this.ingestFunction);

    // SES receipt rule
    const ruleSet = new ReceiptRuleSet(this, 'EmailReceipt', { receiptRuleSetName: 'agentcomms' });
    ruleSet.addRule('CatchAll', {
      recipients: props.inboundDomains,
      actions: [
        new S3({ bucket: props.rawInboundBucket, objectKeyPrefix: 'inbound/' }),
        new Sns({ topic: inboundTopic }),
      ],
    });

    // Outbound
    this.outboundQueue = new Queue(this, 'EmailOutboundQueue', {
      queueName: 'agentcomms-email-outbound',
      visibilityTimeout: Duration.seconds(60),
    });
    this.outboundFunction = new LambdaFn(this, 'EmailOutboundFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'adapters.email.outbound.handler',
      code: Code.fromAsset('..', {
        exclude: ['cdk', 'console', 'sdks', 'node_modules', '.git', 'tests', '*.md'],
      }),
      timeout: Duration.seconds(30),
      memorySize: 512,
      environment: {
        AGENTCOMMS_TABLE: props.table.tableName,
        AGENTCOMMS_EVENT_STREAM: props.eventStream.streamName,
      },
    });
    this.outboundFunction.addEventSource(new SqsEventSource(this.outboundQueue));
    props.table.grantReadWriteData(this.outboundFunction);
    this.outboundFunction.addToRolePolicy(
      // SES send permission (scoped in real deploy; wildcard here for brevity)
      new (require('aws-cdk-lib/aws-iam').PolicyStatement)({
        actions: ['ses:SendRawEmail'],
        resources: ['*'],
      }),
    );
    props.eventStream.grantWrite(this.outboundFunction);
  }
}
```

- [ ] **Step 2: Verify CDK synth**

```bash
cd cdk && npx tsc --noEmit && cd ..
```

Expected: compiles without error. (Actual stack instantiation happens in Task 21 when wired into app.ts.)

- [ ] **Step 3: Commit**

```bash
git add cdk/lib/adapters/email-adapter-stack.ts
git commit -m "feat(phase1): email adapter CDK stack (SES receipt + SNS + Lambda ingest + SQS outbound)"
```

---

## Task 20: Kinesis events stack + outbound SQS event-bus scaffolding

**Files:**
- Create: `cdk/lib/stacks/agentcomms-events-stack.ts`
- Create: `cdk/test/agentcomms-events-stack.test.ts`

- [ ] **Step 1: Write failing assertion test**

```typescript
// cdk/test/agentcomms-events-stack.test.ts
import { App } from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { AgentCommsEventsStack } from '../lib/stacks/agentcomms-events-stack';

describe('AgentCommsEventsStack', () => {
  const app = new App();
  const stack = new AgentCommsEventsStack(app, 'Test');
  const tpl = Template.fromStack(stack);

  test('Kinesis stream with 4 shards', () => {
    tpl.hasResourceProperties('AWS::Kinesis::Stream', {
      Name: 'agentcomms-events',
      ShardCount: 4,
      RetentionPeriodHours: 168,  // 7 days
    });
  });
});
```

- [ ] **Step 2: Run test, expect fail**

```bash
cd cdk && npx jest agentcomms-events-stack.test.ts ; cd ..
```

Expected: FAIL — not found.

- [ ] **Step 3: Implement stack**

```typescript
// cdk/lib/stacks/agentcomms-events-stack.ts
import { Stack, StackProps, Duration } from 'aws-cdk-lib';
import { Construct } from 'constructs';
import { Stream, StreamMode } from 'aws-cdk-lib/aws-kinesis';

export class AgentCommsEventsStack extends Stack {
  public readonly eventStream: Stream;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);
    this.eventStream = new Stream(this, 'AgentCommsEvents', {
      streamName: 'agentcomms-events',
      shardCount: 4,
      retentionPeriod: Duration.days(7),
      streamMode: StreamMode.PROVISIONED,
    });
  }
}
```

- [ ] **Step 4: Run tests**

```bash
cd cdk && npx jest agentcomms-events-stack.test.ts && cd ..
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add cdk/lib/stacks/agentcomms-events-stack.ts cdk/test/agentcomms-events-stack.test.ts
git commit -m "feat(phase1): AgentComms Kinesis events stack (4 shards, 7-day retention)"
```

---

## Task 21: Authorizer Lambda (new scope model: org / agent / channel)

**Files:**
- Create: `core/api/authorizer.py`
- Create: `tests/core/test_authorizer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/core/test_authorizer.py
import hashlib
import pytest
from core.data.models import ApiKey, ApiKeyScope
from core.data.repo import Repo
from core.api.authorizer import authorize, DeniedError


@pytest.fixture
def repo_with_keys(agentcomms_table):
    repo = Repo(table=agentcomms_table)
    org_key = ApiKey(
        key_id="k_org", key_hash=hashlib.sha256(b"org_secret").hexdigest(),
        org_id="org_X", scope=ApiKeyScope.ORG, name="admin",
    )
    agent_key = ApiKey(
        key_id="k_agt", key_hash=hashlib.sha256(b"agt_secret").hexdigest(),
        org_id="org_X", scope=ApiKeyScope.AGENT, agent_id="agt_1", name="bot",
    )
    repo.put_table_item = repo.table.put_item  # for reuse if needed
    repo.table.put_item(Item=org_key.to_dynamodb_item())
    repo.table.put_item(Item=agent_key.to_dynamodb_item())
    return repo


def test_valid_org_key_allows_everything(repo_with_keys):
    ctx = authorize(
        repo=repo_with_keys,
        raw_api_key="org_secret",
        requested_path="/v1/agents/agt_1/messages",
        requested_method="POST",
    )
    assert ctx.org_id == "org_X"
    assert ctx.scope == "org"


def test_agent_key_allows_own_agent_path(repo_with_keys):
    ctx = authorize(
        repo=repo_with_keys,
        raw_api_key="agt_secret",
        requested_path="/v1/agents/agt_1/messages",
        requested_method="GET",
    )
    assert ctx.agent_id == "agt_1"


def test_agent_key_denies_other_agent_path(repo_with_keys):
    with pytest.raises(DeniedError):
        authorize(
            repo=repo_with_keys,
            raw_api_key="agt_secret",
            requested_path="/v1/agents/agt_OTHER/messages",
            requested_method="GET",
        )


def test_unknown_key_denied(repo_with_keys):
    with pytest.raises(DeniedError):
        authorize(
            repo=repo_with_keys,
            raw_api_key="nope",
            requested_path="/v1/agents/agt_1/messages",
            requested_method="GET",
        )
```

- [ ] **Step 2: Run test to verify fail**

```bash
pytest tests/core/test_authorizer.py -v
```

Expected: FAIL — not found.

- [ ] **Step 3: Implement `core/api/authorizer.py`**

```python
# core/api/authorizer.py
"""
AgentComms authorizer.

Looks up an API key via GSI1, returns a caller context with scope enforcement.
Agent-scoped keys may only access paths containing their agent_id; channel-
scoped keys additionally restrict to their channel_id.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from boto3.dynamodb.conditions import Key

from core.data.models import ApiKey, ApiKeyScope
from core.data.repo import Repo


class DeniedError(Exception):
    pass


@dataclass
class CallerContext:
    org_id: str
    scope: str
    agent_id: str | None = None
    channel_id: str | None = None
    api_key_id: str | None = None


_AGENT_PATH_RE = re.compile(r"^/v1/agents/(?P<agent_id>agt_[A-Za-z0-9_]+)")
_CHANNEL_PATH_RE = re.compile(
    r"^/v1/agents/agt_[A-Za-z0-9_]+/channels/(?P<channel_id>chan_[A-Za-z0-9_]+)"
)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_by_hash(repo: Repo, key_hash: str) -> ApiKey | None:
    resp = repo.table.query(
        IndexName="GSI1",
        KeyConditionExpression=Key("gsi1_pk").eq(f"APIKEY#{key_hash}"),
        Limit=1,
    )
    items = resp.get("Items", [])
    if not items:
        return None
    return ApiKey.from_dynamodb_item(items[0])


def authorize(
    *, repo: Repo, raw_api_key: str,
    requested_path: str, requested_method: str,
) -> CallerContext:
    key = _load_by_hash(repo, _hash(raw_api_key))
    if key is None:
        raise DeniedError("invalid API key")

    ctx = CallerContext(
        org_id=key.org_id,
        scope=key.scope.value,
        agent_id=key.agent_id,
        channel_id=key.channel_id,
        api_key_id=key.key_id,
    )

    if key.scope == ApiKeyScope.ORG:
        return ctx  # full access within the org

    if key.scope == ApiKeyScope.AGENT:
        m = _AGENT_PATH_RE.match(requested_path)
        if not m or m.group("agent_id") != key.agent_id:
            raise DeniedError(
                f"agent-scoped key {key.key_id} denied for path {requested_path}"
            )
        return ctx

    if key.scope == ApiKeyScope.CHANNEL:
        m_agt = _AGENT_PATH_RE.match(requested_path)
        m_ch = _CHANNEL_PATH_RE.match(requested_path)
        if not m_agt or m_agt.group("agent_id") != key.agent_id:
            raise DeniedError("channel-scoped key denied (wrong agent)")
        if m_ch and m_ch.group("channel_id") != key.channel_id:
            raise DeniedError("channel-scoped key denied (wrong channel)")
        return ctx

    raise DeniedError(f"unknown scope: {key.scope}")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/core/test_authorizer.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add core/api/authorizer.py tests/core/test_authorizer.py
git commit -m "feat(phase1): authorizer with org/agent/channel scope enforcement (GSI1 lookup)"
```

---

## Task 22: `POST /v1/agents` — create agent + one-shot provision

**Files:**
- Create: `core/api/_common.py` (shared request/response helpers)
- Create: `core/api/agents_handler.py`
- Create: `tests/api/test_agents.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_agents.py
import json
import pytest
from unittest.mock import patch

from core.data.models import Organization, OrgPlan
from core.data.repo import Repo
from core.api.agents_handler import handler


@pytest.fixture
def seeded(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    return repo


def _event(method, path, body=None, ctx=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": {},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {
            "authorizer": ctx or {
                "org_id": "org_X", "scope": "org",
                "agent_id": None, "channel_id": None, "api_key_id": "k_org",
            },
        },
    }


def test_create_agent_with_email_provision(seeded):
    with patch("adapters.email.adapter.boto3") as mock_boto3:
        # Mock SES client
        mock_ses = mock_boto3.client.return_value
        mock_ses.verify_domain_dkim.return_value = {"DkimTokens": ["t1", "t2", "t3"]}
        event = _event("POST", "/v1/agents", body={
            "name": "InvoiceBot",
            "provision": {
                "email": {"local_part": "invoice-bot", "domain": "agentcomms.dev"}
            },
        })
        resp = handler(event, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["agent_id"].startswith("agt_")
    assert len(body["channels"]) == 1
    assert body["channels"][0]["channel"] == "email"
    assert body["channels"][0]["details"]["address"] == "invoice-bot@agentcomms.dev"


def test_create_agent_no_provision(seeded):
    event = _event("POST", "/v1/agents", body={"name": "Minimal"})
    resp = handler(event, None)
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["channels"] == []


def test_list_agents(seeded):
    # seed two agents
    handler(_event("POST", "/v1/agents", body={"name": "A"}), None)
    handler(_event("POST", "/v1/agents", body={"name": "B"}), None)
    resp = handler(_event("GET", "/v1/agents"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["agents"]) == 2


def test_get_agent_by_id(seeded):
    c = handler(_event("POST", "/v1/agents", body={"name": "GetMe"}), None)
    agent_id = json.loads(c["body"])["agent_id"]
    event = _event("GET", f"/v1/agents/{agent_id}")
    event["pathParameters"] = {"agent_id": agent_id}
    resp = handler(event, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["name"] == "GetMe"


def test_delete_agent(seeded):
    c = handler(_event("POST", "/v1/agents", body={"name": "Trash"}), None)
    agent_id = json.loads(c["body"])["agent_id"]
    event = _event("DELETE", f"/v1/agents/{agent_id}")
    event["pathParameters"] = {"agent_id": agent_id}
    resp = handler(event, None)
    assert resp["statusCode"] == 204
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/api/test_agents.py -v
```

Expected: FAIL — handler not found.

- [ ] **Step 3: Implement `core/api/_common.py`**

```python
# core/api/_common.py
"""Shared request/response helpers for hub API handlers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import boto3

from core.data.repo import Repo


def ok(body: Any, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def err(message: str, status: int = 400) -> dict:
    return ok({"error": message}, status=status)


def no_content() -> dict:
    return {"statusCode": 204, "body": ""}


@dataclass
class Caller:
    org_id: str
    scope: str
    agent_id: str | None = None
    channel_id: str | None = None
    api_key_id: str | None = None

    @classmethod
    def from_event(cls, event: dict) -> Caller:
        a = event["requestContext"]["authorizer"]
        return cls(
            org_id=a["org_id"],
            scope=a["scope"],
            agent_id=a.get("agent_id"),
            channel_id=a.get("channel_id"),
            api_key_id=a.get("api_key_id"),
        )


def get_repo() -> Repo:
    region = os.environ.get("AWS_REGION", "us-east-1")
    table = boto3.resource("dynamodb", region_name=region).Table(
        os.environ.get("AGENTCOMMS_TABLE", "agentcomms")
    )
    return Repo(table)


def parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    return json.loads(raw) if isinstance(raw, str) else raw
```

- [ ] **Step 4: Implement `core/api/agents_handler.py`**

```python
# core/api/agents_handler.py
"""
/v1/agents/* route handlers.

Dispatches on METHOD + path pattern. Uses the adapter registry to provision
channels declared in the request body.
"""
from __future__ import annotations

from core.api._common import Caller, get_repo, err, ok, no_content, parse_body
from core.adapters.registry import load_registry
from core.data.models import Agent, Channel, ChannelMode, ChannelType, ChannelStatus
from core.data.ulid_ import new_id


_REGISTRY = None


def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


def _provision_channels(
    *, agent: Agent, provision: dict, bridge: dict
) -> list[Channel]:
    repo = get_repo()
    registry = _registry()
    results: list[Channel] = []

    # A-mode: provision
    for channel_name, config in (provision or {}).items():
        entry = registry.get(channel_name)
        if not entry:
            continue
        if channel_name == "push" and config is True:
            config = {}
        provision_result = entry.adapter.provision(agent=agent, config=config or {})
        address_index = None
        if channel_name == "email":
            address_index = provision_result.details.get("address")
        ch = Channel(
            channel_id=provision_result.channel_id,
            agent_id=agent.agent_id,
            org_id=agent.org_id,
            channel=ChannelType(channel_name),
            mode=ChannelMode.PROVISION,
            config=provision_result.details,
            status=ChannelStatus(provision_result.status)
                if provision_result.status in [e.value for e in ChannelStatus]
                else ChannelStatus.PROVISIONING,
            address_index_value=address_index,
        )
        repo.put_channel(ch)
        results.append(ch)

    # B-mode: bridge_start
    for channel_name, cfg in (bridge or {}).items():
        entry = registry.get(channel_name)
        if not entry or "bridge" not in entry.modes:
            continue
        bs = entry.adapter.bridge_start(agent=agent, config=cfg)
        ch = Channel(
            channel_id=new_id("chan", suffix=channel_name[:2]),
            agent_id=agent.agent_id,
            org_id=agent.org_id,
            channel=ChannelType(channel_name),
            mode=ChannelMode.BRIDGE,
            config={"oauth_state": bs.state, "oauth_url": bs.oauth_url},
            status=ChannelStatus.PENDING_OAUTH,
        )
        repo.put_channel(ch)
        results.append(ch)

    return results


def _channel_to_response(ch: Channel) -> dict:
    details = dict(ch.config)
    return {
        "channel": ch.channel.value,
        "channel_id": ch.channel_id,
        "status": ch.status.value,
        "details": details,
    }


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()

    # POST /v1/agents → create
    if method == "POST" and path == "/v1/agents":
        body = parse_body(event)
        if not body.get("name"):
            return err("name is required", 400)
        agent_id = new_id("agt")
        agent = Agent(
            agent_id=agent_id,
            org_id=caller.org_id,
            name=body["name"],
            metadata=body.get("metadata") or {},
        )
        repo.put_agent(agent)
        channels = _provision_channels(
            agent=agent,
            provision=body.get("provision") or {},
            bridge=body.get("bridge") or {},
        )
        return ok({
            "agent_id": agent.agent_id,
            "name": agent.name,
            "channels": [_channel_to_response(c) for c in channels],
        }, status=201)

    # GET /v1/agents → list
    if method == "GET" and path == "/v1/agents":
        agents = repo.list_agents(org_id=caller.org_id)
        return ok({"agents": [{"agent_id": a.agent_id, "name": a.name} for a in agents]})

    # GET /v1/agents/{id} → read
    if method == "GET" and pp.get("agent_id"):
        agent = repo.get_agent(org_id=caller.org_id, agent_id=pp["agent_id"])
        if not agent:
            return err("agent not found", 404)
        return ok({"agent_id": agent.agent_id, "name": agent.name, "metadata": agent.metadata})

    # DELETE /v1/agents/{id}
    if method == "DELETE" and pp.get("agent_id"):
        agent = repo.get_agent(org_id=caller.org_id, agent_id=pp["agent_id"])
        if not agent:
            return err("agent not found", 404)
        repo.table.delete_item(
            Key={"PK": f"ORG#{caller.org_id}", "SK": f"AGT#{pp['agent_id']}"}
        )
        return no_content()

    return err("not found", 404)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/api/test_agents.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add core/api/_common.py core/api/agents_handler.py tests/api/test_agents.py
git commit -m "feat(phase1): POST /v1/agents + CRUD with one-shot channel provisioning"
```

---

## Task 23: Unified inbox + send handlers — `/v1/agents/{id}/messages`

**Files:**
- Create: `core/api/messages_handler.py`
- Create: `tests/api/test_messages.py`

- [ ] **Step 1: Write failing test**

```python
# tests/api/test_messages.py
import json
from datetime import datetime, timedelta, timezone
import pytest

from core.data.models import (
    Agent, Channel, ChannelMode, ChannelStatus, ChannelType, MessageDirection,
    MessageStatus, Organization, OrgPlan, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.api.messages_handler import handler


@pytest.fixture
def fixture(agentcomms_table, ses_client, s3_buckets):
    repo = Repo(agentcomms_table)
    repo.put_organization(Organization(org_id="org_X", name="Acme", plan=OrgPlan.FREE))
    repo.put_agent(Agent(agent_id="agt_1", org_id="org_X", name="bot"))
    repo.put_channel(Channel(
        channel_id="chan_em_1", agent_id="agt_1", org_id="org_X",
        channel=ChannelType.EMAIL, mode=ChannelMode.PROVISION,
        config={"address": "bot@agentcomms.dev"},
        address_index_value="bot@agentcomms.dev",
        status=ChannelStatus.ACTIVE,
    ))
    # Seed 3 inbound messages: 2 DMs, 1 non-DM
    t0 = datetime(2026, 4, 17, 12, tzinfo=timezone.utc)
    for i, is_dm in enumerate([True, True, False]):
        repo.put_message(UnifiedMessage(
            message_id=f"msg_{i}",
            agent_id="agt_1", org_id="org_X", channel_id="chan_em_1",
            channel=ChannelType.EMAIL,
            direction=MessageDirection.INBOUND,
            status=MessageStatus.RECEIVED,
            from_=Party(address="alice@x.com"),
            to=[Party(address="bot@agentcomms.dev")],
            body_text=f"hi {i}",
            is_dm=is_dm,
            received_at=t0 + timedelta(minutes=i),
        ))
    return repo


def _event(method, path, path_params=None, body=None):
    return {
        "httpMethod": method,
        "path": path,
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else None,
        "requestContext": {"authorizer": {
            "org_id": "org_X", "scope": "org",
            "agent_id": None, "channel_id": None, "api_key_id": "k",
        }},
    }


def test_get_unified_inbox_returns_dms_only(fixture):
    resp = handler(_event(
        "GET", "/v1/agents/agt_1/messages", path_params={"agent_id": "agt_1"},
    ), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(body["messages"]) == 2          # is_dm=True only
    assert body["messages"][0]["message_id"] == "msg_1"  # newest first


def test_get_unified_inbox_since_filter(fixture):
    ev = _event(
        "GET", "/v1/agents/agt_1/messages", path_params={"agent_id": "agt_1"},
    )
    ev["queryStringParameters"] = {"since": "2026-04-17T12:00:30Z"}
    resp = handler(ev, None)
    body = json.loads(resp["body"])
    # msg_1 is at 12:01; msg_0 is at 12:00 → only msg_1 qualifies
    assert [m["message_id"] for m in body["messages"]] == ["msg_1"]


def test_send_message_with_address_inference(fixture, monkeypatch):
    # Mock the EmailAdapter.send to avoid real SES
    sent = {}
    from adapters.email.adapter import EmailAdapter
    from core.adapters.base import SendResult
    def fake_send(self, *, channel, message):
        sent["to"] = message.to
        sent["body"] = message.body_text
        return SendResult(channel_native_id="ses-id-123", status="sent")
    monkeypatch.setattr(EmailAdapter, "send", fake_send)

    resp = handler(_event(
        "POST", "/v1/agents/agt_1/messages",
        path_params={"agent_id": "agt_1"},
        body={"to": "alice@example.com", "body": "hello from hub"},
    ), None)
    assert resp["statusCode"] == 201
    assert sent["to"] == "alice@example.com"
    assert sent["body"] == "hello from hub"


def test_send_message_explicit_channel_override(fixture, monkeypatch):
    from adapters.email.adapter import EmailAdapter
    from core.adapters.base import SendResult
    monkeypatch.setattr(
        EmailAdapter, "send",
        lambda self, *, channel, message: SendResult(channel_native_id="x", status="sent"),
    )
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/messages",
        path_params={"agent_id": "agt_1"},
        body={"channel": "email", "to": {"address": "alice@x.com"},
              "body_text": "hi", "subject": "hi"},
    ), None)
    assert resp["statusCode"] == 201


def test_send_fails_when_no_channel_configured(fixture):
    # Try to send SMS when no SMS channel exists
    resp = handler(_event(
        "POST", "/v1/agents/agt_1/messages",
        path_params={"agent_id": "agt_1"},
        body={"to": "+15551234567", "body": "hi"},
    ), None)
    assert resp["statusCode"] == 409
    body = json.loads(resp["body"])
    assert "no sms channel" in body["error"].lower()


def test_get_single_message(fixture):
    ev = _event(
        "GET", "/v1/agents/agt_1/messages/msg_0",
        path_params={"agent_id": "agt_1", "message_id": "msg_0"},
    )
    ev["queryStringParameters"] = {"received_at_ms": str(int(
        datetime(2026, 4, 17, 12, tzinfo=timezone.utc).timestamp() * 1000
    ))}
    resp = handler(ev, None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"])["message_id"] == "msg_0"
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/api/test_messages.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `core/api/messages_handler.py`**

```python
# core/api/messages_handler.py
"""
/v1/agents/{agent_id}/messages/* route handler.

Unified inbox (GET) and send (POST).
"""
from __future__ import annotations

from datetime import datetime

from core.api._common import Caller, err, get_repo, no_content, ok, parse_body
from core.adapters.registry import load_registry
from core.adapters.base import OutboundMessage
from core.data.models import (
    ChannelType, MessageDirection, MessageStatus, Party, UnifiedMessage,
)
from core.data.repo import Repo
from core.data.ulid_ import new_id
from core.router.address import infer_channel, AmbiguousAddressError


_REGISTRY = None
def _registry():
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_registry()
    return _REGISTRY


def _find_channel_for_send(
    *, repo: Repo, agent_id: str, channel_type: str,
):
    """Return the first ACTIVE Channel of given type on this agent, or None."""
    for ch in repo.list_channels(agent_id=agent_id):
        if ch.channel.value == channel_type and ch.status.value == "active":
            return ch
    return None


def _message_to_response(msg: UnifiedMessage) -> dict:
    item = msg.to_dynamodb_item()
    # Strip internal index keys from API response
    for k in list(item.keys()):
        if k.startswith("gsi") or k in ("PK", "SK", "entity"):
            item.pop(k, None)
    return item


def handler(event: dict, context) -> dict:
    method = event["httpMethod"]
    path = event.get("path", "")
    pp = event.get("pathParameters") or {}
    qs = event.get("queryStringParameters") or {}
    caller = Caller.from_event(event)
    repo = get_repo()
    agent_id = pp.get("agent_id")
    if not agent_id:
        return err("agent_id required", 400)

    # GET /v1/agents/{id}/messages
    if method == "GET" and path.endswith("/messages"):
        since = None
        until = None
        if qs.get("since"):
            since = datetime.fromisoformat(qs["since"].replace("Z", "+00:00"))
        if qs.get("until"):
            until = datetime.fromisoformat(qs["until"].replace("Z", "+00:00"))
        channel_filter = None
        if qs.get("channels"):
            channel_filter = qs["channels"].split(",")
        limit = int(qs.get("limit", "50"))
        msgs = repo.list_unified_inbox(
            agent_id=agent_id, since=since, until=until,
            channel_filter=channel_filter, limit=limit,
        )
        return ok({"messages": [_message_to_response(m) for m in msgs]})

    # GET /v1/agents/{id}/messages/{msg_id}
    if method == "GET" and pp.get("message_id"):
        ts_ms = int(qs.get("received_at_ms", "0"))
        if not ts_ms:
            return err("received_at_ms query param required", 400)
        msg = repo.get_message(
            agent_id=agent_id, received_at_ms=ts_ms, message_id=pp["message_id"],
        )
        if not msg:
            return err("message not found", 404)
        return ok(_message_to_response(msg))

    # POST /v1/agents/{id}/messages — send
    if method == "POST" and path.endswith("/messages"):
        body = parse_body(event)
        to = body.get("to")
        if not to:
            return err("'to' is required", 400)

        # Determine channel type
        channel_type = body.get("channel")
        if not channel_type:
            try:
                to_str = to if isinstance(to, str) else to.get("address", "")
                channel_type = infer_channel(to_str)
            except AmbiguousAddressError as e:
                return err(str(e), 400)

        # Resolve agent's channel instance of that type
        channel = _find_channel_for_send(
            repo=repo, agent_id=agent_id, channel_type=channel_type,
        )
        if channel is None:
            return err(f"no {channel_type} channel configured on agent {agent_id}", 409)

        # Build outbound message
        outbound = OutboundMessage(
            to=to,
            body_text=body.get("body_text") or body.get("body") or "",
            body_html=body.get("body_html"),
            subject=body.get("subject"),
            attachments=body.get("attachments") or [],
            thread_key=body.get("thread_key"),
        )

        # Resolve adapter + send
        entry = _registry().get(channel_type)
        if not entry:
            return err(f"no adapter for channel {channel_type}", 500)
        result = entry.adapter.send(channel=channel, message=outbound)

        # Persist outbound UnifiedMessage
        now = datetime.utcnow().replace(tzinfo=None)
        from datetime import timezone
        now_tz = datetime.now(timezone.utc)
        stored = UnifiedMessage(
            message_id=new_id("msg"),
            agent_id=agent_id,
            org_id=caller.org_id,
            channel_id=channel.channel_id,
            channel=ChannelType(channel_type),
            direction=MessageDirection.OUTBOUND,
            status=MessageStatus.SENT if result.status == "sent" else MessageStatus.FAILED,
            from_=Party(address=channel.config.get("address", "")),
            to=[Party(address=to if isinstance(to, str) else to.get("address", ""))],
            body_text=outbound.body_text,
            body_html=outbound.body_html,
            subject=outbound.subject,
            thread_key=outbound.thread_key,
            is_dm=True,
            received_at=now_tz,
            channel_native={"vendor_id": result.channel_native_id},
            external_id=result.channel_native_id or None,
        )
        repo.put_message(stored)
        return ok({
            "message_id": stored.message_id,
            "status": stored.status.value,
            "channel_native_id": result.channel_native_id,
        }, status=201)

    return err("not found", 404)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/api/test_messages.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add core/api/messages_handler.py tests/api/test_messages.py
git commit -m "feat(phase1): unified inbox (GSI3) + send with router + single-message read"
```

---

## Task 24: Channels CRUD, Threads, Drafts, Webhooks, Wait, OTP handlers

All five of these follow the same pattern as Task 22/23. Rather than repeat 5× long tasks, this single task bundles them — each gets its own `tests/api/test_<x>.py`, its own handler file, and its own commit. The steps below list the minimum each must include; follow the Task 22/23 pattern.

**Files to create:**
- `core/api/channels_handler.py` + `tests/api/test_channels.py`
- `core/api/threads_handler.py` + `tests/api/test_threads.py`
- `core/api/drafts_handler.py` + `tests/api/test_drafts.py`
- `core/api/webhooks_handler.py` + `tests/api/test_webhooks.py`
- `core/api/wait_handler.py` + `tests/api/test_wait.py`
- `core/api/otp_handler.py` + `tests/api/test_otp.py`

**Per handler, the required routes, behavior, and tests:**

### 24a: channels
Routes: `GET /v1/agents/{id}/channels`, `POST /…/channels`, `GET /…/channels/{channel_id}`, `PATCH`, `DELETE`.
Tests: list (3 channels on one agent), create (calls adapter.provision for A-mode or bridge_start for B-mode), get by id, disable (status→"disabled", calls `adapter.teardown`), delete (also removes the item).
**Commit:** `feat(phase1): channels handler — CRUD + provision/bridge/teardown dispatch`

### 24b: threads
Routes: `GET /v1/agents/{id}/threads` (list unique threads for agent by walking messages), `GET /…/threads/{thread_id}` (all messages in a thread via GSI5).
Tests: list returns distinct threads, get_thread returns messages in chronological order.
**Commit:** `feat(phase1): threads handler — list distinct threads + GSI5 message listing`

### 24c: drafts
Routes: full CRUD under `/v1/agents/{id}/drafts`. Body accepts `channel` discriminator.
Tests: create per-channel draft, update body_text, list all drafts for agent, delete.
**Commit:** `feat(phase1): drafts handler — per-channel draft CRUD`

### 24d: webhooks
Routes: full CRUD under `/v1/agents/{id}/webhooks`. Validation: `url` must be https, `events` must be from the supported list.
Tests: create (generates secret if not provided), enforce https, reject unknown event names.
**Commit:** `feat(phase1): webhooks handler — per-agent subscription CRUD`

### 24e: wait
Route: `POST /v1/agents/{id}/wait` — long-poll for next inbound message matching `{channel?, from?, subject_contains?, timeout_sec}`. Default timeout 25s. Implement by repeatedly querying GSI3 with a `since=now` cursor and sleeping 1s between polls.
Tests: wait returns found message when pre-seeded, returns timeout when none arrive, filter `channel=email` restricts correctly.
**Commit:** `feat(phase1): wait long-poll for channel-agnostic next-inbound`

### 24f: otp
Route: `POST /v1/agents/{id}/extract-otp` — pulls recent DMs (default: last 10 min), runs OTP regexes against bodies (`\b\d{4,8}\b` filtered against the surrounding "code|OTP|verification" words), returns the most recent match.
Tests: OTP extracted from email body, OTP extracted from SMS body (channel-agnostic), no-match returns 404.
**Commit:** `feat(phase1): extract-otp handler — channel-agnostic OTP recovery`

Each of 24a–24f should follow the same TDD rhythm as Tasks 22 and 23: write the tests first, run them red, implement, run green, commit.

---

## Task 25: CDK API stack (`agentcomms-api-stack.ts`)

**Files:**
- Create: `cdk/lib/stacks/agentcomms-api-stack.ts`
- Modify: `cdk/bin/app.ts` (instantiate)
- Create: `cdk/test/agentcomms-api-stack.test.ts`

Deliver: a TypeScript CDK stack that creates an API Gateway REST API with:
- Lambda authorizer pointing at `core.api.authorizer:lambda_handler` (you'll need a thin Lambda wrapper for the authorizer in `core/api/authorizer.py` exporting `lambda_handler(event, context)`).
- Routes wired to the handler Lambdas (one Lambda per handler file, or one shared Lambda that dispatches by path — choose one-Lambda-per-handler for clearer IAM scoping).
- Custom domain `api.agentcomms.dev` with ACM cert (add cert in us-east-1).

**Steps:**
1. Write failing CDK assertion test checking route count and authorizer presence.
2. Implement stack — one Lambda per handler: agents, channels, messages, threads, drafts, webhooks, wait, otp.
3. Wire routes: see `core/api/*` file list; every handler covers its own subtree.
4. Pass table name, event stream, and bucket names via env vars (from the data stack outputs).
5. Run `npx cdk synth AgentCommsApi` and verify no errors.
6. Commit: `feat(phase1): AgentComms API stack (API Gateway + 8 handler Lambdas + authorizer)`

---

## Task 26: CDK adapters stack (`agentcomms-adapters-stack.ts`)

**Files:**
- Create: `cdk/lib/stacks/agentcomms-adapters-stack.ts`

This stack is a thin orchestrator: it iterates manifest.toml files under `adapters/` at synth time and instantiates each adapter's declared CDK construct. For Phase 1, only `adapters/email/` ships, so the iteration concretely instantiates `EmailAdapterStack`.

**Steps:**
1. Implement as a Stack that reads `adapters/*/manifest.toml` during synth (via `fs.readdirSync` + `toml` package), and for each `cdk_stack` reference dynamically imports + instantiates.
2. In Phase 1 practice: only email is present, so explicitly instantiate `EmailAdapterStack` with props from the data/events stacks.
3. Write a CDK assertion test that confirms email resources appear (SES rule set, SNS topic, 2 Lambdas, 1 SQS queue).
4. Commit: `feat(phase1): AgentComms adapters stack (wires email adapter; extensible for later channels)`

---

## Task 27: Deploy to staging + verify

**Files:** none — deployment only.

**Steps:**
1. From repo root:
   ```bash
   cd cdk && npx cdk deploy AgentCommsData AgentCommsEvents AgentCommsApi AgentCommsAdapters --require-approval never
   cd ..
   ```
2. Record outputs (API URL, table ARN, SNS topic ARN).
3. Verify:
   - `aws dynamodb describe-table --table-name agentcomms` shows 7 GSIs, `PointInTimeRecovery` = ENABLED.
   - `aws ses list-identities` includes `agentcomms.dev` (or a verified test domain).
   - API Gateway returns 401 for requests without an API key.
4. Seed an org + admin key via a one-off script `tools/seed_first_org.py` (simple: call `repo.put_organization` + `repo.put_api_key`).
5. Commit any fixes needed: `chore(phase1): post-deploy seed script + small stack adjustments`.

---

## Task 28: End-to-end integration test — round-trip email

**Files:**
- Create: `tests/e2e/test_email_roundtrip.py`

The E2E test exercises the full Phase 1 surface against moto (no real AWS required):
1. Create Organization + API key.
2. POST /v1/agents with email provision → get agent_id + channel_id.
3. Simulate SES inbound: drop MIME bytes in the raw-inbound S3 bucket; trigger the `adapters.email.ingest.handler` directly with a synthesized SNS event.
4. GET /v1/agents/{id}/messages → assert one DM appears.
5. POST /v1/agents/{id}/messages with `{to, body}` → assert EmailAdapter.send was called; outbound UnifiedMessage persisted with status=sent.
6. GET /v1/agents/{id}/messages → assert 2 messages now (1 inbound + 1 outbound), both is_dm.

**Steps:**
1. Write the failing test.
2. Run red.
3. Fix any wiring issues discovered (most likely: the ingest handler's S3 GetObject needs mocking).
4. Run green.
5. Commit: `test(phase1): E2E email round-trip via moto — provision → receive → send`

---

## Task 29: Phase 1 final verification

**Steps:**

1. **All tests green:**
   ```bash
   pytest -x -q
   cd cdk && npx jest && cd ..
   ```
2. **CDK synth clean on all new stacks:**
   ```bash
   cd cdk && npx cdk synth AgentCommsData AgentCommsEvents AgentCommsApi AgentCommsAdapters && cd ..
   ```
3. **Lint/type-check:**
   ```bash
   python -m mypy core/ adapters/ --strict --ignore-missing-imports
   cd cdk && npx tsc --noEmit && cd ..
   ```
4. **Test count sanity check:** target at minimum: ~120 Python tests passing, ~15 CDK tests passing. Actual can vary; flag wildly-off numbers.

5. **Commit final Phase 1 tag:**
   ```bash
   git commit --allow-empty -m "chore(phase1): foundation complete — ready to merge"
   git tag -a phase1-complete -m "AgentComms Phase 1 (Foundation) — complete and all-green"
   ```

6. **Open PR to `main` for review.**

**Phase 1 Exit Criteria Checklist:**
- [ ] `agentcomms` DynamoDB table deployed with all 7 GSIs; PITR on
- [ ] `POST /v1/agents` with email provision creates Agent + Channel + SES identity
- [ ] Inbound email via `adapters.email.ingest.handler` normalizes and writes UnifiedMessage with `is_dm=True`
- [ ] `GET /v1/agents/{id}/messages` returns unified inbox via one GSI3 query (no filter scan)
- [ ] `POST /v1/agents/{id}/messages` with unadorned `{to, body}` routes via address format and calls the correct adapter
- [ ] All 6 handlers from Task 24 (+ Tasks 22, 23) have passing tests
- [ ] E2E round-trip test (Task 28) passes
- [ ] Old `victorymail` stacks untouched and still running

---

## Self-review — checked against the spec

- **Spec §2 (Data model):** Organization, Agent, Channel, UnifiedMessage, ApiKey, Thread, Draft, Webhook, Attachment — Tasks 4–8 cover all 9 entities. GSI1–GSI7 all declared in Task 15. ✅
- **Spec §3 (REST API):** Agents + Channels + Messages + Threads + Drafts + Webhooks + Wait + OTP + AI all listed; Phase 1 covers all except AI (deferred to Phase 2). Domains CRUD is not covered — add to Phase 2. ⚠️ *noted.*
- **Spec §4 (Adapter SDK):** ChannelAdapter ABC (Task 12), registry (Task 13), manifest.toml (Task 18), cdk_wiring doc-tied to email stack (Task 19). ✅
- **Spec §5 (Bootstrap CLI, AGENT.md, FSL license):** Deferred to Phase 4. ✅
- **Spec §6 (Migration):** Phase 5 — not in Phase 1. ✅
- **Spec §7 (v0.1 scope):** Phase 1 covers email only (v0.1 scope includes 5 channels). Remaining channels covered in Phases 2 & 3. ✅

**Gaps flagged for subsequent phases' plan authors:**
- Domains endpoint (`/v1/domains`) — add to Phase 2 plan.
- AI features (`/v1/agents/{id}/ai/*`) — add to Phase 2 plan.
- Vault + Personas `/v1/vault`, `/v1/personas` — add to Phase 2 plan.
- The spec's 8 "Open questions" (Section 8) should be addressed at the start of Phase 4 or wherever they intersect the work.

*Phase 1 plan complete. Total tasks: 29. Estimated calendar: 2–3 weeks for a focused solo engineer; proportionally less with subagent-driven execution across parallel tasks where possible (e.g., 24a–24f can partially parallelize).*


