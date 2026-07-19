# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""
Unit tests for tools/migrate_stripe_customers.py.

Uses unittest.mock to patch Stripe SDK calls — no real Stripe account required.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import tools.legacy.migrate_stripe_customers as migrator  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers to build mock Stripe objects
# ---------------------------------------------------------------------------

def _make_price(unit_amount: int, price_id: str = "price_test") -> dict:
    return {"id": price_id, "unit_amount": unit_amount}


def _make_sub_item(price: dict, item_id: str = "si_test") -> dict:
    return {"id": item_id, "price": price}


def _make_subscription(
    sub_id: str,
    customer_id: str,
    unit_amount: int,
    price_id: str = "price_test",
    item_id: str = "si_test",
) -> dict:
    return {
        "id": sub_id,
        "customer": customer_id,
        "items": {
            "data": [_make_sub_item(_make_price(unit_amount, price_id), item_id)]
        },
        "current_period_end": 9999999999,
    }


def _args(dry_run: bool = False, customer_id: str = "", halt_on_error: bool = True):
    ns = SimpleNamespace()
    ns.stripe_key = "sk_test_fake"
    ns.dry_run = dry_run
    ns.use_json = False
    ns.customer_id = customer_id
    ns.halt_on_error = halt_on_error
    return ns


# ---------------------------------------------------------------------------
# classify_subscription
# ---------------------------------------------------------------------------

class TestClassifySubscription:
    def test_free_tier(self):
        sub = _make_subscription("sub_free", "cus_1", unit_amount=0)
        assert migrator.classify_subscription(sub) == "free"

    def test_starter_tier(self):
        sub = _make_subscription("sub_start", "cus_2", unit_amount=500)
        assert migrator.classify_subscription(sub) == "starter"

    def test_pro_tier(self):
        sub = _make_subscription("sub_pro", "cus_3", unit_amount=2500)
        assert migrator.classify_subscription(sub) == "pro"

    def test_enterprise_tier(self):
        sub = _make_subscription("sub_ent", "cus_4", unit_amount=50000)
        assert migrator.classify_subscription(sub) == "enterprise"

    def test_no_items_returns_free(self):
        sub = {"id": "sub_x", "customer": "cus_5", "items": {"data": []}}
        assert migrator.classify_subscription(sub) == "free"


# ---------------------------------------------------------------------------
# Per-tier migration handlers
# ---------------------------------------------------------------------------

class TestFreeTierUnchanged:
    def test_free_tier_unchanged(self):
        """Free tier customers must not trigger any Stripe API calls."""
        sub = _make_subscription("sub_free", "cus_1", unit_amount=0)
        with patch("stripe.Coupon.create") as mock_coupon, \
             patch("stripe.Subscription.modify") as mock_sub_modify, \
             patch("stripe.Customer.modify") as mock_cust_modify:

            result = migrator.migrate_free("cus_1", sub, dry_run=False)

        assert result["action"] == "free_unchanged"
        mock_coupon.assert_not_called()
        mock_sub_modify.assert_not_called()
        mock_cust_modify.assert_not_called()


class TestStarterMigration:
    def test_starter_gets_coupon_and_cancellation_at_period_end(self):
        """Starter customers get a 100%-off coupon + sub cancelled at period end."""
        sub = _make_subscription("sub_start", "cus_2", unit_amount=500)

        mock_coupon_obj = MagicMock()
        mock_coupon_obj.id = "agentcomms-starter-grandfather-cus_2"

        with patch("stripe.Coupon.create", return_value=mock_coupon_obj) as mock_coupon_create, \
             patch("stripe.Customer.modify") as mock_cust_modify, \
             patch("stripe.Subscription.modify") as mock_sub_modify:

            result = migrator.migrate_starter("cus_2", sub, dry_run=False, halt_on_error=True)

        assert result["action"] == "grandfathered_starter"
        assert result["coupon_id"] == "agentcomms-starter-grandfather-cus_2"

        # Coupon created with correct params
        create_kwargs = mock_coupon_create.call_args.kwargs
        assert create_kwargs["percent_off"] == 100
        assert create_kwargs["duration"] == "repeating"
        assert create_kwargs["duration_in_months"] == 6

        # Coupon applied to customer
        mock_cust_modify.assert_called_once()
        cust_call_kwargs = mock_cust_modify.call_args.kwargs
        assert cust_call_kwargs["coupon"] == "agentcomms-starter-grandfather-cus_2"

        # Sub cancelled at period end
        mock_sub_modify.assert_called_once()
        sub_call_kwargs = mock_sub_modify.call_args.kwargs
        assert sub_call_kwargs["cancel_at_period_end"] is True

    def test_starter_dry_run_makes_no_stripe_writes(self):
        """Dry-run mode must not write to Stripe."""
        sub = _make_subscription("sub_start", "cus_2", unit_amount=500)

        with patch("stripe.Coupon.create") as mock_coupon, \
             patch("stripe.Customer.modify") as mock_cust, \
             patch("stripe.Subscription.modify") as mock_sub:

            result = migrator.migrate_starter("cus_2", sub, dry_run=True, halt_on_error=True)

        assert result["action"] == "grandfathered_starter"
        mock_coupon.assert_not_called()
        mock_cust.assert_not_called()
        mock_sub.assert_not_called()


class TestProMigration:
    def test_pro_moved_to_developer_price(self):
        """Pro customers' subscription item must be updated to the Developer price."""
        sub = _make_subscription(
            "sub_pro", "cus_3", unit_amount=2500,
            price_id="price_pro_25", item_id="si_pro_item"
        )

        with patch("stripe.Subscription.modify") as mock_sub_modify:
            result = migrator.migrate_pro(
                "cus_3", sub,
                developer_price_id="price_developer_19",
                dry_run=False,
                halt_on_error=True,
            )

        assert result["action"] == "pro_to_developer"
        assert result["new_price"] == "price_developer_19"

        mock_sub_modify.assert_called_once()
        call_kwargs = mock_sub_modify.call_args.kwargs
        assert call_kwargs["items"] == [{"id": "si_pro_item", "price": "price_developer_19"}]
        assert call_kwargs["proration_behavior"] == "none"

    def test_pro_dry_run_makes_no_stripe_writes(self):
        """Dry-run mode must not call stripe.Subscription.modify."""
        sub = _make_subscription("sub_pro", "cus_3", unit_amount=2500)

        with patch("stripe.Subscription.modify") as mock_sub:
            result = migrator.migrate_pro(
                "cus_3", sub,
                developer_price_id="price_developer_19",
                dry_run=True,
                halt_on_error=True,
            )

        assert result["action"] == "pro_to_developer"
        mock_sub.assert_not_called()


class TestEnterpriseMigration:
    def test_enterprise_skipped(self):
        """Enterprise tier must produce 'skipped_enterprise' action with no API calls."""
        sub = _make_subscription("sub_ent", "cus_4", unit_amount=50000)

        with patch("stripe.Coupon.create") as mock_coupon, \
             patch("stripe.Subscription.modify") as mock_sub, \
             patch("stripe.Customer.modify") as mock_cust:

            result = migrator.migrate_enterprise("cus_4", sub, dry_run=False)

        assert result["action"] == "skipped_enterprise"
        mock_coupon.assert_not_called()
        mock_sub.assert_not_called()
        mock_cust.assert_not_called()


class TestDryRunEndToEnd:
    def test_dry_run_makes_no_stripe_writes(self):
        """Full dry-run pass: no Stripe create/modify calls should be made."""
        free_sub = _make_subscription("sub_free", "cus_1", unit_amount=0)
        starter_sub = _make_subscription("sub_start", "cus_2", unit_amount=500)
        pro_sub = _make_subscription("sub_pro", "cus_3", unit_amount=2500)
        ent_sub = _make_subscription("sub_ent", "cus_4", unit_amount=50000)

        subs = [free_sub, starter_sub, pro_sub, ent_sub]

        args = _args(dry_run=True)

        with patch("stripe.Subscription.auto_paging_iter", return_value=iter(subs)), \
             patch("stripe.Subscription.list"), \
             patch("stripe.Coupon.create") as mock_coupon, \
             patch("stripe.Customer.modify") as mock_cust, \
             patch("stripe.Subscription.modify") as mock_sub, \
             patch("stripe.Price.list", return_value=MagicMock(data=[])), \
             patch("stripe.Product.create", return_value=MagicMock(id="prod_new")), \
             patch("stripe.Price.create", return_value=MagicMock(id="price_dev_new")):

            exit_code = migrator.run_migration(args)

        assert exit_code == 0
        mock_coupon.assert_not_called()
        mock_cust.assert_not_called()
        mock_sub.assert_not_called()
