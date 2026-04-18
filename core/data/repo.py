# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/data/repo.py
"""
Single-table repository for AgentComms DynamoDB.

Encapsulates all DynamoDB access so handlers never build PK/SK strings or touch
boto3 directly. Use this in Lambda handlers by instantiating with a real
DynamoDB Table; use in tests with a moto-backed Table fixture.
"""
from __future__ import annotations

from typing import Any

from boto3.dynamodb.conditions import Key, Attr

from core.data.models import (
    Agent, ApiKey, Channel, Domain, DomainStatus, Draft, Organization,
    Persona, Thread, UnifiedMessage, VaultItem, VaultType, Webhook,
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

    def find_message_by_id(self, *, agent_id: str, message_id: str) -> UnifiedMessage | None:
        """Scan-like query to find a message by message_id without knowing its timestamp.

        Queries PK=AGT#{agent_id} with SK begins_with "MSG#" and a FilterExpression
        on message_id. Suitable for low-frequency AI/admin operations.
        """
        resp = self.table.query(
            KeyConditionExpression=(
                Key("PK").eq(f"AGT#{agent_id}")
                & Key("SK").begins_with("MSG#")
            ),
            FilterExpression=Attr("message_id").eq(message_id),
            Limit=100,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        return UnifiedMessage.from_dynamodb_item(items[0])

    def update_message_labels(
        self, *, agent_id: str, received_at_ms: int, message_id: str, labels: list[str],
    ) -> None:
        """Add *labels* to a message item in-place (atomic list append replacement)."""
        self.table.update_item(
            Key={
                "PK": f"AGT#{agent_id}",
                "SK": f"MSG#{received_at_ms}#{message_id}",
            },
            UpdateExpression="SET labels = :l",
            ExpressionAttributeValues={":l": labels},
        )

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

    def list_thread_messages(
        self, *, thread_key: str, limit: int = 100,
    ) -> list[UnifiedMessage]:
        """GSI5 — list all messages belonging to a thread, oldest first."""
        resp = self.table.query(
            IndexName="GSI5",
            KeyConditionExpression=Key("gsi5_pk").eq(f"THR#{thread_key}"),
            ScanIndexForward=True,  # chronological order
            Limit=limit,
        )
        return [UnifiedMessage.from_dynamodb_item(i) for i in resp.get("Items", [])]

    # ─── Drafts ──────────────────────────────────────────────────────
    def put_draft(self, draft: Draft) -> None:
        self.table.put_item(Item=draft.to_dynamodb_item())

    def get_draft(self, *, agent_id: str, channel: str, draft_id: str) -> Draft | None:
        resp = self.table.get_item(
            Key={"PK": f"AGT#{agent_id}", "SK": f"DRF#{channel}#{draft_id}"}
        )
        item = resp.get("Item")
        return Draft.from_dynamodb_item(item) if item else None

    def list_drafts(self, *, agent_id: str) -> list[Draft]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"AGT#{agent_id}")
                & Key("SK").begins_with("DRF#"),
        )
        return [Draft.from_dynamodb_item(i) for i in resp.get("Items", [])]

    def delete_draft(self, *, agent_id: str, channel: str, draft_id: str) -> None:
        self.table.delete_item(
            Key={"PK": f"AGT#{agent_id}", "SK": f"DRF#{channel}#{draft_id}"}
        )

    # ─── Webhooks ────────────────────────────────────────────────────
    def put_webhook(self, webhook: Webhook) -> None:
        self.table.put_item(Item=webhook.to_dynamodb_item())

    def get_webhook(self, *, agent_id: str, webhook_id: str) -> Webhook | None:
        resp = self.table.get_item(
            Key={"PK": f"AGT#{agent_id}", "SK": f"WHK#{webhook_id}"}
        )
        item = resp.get("Item")
        return Webhook.from_dynamodb_item(item) if item else None

    def list_webhooks(self, *, agent_id: str) -> list[Webhook]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"AGT#{agent_id}")
                & Key("SK").begins_with("WHK#"),
        )
        return [Webhook.from_dynamodb_item(i) for i in resp.get("Items", [])]

    def delete_webhook(self, *, agent_id: str, webhook_id: str) -> None:
        self.table.delete_item(
            Key={"PK": f"AGT#{agent_id}", "SK": f"WHK#{webhook_id}"}
        )

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

    # ─── Vault ───────────────────────────────────────────────────────
    def put_vault(self, item: VaultItem) -> None:
        self.table.put_item(Item=item.to_dynamodb_item())

    def get_vault(self, *, org_id: str, vault_id: str) -> VaultItem | None:
        resp = self.table.get_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"VLT#{vault_id}"}
        )
        raw = resp.get("Item")
        return VaultItem.from_dynamodb_item(raw) if raw else None

    def list_vault(
        self,
        *,
        org_id: str,
        type: VaultType | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[VaultItem]:
        """List vault items for an org, optionally filtered by type or tag.

        ``tag`` should be a ``key:value`` string, e.g. ``agent_id:agt_1``.
        """
        if type is not None:
            # GSI1: ORG#{org_id}#VAULT / TYPE#{type}#VLT#{…}
            resp = self.table.query(
                IndexName="GSI1",
                KeyConditionExpression=(
                    Key("gsi1_pk").eq(f"ORG#{org_id}#VAULT")
                    & Key("gsi1_sk").begins_with(f"TYPE#{type.value}#")
                ),
                Limit=limit,
            )
        else:
            resp = self.table.query(
                KeyConditionExpression=(
                    Key("PK").eq(f"ORG#{org_id}")
                    & Key("SK").begins_with("VLT#")
                ),
                Limit=limit,
            )
        items = [VaultItem.from_dynamodb_item(i) for i in resp.get("Items", [])]
        if tag:
            key, _, value = tag.partition(":")
            items = [i for i in items if i.tags.get(key) == value]
        return items

    def delete_vault(self, *, org_id: str, vault_id: str) -> None:
        self.table.delete_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"VLT#{vault_id}"}
        )

    # ─── Personas ────────────────────────────────────────────────────
    def put_persona(self, persona: Persona) -> None:
        self.table.put_item(Item=persona.to_dynamodb_item())

    def get_persona(self, *, org_id: str, persona_id: str) -> Persona | None:
        resp = self.table.get_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"PER#{persona_id}"}
        )
        raw = resp.get("Item")
        return Persona.from_dynamodb_item(raw) if raw else None

    def list_personas(self, *, org_id: str, limit: int = 100) -> list[Persona]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"ORG#{org_id}")
                & Key("SK").begins_with("PER#"),
            Limit=limit,
        )
        return [Persona.from_dynamodb_item(i) for i in resp.get("Items", [])]

    def delete_persona(self, *, org_id: str, persona_id: str) -> None:
        self.table.delete_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"PER#{persona_id}"}
        )

    # ─── Domains ─────────────────────────────────────────────────────
    def put_domain(self, domain: Domain) -> None:
        self.table.put_item(Item=domain.to_dynamodb_item())

    def get_domain(self, *, org_id: str, domain_id: str) -> Domain | None:
        resp = self.table.get_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"DOM#{domain_id}"}
        )
        raw = resp.get("Item")
        return Domain.from_dynamodb_item(raw) if raw else None

    def list_domains(self, *, org_id: str, limit: int = 100) -> list[Domain]:
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(f"ORG#{org_id}")
                & Key("SK").begins_with("DOM#"),
            Limit=limit,
        )
        return [Domain.from_dynamodb_item(i) for i in resp.get("Items", [])]

    def delete_domain(self, *, org_id: str, domain_id: str) -> None:
        self.table.delete_item(
            Key={"PK": f"ORG#{org_id}", "SK": f"DOM#{domain_id}"}
        )

    def lookup_domain_ownership(self, domain_name: str) -> Domain | None:
        """GSI7 lookup: find which org (if any) owns *domain_name*.

        Returns the first matching Domain or None if unclaimed.
        """
        resp = self.table.query(
            IndexName="GSI7",
            KeyConditionExpression=Key("gsi7_pk").eq(f"DOMAIN#{domain_name}"),
            Limit=1,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        return Domain.from_dynamodb_item(items[0])
