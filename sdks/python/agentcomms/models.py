# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""Pydantic models mirroring AgentComms API response shapes."""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ChannelDetails(BaseModel):
    """Channel-specific details; contents vary by channel type."""
    model_config = {"extra": "allow"}

    address: Optional[str] = None
    phone_e164: Optional[str] = None
    bot_username: Optional[str] = None
    oauth_url: Optional[str] = None
    status: Optional[str] = None


class Channel(BaseModel):
    channel_id: str
    channel: str
    agent_id: str
    mode: Optional[str] = None
    status: Optional[str] = None
    details: Optional[ChannelDetails] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Agent(BaseModel):
    agent_id: str
    org_id: Optional[str] = None
    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    channels: list[Channel] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Recipient(BaseModel):
    address: Optional[str] = None
    display_name: Optional[str] = None
    platform_user_id: Optional[str] = None


class Message(BaseModel):
    message_id: str
    agent_id: str
    channel_id: Optional[str] = None
    channel: Optional[str] = None
    direction: Optional[str] = None
    status: Optional[str] = None
    from_: Optional[Recipient] = Field(None, alias="from")
    to: list[Recipient] = Field(default_factory=list)
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    thread_key: Optional[str] = None
    is_dm: bool = False
    received_at: Optional[str] = None
    created_at: Optional[str] = None
    channel_native: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class Thread(BaseModel):
    thread_key: str
    agent_id: str
    channel: Optional[str] = None
    message_count: int = 0
    last_message_at: Optional[str] = None
    created_at: Optional[str] = None


class Draft(BaseModel):
    draft_id: str
    agent_id: str
    channel: Optional[str] = None
    to: Optional[str] = None
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class Webhook(BaseModel):
    webhook_id: str
    agent_id: str
    url: str
    events: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class VaultItem(BaseModel):
    model_config = {"extra": "allow"}

    vault_id: str
    org_id: str
    label: Optional[str] = None
    type: str = "secret"
    value: Optional[str] = None
    tags: dict[str, Any] = Field(default_factory=dict)
    kms_key_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def name(self) -> Optional[str]:
        return self.label or (self.__pydantic_extra__ or {}).get("name")


class Persona(BaseModel):
    persona_id: str
    org_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class Domain(BaseModel):
    model_config = {"extra": "allow"}

    domain_id: str
    org_id: str
    domain_name: Optional[str] = None
    status: Optional[str] = None
    dkim_tokens: list[str] = Field(default_factory=list)
    dkim_verified: bool = False
    spf_verified: bool = False
    mx_verified: bool = False
    dmarc_verified: bool = False
    dns_records: dict[str, Any] = Field(default_factory=dict)
    verified_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @property
    def domain(self) -> Optional[str]:
        return self.domain_name or (self.__pydantic_extra__ or {}).get("domain")
