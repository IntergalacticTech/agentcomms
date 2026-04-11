"""Stripe billing handler for FreeMail Pro subscriptions."""

import json
import os

import stripe

from shared.auth import get_org_id
from shared.dynamo import get_item, update_item
from shared.models import now_iso, org_keys
from shared.response import bad_request, error, success
from shared.validation import parse_body

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.environ.get("STRIPE_PRICE_ID", "")
CONSOLE_URL = os.environ.get("CONSOLE_URL", "https://console.victorymail.dev")

FREE_QUOTAS = {
    "max_inboxes": 5,
    "max_messages_per_day": 1000,
    "max_api_keys": 5,
    "max_pods": 3,
    "max_domains": 1,
    "max_webhooks": 5,
}

PRO_QUOTAS = {
    "max_inboxes": 1000,
    "max_messages_per_day": 50000,
    "max_api_keys": 50,
    "max_pods": 50,
    "max_domains": 10,
    "max_webhooks": 50,
}


def handler(event, context):
    """Route billing requests to the appropriate handler."""
    path = event.get("path", "")
    method = event.get("httpMethod", "")

    if path.endswith("/webhook") and method == "POST":
        return handle_webhook(event)
    elif path.endswith("/checkout") and method == "POST":
        return handle_checkout(event)
    elif path.endswith("/portal") and method == "POST":
        return handle_portal(event)
    elif path.endswith("/status") and method == "GET":
        return handle_status(event)
    return bad_request("Not found")


def handle_checkout(event):
    """Create a Stripe Checkout session for upgrading to Pro."""
    org_id = get_org_id(event)
    if not org_id:
        return error("UNAUTHORIZED", "Authentication required", 401)

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return error("NOT_FOUND", "Organization not found", 404)

    customer_email = org.get("email", "")
    if not customer_email:
        return bad_request("Organization has no email address")

    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        customer_email=customer_email,
        metadata={"org_id": org_id},
        success_url=f"{CONSOLE_URL}/billing?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{CONSOLE_URL}/billing?canceled=true",
    )

    return success({"checkout_url": session.url})


def handle_portal(event):
    """Create a Stripe Billing Portal session for managing subscription."""
    org_id = get_org_id(event)
    if not org_id:
        return error("UNAUTHORIZED", "Authentication required", 401)

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return error("NOT_FOUND", "Organization not found", 404)

    stripe_customer_id = org.get("stripe_customer_id")
    if not stripe_customer_id:
        return bad_request("No billing account found. Please subscribe first.")

    session = stripe.billing_portal.Session.create(
        customer=stripe_customer_id,
        return_url=f"{CONSOLE_URL}/billing",
    )

    return success({"portal_url": session.url})


def handle_status(event):
    """Get current billing status for the org."""
    org_id = get_org_id(event)
    if not org_id:
        return error("UNAUTHORIZED", "Authentication required", 401)

    keys = org_keys(org_id)
    org = get_item(keys["PK"], keys["SK"])
    if not org:
        return error("NOT_FOUND", "Organization not found", 404)

    return success({
        "org_id": org_id,
        "tier": org.get("tier", "free"),
        "billing_status": org.get("billing_status", "none"),
        "stripe_customer_id": org.get("stripe_customer_id"),
    })


def handle_webhook(event):
    """Handle Stripe webhook events. No auth required -- verified by signature."""
    payload = event.get("body", "")
    sig_header = (event.get("headers") or {}).get("Stripe-Signature", "")

    try:
        webhook_event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        return bad_request("Invalid payload")
    except stripe.SignatureVerificationError:
        return error("UNAUTHORIZED", "Invalid signature", 401)

    event_type = webhook_event["type"]
    data = webhook_event["data"]["object"]

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data)
    elif event_type == "invoice.payment_failed":
        _handle_payment_failed(data)

    return success({"received": True})


def _handle_checkout_completed(session):
    """Upgrade org to Pro after successful checkout."""
    org_id = session.get("metadata", {}).get("org_id")
    if not org_id:
        return

    customer_id = session.get("customer")
    keys = org_keys(org_id)
    update_item(keys["PK"], keys["SK"], {
        "tier": "pro",
        "billing_status": "active",
        "stripe_customer_id": customer_id,
        "billing_channel": "stripe",
        "quotas": PRO_QUOTAS,
        "updated_at": now_iso(),
    })


def _handle_subscription_updated(subscription):
    """Update org status based on subscription status."""
    customer_id = subscription.get("customer")
    org_id = _find_org_id_by_customer(customer_id)
    if not org_id:
        return

    status = subscription.get("status", "")
    keys = org_keys(org_id)

    billing_status = status  # active, past_due, canceled, etc.
    updates = {
        "billing_status": billing_status,
        "updated_at": now_iso(),
    }

    # If subscription becomes active again, ensure pro tier
    if status == "active":
        updates["tier"] = "pro"
        updates["quotas"] = PRO_QUOTAS

    update_item(keys["PK"], keys["SK"], updates)


def _handle_subscription_deleted(subscription):
    """Downgrade org to free tier when subscription is canceled."""
    customer_id = subscription.get("customer")
    org_id = _find_org_id_by_customer(customer_id)
    if not org_id:
        return

    keys = org_keys(org_id)
    update_item(keys["PK"], keys["SK"], {
        "tier": "free",
        "billing_status": "canceled",
        "quotas": FREE_QUOTAS,
        "updated_at": now_iso(),
    })


def _handle_payment_failed(invoice):
    """Mark org billing as past_due on payment failure."""
    customer_id = invoice.get("customer")
    org_id = _find_org_id_by_customer(customer_id)
    if not org_id:
        return

    keys = org_keys(org_id)
    update_item(keys["PK"], keys["SK"], {
        "billing_status": "past_due",
        "updated_at": now_iso(),
    })


def _find_org_id_by_customer(customer_id):
    """Look up org_id from stripe_customer_id.

    Scans the table for an org with the given stripe_customer_id.
    In production, consider adding a GSI for this lookup.
    """
    if not customer_id:
        return None

    from shared.dynamo import _get_table

    table = _get_table()
    resp = table.scan(
        FilterExpression="stripe_customer_id = :cid AND begins_with(PK, :prefix)",
        ExpressionAttributeValues={
            ":cid": customer_id,
            ":prefix": "ORG#",
        },
        Limit=1,
    )
    items = resp.get("Items", [])
    if items:
        return items[0].get("id")
    return None
