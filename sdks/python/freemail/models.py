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
class Message:
    id: str
    inbox_id: str
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    from_address: Optional[str] = None
    to: List[dict] = field(default_factory=list)
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
