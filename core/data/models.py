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
