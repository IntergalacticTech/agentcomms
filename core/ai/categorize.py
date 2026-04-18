# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.

# core/ai/categorize.py
"""Message categorization via Bedrock tool_use."""
from __future__ import annotations

import logging

from core.ai.bedrock_client import default_model_for, invoke_model

logger = logging.getLogger(__name__)

_TOOL = {
    "name": "classify",
    "description": "Classify the message into one of the provided labels.",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "description": "The single best-matching label from the allowed list.",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score between 0.0 and 1.0.",
            },
        },
        "required": ["label", "confidence"],
    },
}


def _parse_tool_result(resp: dict) -> dict | None:
    """Extract the classify tool_use block from a Bedrock response."""
    for block in resp.get("content", []):
        if block.get("type") == "tool_use" and block.get("name") == "classify":
            return block.get("input", {})
    return None


def categorize(
    message_body: str,
    labels: list[str],
    *,
    complex: bool = False,
) -> dict:
    """Classify *message_body* into one of *labels*.

    Returns ``{"label": str, "confidence": float}``.
    Falls back to ``"uncategorized"`` if the model returns an invalid label.
    """
    model_id = default_model_for("categorize", complex=complex)
    labels_str = ", ".join(f'"{lb}"' for lb in labels)

    prompt = (
        f"You must classify the following message into exactly one of these labels: [{labels_str}]. "
        "Use the `classify` tool to return your answer.\n\n"
        f"Message:\n{message_body[:4000]}"
    )

    resp = invoke_model(model_id=model_id, prompt=prompt, max_tokens=256, tools=[_TOOL])
    result = _parse_tool_result(resp)

    if result and result.get("label") in labels:
        return {"label": result["label"], "confidence": float(result.get("confidence", 0.9))}

    # Retry once with a stricter prompt
    logger.warning("categorize: invalid label on first attempt; retrying with strict prompt")
    strict_prompt = (
        f"IMPORTANT: You MUST pick one label from this exact list: {labels_str}. "
        "No other label is allowed. Use the `classify` tool.\n\n"
        f"Message:\n{message_body[:4000]}"
    )
    resp2 = invoke_model(model_id=model_id, prompt=strict_prompt, max_tokens=256, tools=[_TOOL])
    result2 = _parse_tool_result(resp2)

    if result2 and result2.get("label") in labels:
        return {"label": result2["label"], "confidence": float(result2.get("confidence", 0.7))}

    logger.warning("categorize: fallback to 'uncategorized'")
    return {"label": "uncategorized", "confidence": 0.0}
