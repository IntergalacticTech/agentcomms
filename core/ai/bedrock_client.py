# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/ai/bedrock_client.py
"""Thin Bedrock wrapper using Anthropic Messages API format.

Usage::

    from core.ai.bedrock_client import invoke_model, default_model_for

    resp = invoke_model(
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        prompt="Hello",
        max_tokens=256,
    )
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Model IDs ----------------------------------------------------------------
HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"
SONNET = "anthropic.claude-3-sonnet-20240229-v1:0"

_COMPLEX_TASKS = {"extract", "search"}

# Lazy singleton -----------------------------------------------------------
_bedrock = None


def _get_client():
    global _bedrock
    if _bedrock is None:
        region = os.environ.get("AWS_REGION", "us-east-1")
        _bedrock = boto3.client("bedrock-runtime", region_name=region)
    return _bedrock


# Public API ---------------------------------------------------------------

def default_model_for(task: str, complex: bool = False) -> str:
    """Return the preferred Bedrock model ID for *task*.

    Uses Sonnet for tasks flagged complex or in the complexity set, Haiku
    otherwise.
    """
    if complex or task in _COMPLEX_TASKS:
        return SONNET
    return HAIKU


def invoke_model(
    model_id: str,
    prompt: str,
    *,
    max_tokens: int = 1024,
    temperature: float = 0.2,
    system: str | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    """Call a Bedrock Anthropic model and return the full response JSON dict.

    Retries up to 3 times on ThrottlingException with exponential back-off.
    """
    body: dict[str, Any] = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
        body["tool_choice"] = {"type": "any"}

    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            response = client.invoke_model(
                modelId=model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
            return json.loads(response["body"].read())
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("ThrottlingException", "TooManyRequestsException"):
                last_exc = exc
                wait = (2 ** attempt) * 0.5  # 0.5s, 1s, 2s
                logger.warning("Bedrock throttle (attempt %d); sleeping %.1fs", attempt + 1, wait)
                time.sleep(wait)
            else:
                raise
    raise last_exc  # type: ignore[misc]


def generate_persona(hint: str | None = None) -> dict[str, Any]:
    """Generate a synthetic persona using the Haiku model.

    Returns a dict with keys: name, address, dob, phone, email.
    Used by personas_handler when generate=true.
    """
    hint_line = f"The persona should feel like: {hint}." if hint else ""
    tool = {
        "name": "persona",
        "description": "Synthetic persona details",
        "input_schema": {
            "type": "object",
            "properties": {
                "name":    {"type": "string"},
                "address": {"type": "string"},
                "dob":     {"type": "string", "description": "ISO date YYYY-MM-DD"},
                "phone":   {"type": "string"},
                "email":   {"type": "string"},
            },
            "required": ["name"],
        },
    }
    prompt = (
        "Generate a plausible synthetic persona (not a real person). "
        "Use the `persona` tool to return structured data. "
        f"{hint_line}"
    )
    resp = invoke_model(
        model_id=HAIKU,
        prompt=prompt,
        max_tokens=512,
        tools=[tool],
    )
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "persona":
            return block["input"]
    # Fallback if tool_use not returned
    return {"name": "Alex Smith"}
