# adapters/email/normalize.py
"""
Parse raw MIME into the AgentComms normalized form.

Ports the MIME parsing and quoted-reply stripping that the existing FreeMail
`lambdas/inbound_processor/handler.py` implements. The output shape is the
adapter's private intermediate representation, converted to UnifiedMessage in
adapter.py.
"""
from __future__ import annotations

import email
import re
from dataclasses import dataclass, field
from email.message import Message
from email.utils import getaddresses, parseaddr
from typing import Any


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    size: int
    content: bytes


@dataclass
class ParsedEmail:
    from_address: str
    from_display_name: str | None
    to_addresses: list[str]
    cc_addresses: list[str] = field(default_factory=list)
    subject: str = ""
    message_id_header: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    body_text: str = ""
    body_html: str | None = None
    attachments: list[ParsedAttachment] = field(default_factory=list)


_GMAIL_QUOTE_RE = re.compile(
    r"\n+On .+ wrote:\s*\n(?:>.*\n?)+", flags=re.DOTALL,
)
_OUTLOOK_QUOTE_RE = re.compile(
    r"\n+-----Original Message-----.*", flags=re.DOTALL,
)
_APPLE_QUOTE_RE = re.compile(
    r"\n+On .+, .+ <.+@.+> wrote:\s*\n(?:>.*\n?)+", flags=re.DOTALL,
)


def strip_quoted_reply(text: str) -> str:
    for pat in (_APPLE_QUOTE_RE, _GMAIL_QUOTE_RE, _OUTLOOK_QUOTE_RE):
        text = pat.sub("", text)
    return text.rstrip() + "\n" if text.strip() else ""


def _references_list(msg: Message) -> list[str]:
    raw = msg.get("References") or ""
    return [r.strip() for r in raw.split() if r.strip()]


def _extract_body(msg: Message) -> tuple[str, str | None]:
    text: str = ""
    html: str | None = None
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain" and not text:
                payload = part.get_payload(decode=True) or b""
                text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
            elif ctype == "text/html" and not html:
                payload = part.get_payload(decode=True) or b""
                html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        ctype = msg.get_content_type()
        payload = msg.get_payload(decode=True) or b""
        decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html":
            html = decoded
        else:
            text = decoded
    return strip_quoted_reply(text), html


def _extract_attachments(msg: Message) -> list[ParsedAttachment]:
    attachments: list[ParsedAttachment] = []
    if not msg.is_multipart():
        return attachments
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        attachments.append(ParsedAttachment(
            filename=part.get_filename() or "attachment",
            content_type=part.get_content_type(),
            size=len(payload),
            content=payload,
        ))
    return attachments


def parse_mime_bytes(raw: bytes) -> ParsedEmail:
    if not raw:
        raise ValueError("empty MIME bytes")
    msg = email.message_from_bytes(raw)
    if msg.keys() == []:
        raise ValueError("no MIME headers found")
    from_display, from_addr = parseaddr(msg.get("From") or "")
    to_addresses = [a for _, a in getaddresses([msg.get("To") or ""]) if a]
    cc_addresses = [a for _, a in getaddresses([msg.get("Cc") or ""]) if a]
    text, html = _extract_body(msg)
    return ParsedEmail(
        from_address=from_addr,
        from_display_name=from_display or None,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        subject=msg.get("Subject", "") or "",
        message_id_header=msg.get("Message-ID"),
        in_reply_to=msg.get("In-Reply-To"),
        references=_references_list(msg),
        body_text=text,
        body_html=html,
        attachments=_extract_attachments(msg),
    )
