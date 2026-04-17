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
