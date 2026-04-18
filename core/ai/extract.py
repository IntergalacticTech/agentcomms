# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/ai/extract.py
"""Structured data extraction via Bedrock tool_use + jsonschema validation."""
from __future__ import annotations

import logging

import jsonschema

from core.ai.bedrock_client import SONNET, invoke_model

logger = logging.getLogger(__name__)


def extract(message_body: str, schema: dict) -> dict:
    """Extract structured data from *message_body* conforming to *schema*.

    Uses Anthropic tool_use so the LLM returns validated JSON directly.
    Validates the result against *schema* via jsonschema.

    Returns the extracted dict.
    Raises ``ValueError`` if validation fails.
    """
    tool = {
        "name": "extract",
        "description": "Extract structured data from the message according to the given schema.",
        "input_schema": schema,
    }

    prompt = (
        "Extract structured information from the following message. "
        "Use the `extract` tool to return your answer. "
        "If a field cannot be found, omit it or use null.\n\n"
        f"Message:\n{message_body[:6000]}"
    )

    resp = invoke_model(
        model_id=SONNET,
        prompt=prompt,
        max_tokens=1024,
        tools=[tool],
    )

    # Find the extract tool_use block
    extracted: dict | None = None
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "extract":
            extracted = block.get("input", {})
            break

    if extracted is None:
        logger.warning("extract: no tool_use block in response")
        extracted = {}

    # Validate against caller-provided schema
    try:
        jsonschema.validate(extracted, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"Extracted data failed schema validation: {exc.message}") from exc

    return extracted
