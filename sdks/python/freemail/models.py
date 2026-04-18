"""Response dataclasses for FreeMail API objects.

These are provided for convenience but are not currently required --
all resource methods return plain dicts. Future versions may return
typed model instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Inbox:
    id: str
    email: str
    display_name: Optional[str] = None
    pod_id: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Recipient:
    address: str
    name: Optional[str] = None


@dataclass
class Message:
    id: str
    inbox_id: str
    thread_id: Optional[str] = None
    direction: Optional[str] = None
    subject: Optional[str] = None
    snippet: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    from_addr: Optional[dict] = None  # {name, address}
    to: List[dict] = field(default_factory=list)
    cc: List[dict] = field(default_factory=list)
    bcc: List[dict] = field(default_factory=list)
    is_read: bool = False
    is_starred: bool = False
    has_attachments: bool = False
    attachment_count: int = 0
    received_at: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Pod:
    id: str
    name: str
    description: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Domain:
    id: str
    domain: str
    status: Optional[str] = None
    created_at: Optional[str] = None


@dataclass
class Webhook:
    id: str
    url: str
    events: List[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class ApiKey:
    id: str
    name: str
    scope: str = "org"
    created_at: Optional[str] = None
