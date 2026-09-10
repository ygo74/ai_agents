"""The caller of a single-user run.

Serving the agent over HTTP establishes the caller by authenticating a token.
The command line has no such transport: one person runs it, on their own
machine, against their own mailbox. That person is described in ``.env``.

Keeping this translation in one small class is what lets the composition root
require a :class:`Principal` unconditionally. The rest of the application then
never asks how the caller was established - it is handed one, whether the run is
a console session or an HTTP request.
"""

from __future__ import annotations

from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.mail.config.settings import MailAgentSettings


class LocalPrincipalSource:
    """Builds the principal of a run driven from the command line."""

    def __init__(self, settings: MailAgentSettings) -> None:
        self._settings = settings

    def principal(self) -> Principal:
        """Return the configured local caller."""
        return Principal(
            subject=self._settings.user_id,
            email=self._settings.user_email,
            display_name=self._settings.user_id,
        )
