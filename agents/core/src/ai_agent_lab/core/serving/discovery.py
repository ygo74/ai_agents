"""Describing an agent to discovery, from the configuration it runs on.

The identity, the description and the capabilities of an agent already live in
``config/agents/<agent>/agent.yaml``. Writing them a second time here would let
the two drift, and what a caller discovers would stop matching what the agent
actually does. So the descriptor is derived from the manifest instead.

This is the **only** module of ``ai_agent_lab.core`` that imports the serving
library, and it is optional: install the ``http`` extra of this distribution to
use it. Everything else in ``core`` - the security model, the skill registry, the
conversation port - stays free of any transport, which is what lets a domain test
run without one.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from ygo74.agent_runtime import (
    AgentCapabilitySet,
    AgentDescriptor,
    AgentSkill,
    Modality,
)

from ai_agent_lab.core.manifests import AgentManifest

DEFAULT_VERSION = "1.0.0"
DEFAULT_OWNER = "ai-agent-lab"
DEFAULT_SECURITY_SCHEMES = ("jwt", "oidc")


class AgentDescriptorFactory:
    """Builds the descriptor a serving runtime advertises for one agent.

    Args:
        manifest: The delivered configuration the agent was assembled from.
            Its name, description and skills are what discovery reports.
        agent_id: Stable identifier of the agent, used as its route key and as
            the model name an OpenAI client asks for.
        tags: How the agent is classified in a catalogue.
        created_at: When the agent was first published. Timezone-aware, so two
            deployments in different zones report the same instant.
        version: Version of the agent, not of the library serving it.
    """

    def __init__(
        self,
        manifest: AgentManifest,
        *,
        agent_id: str,
        tags: Sequence[str],
        created_at: datetime,
        version: str = DEFAULT_VERSION,
        owner: str = DEFAULT_OWNER,
    ) -> None:
        self._manifest = manifest
        self._agent_id = agent_id
        self._tags = tuple(tags)
        self._created_at = created_at
        self._version = version
        self._owner = owner

    def build(self) -> AgentDescriptor:
        """Build the descriptor the runtime advertises through discovery."""
        return AgentDescriptor(
            agent_id=self._agent_id,
            route_key=self._agent_id,
            display_name=self._manifest.name,
            description=self._manifest.description,
            version=self._version,
            owner=self._owner,
            created_at_utc=self._created_at,
            capabilities=AgentCapabilitySet(
                streaming=False,
                input_modalities=(Modality.TEXT,),
                output_modalities=(Modality.TEXT,),
            ),
            tags=self._tags,
            security_schemes=DEFAULT_SECURITY_SCHEMES,
            skills=tuple(
                AgentSkill(
                    skill_id=skill.tool_name,
                    name=skill.tool_name,
                    description=skill.description,
                )
                for skill in self._manifest.skills
            ),
        )
