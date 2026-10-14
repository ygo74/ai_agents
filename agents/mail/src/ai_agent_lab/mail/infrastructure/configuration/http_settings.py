"""Settings of the Mail Agent HTTP service.

Only routing and posture live here. No credential is read, held or logged: the
API key of the demonstration mode is compared, never stored anywhere it could be
printed, and OIDC tokens are validated against a published key set.

The shape is the library's. It was 78 % identical to the Wiki Agent's, which is
how the two had already drifted apart on which one refuses to start. What is left
is this deployment's two facts: the prefix its variables carry, and the audience
its tokens must name.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.configuration.agent_http_settings import AgentHttpSettings

ENV_PREFIX = "MAIL_AGENT_HTTP_"
AUDIENCE = "mail-agent"


class MailAgentHttpSettings(AgentHttpSettings):
    """How the Mail Agent is served over HTTP."""

    @classmethod
    def load(cls) -> MailAgentHttpSettings:
        """Read the settings from the environment.

        Explicit rather than implicit in the constructor: the environment file
        has to have been loaded first, and a call that silently returned defaults
        would describe a service identifying nobody. That service refuses to
        start - the guard sees to it - but it would blame the wrong thing.
        """
        return cls.from_env(ENV_PREFIX, default_audience=AUDIENCE)
