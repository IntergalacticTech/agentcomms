# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

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
import re
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

    @classmethod
    def _missing_(cls, value: object) -> ChannelType | None:
        """Accept external adapter channel slugs without a core release.

        Known channels remain real enum members. Third-party adapters can add
        names like ``matrix``, ``smoke_signal``, or ``alien-transmission`` as
        long as the value is safe for API payloads and DynamoDB key segments.
        """
        if not isinstance(value, str):
            return None
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", value):
            return None
        member = str.__new__(cls, value)
        member._name_ = f"EXTERNAL_{value.upper().replace('-', '_')}"
        member._value_ = value
        cls._value2member_map_[value] = member
        return member


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
    labels: list[str] = Field(default_factory=list)
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
            "labels": self.labels,
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
            labels=list(item.get("labels") or []),
            received_at=datetime.fromisoformat(item["received_at"]),
            channel_native=item.get("channel_native") or {},
            external_id=item.get("external_id"),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )


class ApiKeyScope(str, Enum):
    ORG = "org"
    AGENT = "agent"
    CHANNEL = "channel"


class ApiKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key_id: str
    key_hash: str  # sha256 hex; plaintext shown once at creation
    key_prefix: str | None = None
    org_id: str
    scope: ApiKeyScope
    name: str
    agent_id: str | None = None
    channel_id: str | None = None
    revoked: bool = False
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    last_used_at: datetime | None = None

    def is_active(self, *, now: datetime | None = None) -> bool:
        """Return True when the key is neither revoked nor past its expiry.

        A missing/None ``expires_at`` never expires; ``revoked`` defaults to
        False, so pre-existing keys (which have neither field) are active.
        """
        if self.revoked:
            return False
        if self.expires_at is not None:
            now = now or _now_utc()
            expires_at = self.expires_at
            # Normalize naive stored timestamps to UTC for a safe comparison.
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                return False
        return True

    def to_dynamodb_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "PK": f"ORG#{self.org_id}",
            "SK": f"APIKEY#{self.key_hash}",
            "entity": "api_key",
            "key_id": self.key_id,
            "key_hash": self.key_hash,
            "key_prefix": self.key_prefix,
            "org_id": self.org_id,
            "scope": self.scope.value,
            "name": self.name,
            "agent_id": self.agent_id,
            "channel_id": self.channel_id,
            "revoked": self.revoked,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
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
            key_prefix=item.get("key_prefix"),
            org_id=item["org_id"],
            scope=ApiKeyScope(item["scope"]),
            name=item["name"],
            agent_id=item.get("agent_id"),
            channel_id=item.get("channel_id"),
            revoked=bool(item.get("revoked", False)),
            expires_at=datetime.fromisoformat(item["expires_at"]) if item.get("expires_at") else None,
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


class VaultType(str, Enum):
    TOTP = "totp"
    PASSWORD = "password"
    SECRET = "secret"
    API_KEY = "api_key"


class VaultItem(BaseModel):
    """Encrypted secret stored under PK=ORG#{org_id} SK=VLT#{vault_id}.

    ``encrypted_blob`` is the raw KMS CiphertextBlob (bytes), stored as
    Base64 in DynamoDB so it survives JSON/boto3 round-trips.
    ``kms_key_id`` is the KMS key ARN/ID that was used to encrypt.
    ``tags`` is a free-form dict used for filtering (e.g. ``agent_id``,
    ``persona_id``).

    GSI1 projects on ``gsi1_pk = ORG#{org_id}#VAULT`` / ``gsi1_sk =
    TYPE#{type}#VLT#{vault_id}`` so list-by-type queries are O(1).
    """
    model_config = ConfigDict(extra="forbid")

    vault_id: str
    org_id: str
    type: VaultType
    label: str
    encrypted_blob: bytes  # raw KMS ciphertext
    kms_key_id: str
    tags: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        import base64 as _b64
        return {
            "PK": f"ORG#{self.org_id}",
            "SK": f"VLT#{self.vault_id}",
            "entity": "vault_item",
            "vault_id": self.vault_id,
            "org_id": self.org_id,
            "type": self.type.value,
            "label": self.label,
            # Store ciphertext as Base64 string so it survives DynamoDB JSON encoding
            "encrypted_blob": _b64.b64encode(self.encrypted_blob).decode("ascii"),
            "kms_key_id": self.kms_key_id,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # GSI1: list-by-org-vault + sort by type
            "gsi1_pk": f"ORG#{self.org_id}#VAULT",
            "gsi1_sk": f"TYPE#{self.type.value}#VLT#{self.vault_id}",
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> VaultItem:
        import base64 as _b64
        raw = item["encrypted_blob"]
        if isinstance(raw, bytes):
            blob = raw
        else:
            blob = _b64.b64decode(raw)
        return cls(
            vault_id=item["vault_id"],
            org_id=item["org_id"],
            type=VaultType(item["type"]),
            label=item["label"],
            encrypted_blob=blob,
            kms_key_id=item["kms_key_id"],
            tags=item.get("tags") or {},
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )


class Persona(BaseModel):
    """Persistent identity profile an AI agent uses across sessions.

    Stored at PK=ORG#{org_id} SK=PER#{persona_id}.
    GSI1 projects on gsi1_pk=ORG#{org_id}#PERSONAS / gsi1_sk=PER#{persona_id}
    for efficient org-wide listing.
    """
    model_config = ConfigDict(extra="forbid")

    persona_id: str
    org_id: str
    name: str
    address: str | None = None
    dob: str | None = None          # YYYY-MM-DD
    phone: str | None = None
    email: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        return {
            "PK": f"ORG#{self.org_id}",
            "SK": f"PER#{self.persona_id}",
            "entity": "persona",
            "persona_id": self.persona_id,
            "org_id": self.org_id,
            "name": self.name,
            "address": self.address,
            "dob": self.dob,
            "phone": self.phone,
            "email": self.email,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # GSI1: list personas per org
            "gsi1_pk": f"ORG#{self.org_id}#PERSONAS",
            "gsi1_sk": f"PER#{self.persona_id}",
        }

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Persona:
        return cls(
            persona_id=item["persona_id"],
            org_id=item["org_id"],
            name=item["name"],
            address=item.get("address"),
            dob=item.get("dob"),
            phone=item.get("phone"),
            email=item.get("email"),
            metadata=item.get("metadata") or {},
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )


class DomainStatus(str, Enum):
    PENDING_DNS = "pending_dns"
    PENDING_DKIM = "pending_dkim"
    VERIFIED = "verified"
    FAILED = "failed"


class Domain(BaseModel):
    """Email domain registered for SES identity lifecycle.

    Stored at PK=ORG#{org_id} SK=DOM#{domain_id}.
    GSI7 projects on gsi7_pk=DOMAIN#{domain_name} / gsi7_sk=ORG#{org_id}
    for cross-org uniqueness enforcement.
    """
    model_config = ConfigDict(extra="forbid")

    domain_id: str
    org_id: str
    domain_name: str
    status: DomainStatus = DomainStatus.PENDING_DNS
    dkim_tokens: list[str] = Field(default_factory=list)
    spf_verified: bool = False
    mx_verified: bool = False
    dmarc_verified: bool = False
    dns_records: dict[str, Any] = Field(default_factory=dict)
    verified_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now_utc)
    updated_at: datetime = Field(default_factory=_now_utc)

    def to_dynamodb_item(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            "PK": f"ORG#{self.org_id}",
            "SK": f"DOM#{self.domain_id}",
            "entity": "domain",
            "domain_id": self.domain_id,
            "org_id": self.org_id,
            "domain_name": self.domain_name,
            "status": self.status.value,
            "dkim_tokens": self.dkim_tokens,
            "spf_verified": self.spf_verified,
            "mx_verified": self.mx_verified,
            "dmarc_verified": self.dmarc_verified,
            "dns_records": self.dns_records,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # GSI7: cross-org domain-name uniqueness
            "gsi7_pk": f"DOMAIN#{self.domain_name}",
            "gsi7_sk": f"ORG#{self.org_id}",
        }
        return item

    @classmethod
    def from_dynamodb_item(cls, item: dict[str, Any]) -> Domain:
        return cls(
            domain_id=item["domain_id"],
            org_id=item["org_id"],
            domain_name=item["domain_name"],
            status=DomainStatus(item.get("status", "pending_dns")),
            dkim_tokens=item.get("dkim_tokens") or [],
            spf_verified=bool(item.get("spf_verified", False)),
            mx_verified=bool(item.get("mx_verified", False)),
            dmarc_verified=bool(item.get("dmarc_verified", False)),
            dns_records=item.get("dns_records") or {},
            verified_at=datetime.fromisoformat(item["verified_at"]) if item.get("verified_at") else None,
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
