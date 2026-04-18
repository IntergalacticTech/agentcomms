from .client import FreeMail
from .exceptions import FreemailAPIError, FreemailError

PLATFORM_DOMAINS = (
    "victorymail.dev",
    "karmascale.net",
    "karmascale.org",
)

__version__ = "0.2.0"
__all__ = [
    "FreeMail",
    "FreemailError",
    "FreemailAPIError",
    "PLATFORM_DOMAINS",
]
