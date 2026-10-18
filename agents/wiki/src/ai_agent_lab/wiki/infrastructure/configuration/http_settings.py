"""Settings of the Wiki Agent HTTP service.

Only routing and posture live here. No credential is read, held or logged.

The shape is the library's, shared with the Mail Agent. On a wiki the stakes of
running open are the same as on a mailbox: pages and spaces are restricted per
person, and an anonymous caller would be served somebody's view of the wiki
without anybody having decided whose.
"""

from __future__ import annotations

from ygo74.agent_runtime.domains.configuration.agent_http_settings import AgentHttpSettings

ENV_PREFIX = "WIKI_AGENT_HTTP_"
AUDIENCE = "wiki-agent"


class WikiAgentHttpSettings(AgentHttpSettings):
    """How the Wiki Agent is served over HTTP."""

    @classmethod
    def load(cls) -> WikiAgentHttpSettings:
        """Read the settings from the environment.

        Explicit rather than implicit in the constructor: the environment file
        has to have been loaded first, and a call that silently returned defaults
        would describe a service identifying nobody.
        """
        return cls.from_env(ENV_PREFIX, default_audience=AUDIENCE)
