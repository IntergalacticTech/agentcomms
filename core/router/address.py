# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/router/address.py
"""
Address-format → channel inference.

Used on the outbound hot path: POST /v1/agents/{id}/messages {to: "..."}
Address prefixes disambiguate chat platforms; email and SMS use format regexes.
"""
from __future__ import annotations

import re


class AmbiguousAddressError(ValueError):
    pass


_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z]{2,})+$"
)
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")

_PREFIXED_CHANNELS = {
    "slack:": "slack",
    "discord:": "discord",
    "telegram:": "telegram",
    "push:apns:": "push",
    "push:fcm:": "push",
}


def infer_channel(address: str) -> str:
    if not isinstance(address, str) or not address:
        raise AmbiguousAddressError(f"empty or non-string address: {address!r}")
    for prefix, channel in _PREFIXED_CHANNELS.items():
        if address.startswith(prefix):
            return channel
    if _EMAIL_RE.match(address):
        return "email"
    if _E164_RE.match(address):
        return "sms"
    raise AmbiguousAddressError(
        f"cannot infer channel from address: {address!r}. "
        f"Supported formats: email (user@domain.tld), sms (+15551234567), "
        f"slack:TEAM:USER, discord:GUILD:USER, telegram:chat:ID, "
        f"push:apns:ARN, push:fcm:ARN."
    )
