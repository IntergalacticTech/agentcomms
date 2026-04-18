# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory. Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
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
    vault_id: str
    org_id: str
    name: str
    type: str = "secret"
    created_at: Optional[str] = None


class Persona(BaseModel):
    persona_id: str
    org_id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class Domain(BaseModel):
    domain_id: str
    org_id: str
    domain: str
    status: Optional[str] = None
    dkim_verified: bool = False
    created_at: Optional[str] = None
