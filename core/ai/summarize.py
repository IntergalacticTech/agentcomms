# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Victory (Intergalactic Tech).
# Licensed under the Apache License, Version 2.0. See LICENSE for details.

# core/ai/summarize.py
"""Text summarization via Bedrock."""
from __future__ import annotations

from typing import Literal

from core.ai.bedrock_client import HAIKU, invoke_model

_WORD_LIMITS = {
    "short": 50,
    "long": 300,
}


def summarize(text: str, *, length: Literal["short", "long"] = "short") -> str:
    """Summarize *text* and return a plain string.

    ``length="short"`` → ≤ 50 words.
    ``length="long"``  → ≤ 300 words.
    """
    word_limit = _WORD_LIMITS.get(length, 50)
    prompt = (
        f"Summarize the following text in at most {word_limit} words. "
        "Return only the summary, no preamble or explanation.\n\n"
        f"{text[:8000]}"
    )
    resp = invoke_model(model_id=HAIKU, prompt=prompt, max_tokens=512)
    for block in resp.get("content", []):
        if block.get("type") == "text":
            return block["text"].strip()
    return ""
