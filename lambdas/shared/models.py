"""DynamoDB key builders for all FreeMail entities."""

from datetime import datetime, timezone


def now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Org
# ---------------------------------------------------------------------------

def org_keys(org_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"ORG#{org_id}"}


# ---------------------------------------------------------------------------
# API Key
# ---------------------------------------------------------------------------

def api_key_keys(org_id: str, key_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"APIKEY#{key_id}"}


def api_key_gsi1(key_hash: str, key_id: str) -> dict:
    return {"GSI1PK": f"APIKEY#{key_hash}", "GSI1SK": f"APIKEY#{key_id}"}


# ---------------------------------------------------------------------------
# Pod
# ---------------------------------------------------------------------------

def pod_keys(org_id: str, pod_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"POD#{pod_id}"}


def pod_gsi1(org_id: str, pod_id: str) -> dict:
    return {"GSI1PK": f"ORG#{org_id}#PODS", "GSI1SK": f"POD#{pod_id}"}


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def inbox_keys(org_id: str, inbox_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"INBOX#{inbox_id}"}


def inbox_gsi1(pod_id: str, inbox_id: str) -> dict:
    return {"GSI1PK": f"POD#{pod_id}#INBOXES", "GSI1SK": f"INBOX#{inbox_id}"}


def inbox_gsi2(email_address: str, inbox_id: str) -> dict:
    return {"GSI2PK": f"EMAIL#{email_address}", "GSI2SK": f"INBOX#{inbox_id}"}


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

def message_keys(inbox_id: str, message_id: str) -> dict:
    return {"PK": f"INBOX#{inbox_id}", "SK": f"MSG#{message_id}"}


def message_gsi1(thread_id: str, message_id: str) -> dict:
    return {"GSI1PK": f"THREAD#{thread_id}", "GSI1SK": f"MSG#{message_id}"}


def message_gsi3(org_id: str, message_id: str) -> dict:
    return {"GSI3PK": f"ORG#{org_id}#MSGS", "GSI3SK": f"MSG#{message_id}"}


def message_gsi6(ses_message_id: str, message_id: str) -> dict:
    return {"GSI6PK": f"SES#{ses_message_id}", "GSI6SK": f"MSG#{message_id}"}


# ---------------------------------------------------------------------------
# Thread
# ---------------------------------------------------------------------------

def thread_keys(inbox_id: str, thread_id: str) -> dict:
    return {"PK": f"INBOX#{inbox_id}", "SK": f"THREAD#{thread_id}"}


def thread_gsi1(inbox_id: str, thread_id: str) -> dict:
    return {"GSI1PK": f"INBOX#{inbox_id}#THREADS", "GSI1SK": f"THREAD#{thread_id}"}


# ---------------------------------------------------------------------------
# Draft
# ---------------------------------------------------------------------------

def draft_keys(inbox_id: str, draft_id: str) -> dict:
    return {"PK": f"INBOX#{inbox_id}", "SK": f"DRAFT#{draft_id}"}


def draft_gsi1(inbox_id: str, draft_id: str) -> dict:
    return {"GSI1PK": f"INBOX#{inbox_id}#DRAFTS", "GSI1SK": f"DRAFT#{draft_id}"}


# ---------------------------------------------------------------------------
# Domain
# ---------------------------------------------------------------------------

def domain_keys(org_id: str, domain_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"DOMAIN#{domain_id}"}


def domain_gsi1(domain_name: str, domain_id: str) -> dict:
    return {"GSI1PK": f"DOMAIN#{domain_name}", "GSI1SK": f"DOMAIN#{domain_id}"}


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------

def webhook_keys(org_id: str, webhook_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"WEBHOOK#{webhook_id}"}


def webhook_gsi1(org_id: str, webhook_id: str) -> dict:
    return {"GSI1PK": f"ORG#{org_id}#WEBHOOKS", "GSI1SK": f"WEBHOOK#{webhook_id}"}


# ---------------------------------------------------------------------------
# Attachment
# ---------------------------------------------------------------------------

def attachment_keys(message_id: str, attachment_id: str) -> dict:
    return {"PK": f"MSG#{message_id}", "SK": f"ATTACH#{attachment_id}"}


# ---------------------------------------------------------------------------
# Mailing List
# ---------------------------------------------------------------------------

def list_keys(org_id: str, list_id: str) -> dict:
    return {"PK": f"ORG#{org_id}", "SK": f"LIST#{list_id}"}


def list_member_keys(list_id: str, email_address: str) -> dict:
    return {"PK": f"LIST#{list_id}", "SK": f"MEMBER#{email_address}"}


def list_gsi1(org_id: str, list_id: str) -> dict:
    return {"GSI1PK": f"ORG#{org_id}#LISTS", "GSI1SK": f"LIST#{list_id}"}
