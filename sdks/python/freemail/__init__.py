# SPDX-License-Identifier: FSL-1.1-Apache-2.0
"""
DEPRECATED: The ``freemail`` package is a compatibility shim. Please migrate to ``agentcomms``.

This shim re-exports the AgentComms client. All imports emit a DeprecationWarning.
See MIGRATION.md for the full diff.
"""
import warnings as _warnings

_warnings.warn(
    "The `freemail` package is deprecated and will be removed after the 90-day sunset window. "
    "Install `agentcomms` and update your imports: `from agentcomms import Client`. "
    "See MIGRATION.md for the full diff.",
    DeprecationWarning,
    stacklevel=2,
)

from agentcomms import Client  # re-export  # noqa: E402
from agentcomms.exceptions import AgentCommsError as FreemailError  # re-export with legacy name  # noqa: E402

__all__ = ["Client", "FreemailError"]
