"""Platform domain pool.

Domains owned and operated by FreeMail that any tier can create inboxes on.
Custom domains brought by users live separately in the `domains` resource.
"""

PLATFORM_DOMAINS = (
    "victorymail.dev",
    "karmascale.net",
    "karmascale.org",
)

DEFAULT_PLATFORM_DOMAIN = "victorymail.dev"


def is_platform_domain(domain: str) -> bool:
    return domain.lower() in PLATFORM_DOMAINS


def split_address(address: str) -> tuple[str, str]:
    local, _, domain = address.partition("@")
    return local, domain.lower()
