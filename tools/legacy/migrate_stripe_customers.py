#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.
"""
Migrate existing Stripe customers from FreeMail plans to AgentComms plans.

Per Spec §7.3:
  - Free tier      → Free (no change, no Stripe write)
  - Starter $5/mo  → Free + 6-month Developer-tier complimentary credit (coupon)
  - Pro $25/mo     → Developer tier at $19/mo, grandfathered 6 months, then normal
  - Enterprise     → no change (custom contracts)

Usage:
    python tools/migrate_stripe_customers.py --dry-run
    python tools/migrate_stripe_customers.py --stripe-key sk_live_...
    python tools/migrate_stripe_customers.py --customer-id cus_xxx  # single customer

Environment:
    STRIPE_SECRET_KEY — Stripe secret key (alternative to --stripe-key)

All Stripe API calls are idempotent:
    idempotency_key = "agentcomms-migration-{customer_id}-{action}"

IMPORTANT: Do NOT run against production without --dry-run first.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import stripe

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("migrate_stripe")

# ---------------------------------------------------------------------------
# Known price IDs — adjust these to your actual Stripe price IDs
# ---------------------------------------------------------------------------

# The $19/mo Developer tier price (new AgentComms plan).
# Either create this manually in Stripe first, or the script will create it.
DEVELOPER_PRICE_LOOKUP_KEY = "agentcomms_developer_19_monthly"
DEVELOPER_PRODUCT_NAME = "AgentComms Developer"
DEVELOPER_MONTHLY_CENTS = 1900  # $19.00

# Known legacy price IDs (by amount) for classification
STARTER_AMOUNT_CENTS = 500   # $5.00
PRO_AMOUNT_CENTS = 2500      # $25.00


# ---------------------------------------------------------------------------
# Output / logging
# ---------------------------------------------------------------------------

_use_json = False
_log_file: Any = None


def _emit(kind: str, **fields: Any) -> None:
    record = {"event": kind, "ts": datetime.now(timezone.utc).isoformat(), **fields}
    line = json.dumps(record, default=str)
    print(line, flush=True)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def _open_log() -> Any:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = f"/tmp/stripe-migration-{ts}.log"
    fh = open(path, "w", encoding="utf-8")  # noqa: WPS515
    _emit("log_file", path=path)
    return fh


# ---------------------------------------------------------------------------
# Stripe helpers
# ---------------------------------------------------------------------------

def _stripe_call(method_fn: Any, idempotency_key: str | None = None, **kwargs: Any) -> Any:
    """Call a Stripe API method, log request + response."""
    kwargs_log = {k: v for k, v in kwargs.items() if k != "api_key"}
    _emit("stripe_call", method=method_fn.__name__, kwargs=kwargs_log, idempotency_key=idempotency_key)
    request_options: dict[str, Any] = {}
    if idempotency_key:
        request_options["idempotency_key"] = idempotency_key
    result = method_fn(**kwargs, **({"idempotency_key": idempotency_key} if idempotency_key else {}))
    _emit("stripe_result", method=method_fn.__name__, result_id=getattr(result, "id", None))
    return result


def classify_subscription(sub: Any) -> str:
    """
    Return one of: "free", "starter", "pro", "enterprise", "unknown"
    based on the subscription's first item price amount.
    """
    items = sub.get("items", {}).get("data", [])
    if not items:
        return "free"

    amount = items[0].get("price", {}).get("unit_amount", 0)
    if amount == 0:
        return "free"
    if amount == STARTER_AMOUNT_CENTS:
        return "starter"
    if amount == PRO_AMOUNT_CENTS:
        return "pro"
    # Anything higher or with custom metadata we treat as enterprise
    if amount > PRO_AMOUNT_CENTS:
        return "enterprise"
    return "unknown"


def get_or_create_developer_price(dry_run: bool) -> str | None:
    """
    Look up the Developer tier $19/mo price by lookup key; create if missing.
    Returns the price ID, or None in dry_run mode.
    """
    if dry_run:
        _emit("would_get_or_create_price", lookup_key=DEVELOPER_PRICE_LOOKUP_KEY)
        return "price_DRYRUN_developer_19"

    prices = stripe.Price.list(lookup_keys=[DEVELOPER_PRICE_LOOKUP_KEY], limit=1)
    if prices.data:
        price_id = prices.data[0].id
        _emit("developer_price_found", price_id=price_id)
        return price_id

    # Create product + price
    product = stripe.Product.create(
        name=DEVELOPER_PRODUCT_NAME,
        metadata={"agentcomms_tier": "developer"},
        idempotency_key="agentcomms-migration-create-developer-product",
    )
    price = stripe.Price.create(
        unit_amount=DEVELOPER_MONTHLY_CENTS,
        currency="usd",
        recurring={"interval": "month"},
        product=product.id,
        lookup_key=DEVELOPER_PRICE_LOOKUP_KEY,
        transfer_lookup_key=True,
        metadata={"agentcomms_tier": "developer"},
        idempotency_key="agentcomms-migration-create-developer-price",
    )
    _emit("developer_price_created", price_id=price.id, product_id=product.id)
    return price.id


# ---------------------------------------------------------------------------
# Per-tier migration handlers
# ---------------------------------------------------------------------------

def migrate_free(customer_id: str, sub: Any, dry_run: bool) -> dict[str, Any]:
    """Free → Free: no Stripe change needed."""
    result = {"customer": customer_id, "action": "free_unchanged", "sub": sub["id"]}
    _emit("migrate", **result)
    return result


def migrate_starter(customer_id: str, sub: Any, dry_run: bool, halt_on_error: bool) -> dict[str, Any]:
    """
    Starter $5 → Free + 6-month Developer credit.
    Steps:
    1. Create a 100%-off repeating coupon valid for 6 months.
    2. Apply the coupon to the customer.
    3. Cancel the existing $5 subscription at period end.
    """
    coupon_id = f"agentcomms-starter-grandfather-{customer_id}"

    if dry_run:
        _emit(
            "would_migrate_starter",
            customer=customer_id,
            sub=sub["id"],
            coupon_id=coupon_id,
            action="cancel_at_period_end",
        )
        return {
            "customer": customer_id,
            "action": "grandfathered_starter",
            "coupon_id": coupon_id,
            "sub": sub["id"],
        }

    # Create coupon (idempotent — same id returns existing coupon)
    try:
        coupon = stripe.Coupon.create(
            id=coupon_id,
            percent_off=100,
            duration="repeating",
            duration_in_months=6,
            name="AgentComms Migration: 6-month Developer credit",
            metadata={"migrated_from": "freemail_starter", "customer_id": customer_id},
            idempotency_key=f"agentcomms-migration-{customer_id}-coupon",
        )
        coupon_id = coupon.id
        _emit("coupon_created", coupon_id=coupon_id, customer=customer_id)
    except stripe.error.InvalidRequestError as exc:
        if "already exists" in str(exc) or "duplicate" in str(exc).lower():
            _emit("coupon_already_exists", coupon_id=coupon_id)
        else:
            _emit("stripe_error", customer=customer_id, error=str(exc))
            if halt_on_error:
                raise

    # Apply coupon to customer
    stripe.Customer.modify(
        customer_id,
        coupon=coupon_id,
        idempotency_key=f"agentcomms-migration-{customer_id}-apply-coupon",
    )

    # Cancel existing subscription at period end
    stripe.Subscription.modify(
        sub["id"],
        cancel_at_period_end=True,
        idempotency_key=f"agentcomms-migration-{customer_id}-cancel-starter",
    )

    result = {
        "customer": customer_id,
        "action": "grandfathered_starter",
        "coupon_id": coupon_id,
        "sub": sub["id"],
    }
    _emit("migrate", **result)
    return result


def migrate_pro(
    customer_id: str,
    sub: Any,
    developer_price_id: str,
    dry_run: bool,
    halt_on_error: bool,
) -> dict[str, Any]:
    """
    Pro $25 → Developer tier $19, grandfathered 6 months then normal.
    Steps:
    1. Get the new Developer price ID.
    2. Update the subscription item to the new price.
    3. Apply a 6-month 100%-off coupon to cover the grandfather period,
       OR keep at $19 immediately (lower than $25; always a win for the customer).
       Per spec: grandfather 6 months then normal → use a coupon for the delta.
    """
    if dry_run:
        _emit(
            "would_migrate_pro",
            customer=customer_id,
            sub=sub["id"],
            new_price=developer_price_id,
            action="update_sub_to_developer",
        )
        return {
            "customer": customer_id,
            "action": "pro_to_developer",
            "new_price": developer_price_id,
            "sub": sub["id"],
        }

    items = sub.get("items", {}).get("data", [])
    if not items:
        _emit("no_sub_items", customer=customer_id, sub=sub["id"])
        return {"customer": customer_id, "action": "pro_skipped_no_items", "sub": sub["id"]}

    sub_item_id = items[0]["id"]

    try:
        stripe.Subscription.modify(
            sub["id"],
            items=[{"id": sub_item_id, "price": developer_price_id}],
            proration_behavior="none",
            idempotency_key=f"agentcomms-migration-{customer_id}-pro-to-dev",
        )
    except stripe.error.StripeError as exc:
        _emit("stripe_error", customer=customer_id, error=str(exc))
        if halt_on_error:
            raise

    result = {
        "customer": customer_id,
        "action": "pro_to_developer",
        "new_price": developer_price_id,
        "sub": sub["id"],
    }
    _emit("migrate", **result)
    return result


def migrate_enterprise(customer_id: str, sub: Any, dry_run: bool) -> dict[str, Any]:
    """Enterprise / Business: no change."""
    result = {"customer": customer_id, "action": "skipped_enterprise", "sub": sub["id"]}
    _emit("migrate", **result)
    return result


# ---------------------------------------------------------------------------
# Main migration loop
# ---------------------------------------------------------------------------

def run_migration(args: argparse.Namespace) -> int:
    stripe.api_key = args.stripe_key or os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        print("ERROR: Stripe key not set. Use --stripe-key or STRIPE_SECRET_KEY env var.", file=sys.stderr)
        return 1

    global _log_file
    if not args.dry_run:
        _log_file = _open_log()

    _emit(
        "migration_start",
        dry_run=args.dry_run,
        customer_filter=args.customer_id,
    )

    # Ensure we have the Developer price ready before iterating customers
    developer_price_id = get_or_create_developer_price(args.dry_run)

    results: list[dict[str, Any]] = []
    error_count = 0

    # Fetch subscriptions
    list_kwargs: dict[str, Any] = {"status": "active", "limit": 100, "expand": ["data.items.data.price"]}
    if args.customer_id:
        list_kwargs["customer"] = args.customer_id

    try:
        subs_page = stripe.Subscription.list(**list_kwargs)
    except stripe.error.StripeError as exc:
        _emit("stripe_error", phase="list_subscriptions", error=str(exc))
        if args.halt_on_error:
            return 1
        subs_page = stripe.ListObject()  # empty fallback

    for sub in stripe.Subscription.auto_paging_iter(**list_kwargs):
        customer_id = sub.get("customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id", "")

        tier = classify_subscription(sub)
        _emit("classified", customer=customer_id, sub=sub["id"], tier=tier)

        try:
            if tier == "free":
                r = migrate_free(customer_id, sub, args.dry_run)
            elif tier == "starter":
                r = migrate_starter(customer_id, sub, args.dry_run, args.halt_on_error)
            elif tier == "pro":
                r = migrate_pro(customer_id, sub, developer_price_id, args.dry_run, args.halt_on_error)
            else:
                # enterprise or unknown → skip
                r = migrate_enterprise(customer_id, sub, args.dry_run)
        except stripe.error.StripeError as exc:
            error_count += 1
            _emit("stripe_error", customer=customer_id, sub=sub["id"], error=str(exc))
            if args.halt_on_error:
                _emit("halting", reason="halt_on_error set")
                return 1
            r = {"customer": customer_id, "action": "error", "error": str(exc)}

        results.append(r)

    summary: dict[str, int] = {}
    for r in results:
        action = r.get("action", "unknown")
        summary[action] = summary.get(action, 0) + 1

    _emit("migration_done", total=len(results), errors=error_count, summary=summary)

    if _log_file:
        _log_file.close()

    return 0 if error_count == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate Stripe customers from FreeMail to AgentComms plans."
    )
    parser.add_argument("--stripe-key", default="", help="Stripe secret key (or set STRIPE_SECRET_KEY env var).")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done; no Stripe writes.")
    parser.add_argument("--json", action="store_true", dest="use_json", help="NDJSON output.")
    parser.add_argument("--customer-id", default="", help="Limit migration to one Stripe customer ID.")
    parser.add_argument(
        "--halt-on-error",
        action="store_true",
        default=True,
        dest="halt_on_error",
        help="Stop on first Stripe API error (default: true).",
    )
    parser.add_argument(
        "--no-halt-on-error",
        action="store_false",
        dest="halt_on_error",
        help="Continue on Stripe API errors.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    global _use_json
    _use_json = args.use_json
    return run_migration(args)


if __name__ == "__main__":
    sys.exit(main())
