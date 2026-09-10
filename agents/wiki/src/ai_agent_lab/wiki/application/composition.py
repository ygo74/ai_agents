"""Composition root of the Wiki Agent.

This is the only place allowed to instantiate concrete implementations. Every
other component receives its collaborators, which is what makes the skills
testable, the runtime mode a configuration choice, and the framework replaceable.

The agent itself is built here with the plain LangChain API, deliberately. There
is no house abstraction to learn: a developer reads ``create_agent(...)`` and
finds the public documentation of that call. What the repository owns is what
makes skills reusable - the manifests, the registry, the adapter and the
confirmation policy - not a wrapper around an agent.

**The one thing to read carefully is the thread identifier.** LangGraph keys its
persisted state by ``thread_id``, and a conversation identifier is supplied by
the caller. Using it directly would let somebody resume another person's
conversation by guessing a string. The identifier is therefore derived from the
authenticated subject *and* the conversation, so the half a caller controls is
only half.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.config.manifests import AgentManifestLoader, SkillManifestLoader
from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.observability.audit import InMemoryAuditTrail
from ai_agent_lab.core.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.core.reasoning.ports import TextReasoner
from ai_agent_lab.core.registry import SkillDescriptor, SkillRegistry
from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.permissions import PermissionRegistry
from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator
from ai_agent_lab.langgraph.reasoner import LangGraphTextReasoner
from ai_agent_lab.langgraph.tool_adapter import SkillToolAdapter
from ai_agent_lab.wiki.application.skills_factory import WikiSkills, WikiSkillsFactory
from ai_agent_lab.wiki.application.wiki_tools_provider import WikiToolsProvider
from ai_agent_lab.wiki.capabilities.converters import WikiSearchRequestFactory
from ai_agent_lab.wiki.capabilities.read_capabilities import (
    REQUIRED_MCP_CAPABILITY,
    WikiReadCapabilities,
)
from ai_agent_lab.wiki.capabilities.results import (
    WIKI_UNTRUSTED_SOURCE,
    WikiToolResultRenderer,
)
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.config.settings import (
    ChatModelSettings,
    WikiAgentSettings,
    WikiFreshnessSettings,
)
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.freshness_skill import PageFreshnessDetector
from ai_agent_lab.wiki.tools_port import WikiTools

WIKI_AGENT = "wiki"


def thread_id_of(principal: Principal, conversation_id: str) -> str:
    """Derive the LangGraph thread identifier of one conversation.

    Both halves are hashed together rather than concatenated. A subject
    containing the separator could otherwise be made to collide with another
    subject's conversation - the classic ambiguity of a delimiter in a composite
    key - and the identifier is opaque to everyone anyway.
    """
    material = f"{len(principal.subject)}:{principal.subject}:{conversation_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class WikiAgentRuntime:
    """Everything the console, a test or another host needs to drive the agent."""

    principal: Principal
    user: UserContext
    manifest: AgentManifest
    registry: SkillRegistry
    agent: Any
    thread_id: str
    skills: WikiSkills
    policy: ConfirmationPolicy
    approvals: LangGraphApprovalTranslator
    audit: InMemoryAuditTrail
    wiki_tools: WikiTools
    provider: WikiToolsProvider

    async def aclose(self) -> None:
        """Release whatever the backend holds open, such as an MCP session."""
        await self.provider.aclose()


class WikiAgentCompositionRoot:
    """Wires the Wiki Agent for one user session."""

    def __init__(
        self,
        settings: WikiAgentSettings,
        chat_model: BaseChatModel,
        *,
        principal: Principal | None = None,
        wiki_tools: WikiTools | None = None,
        reasoner: TextReasoner | None = None,
        base_path: Path | None = None,
    ) -> None:
        self._settings = settings
        self._chat_model = chat_model
        self._principal = principal or Principal(subject=settings.user_id)
        self._wiki_tools_override = wiki_tools
        self._reasoner_override = reasoner
        self._base_path = base_path

    def for_principal(self, principal: Principal) -> WikiAgentCompositionRoot:
        """Return a root that assembles the agent for another caller.

        Serving several people means building the same wiring for a different
        identity, request after request. Copying the root keeps that in one
        place: nothing else has to know which collaborators a runtime needs.
        """
        return WikiAgentCompositionRoot(
            self._settings,
            self._chat_model,
            principal=principal,
            wiki_tools=self._wiki_tools_override,
            reasoner=self._reasoner_override,
            base_path=self._base_path,
        )

    def manifest(self) -> AgentManifest:
        """Return the delivered configuration of this agent.

        Exposed because the description an HTTP surface advertises must come from
        the same file the agent runs on. Two hand-written descriptions would
        drift, and a caller would discover capabilities the agent does not have.
        """
        return self._manifest()

    def build(self, *, session_id: str) -> WikiAgentRuntime:
        """Assemble the Wiki Agent and everything driving it."""
        manifest = self._manifest()
        user = self._user_context(session_id)
        policy = self._policy()
        audit = InMemoryAuditTrail()
        provider = WikiToolsProvider(self._settings, WikiDatasetLoader(), user_id=self._principal.subject)
        wiki_tools = self._wiki_tools_override or provider.build(base_path=self._base_path)
        skills = self._skills(manifest, wiki_tools)
        registry = self._registry(manifest, skills, provider.capabilities(base_path=self._base_path))

        approvals = LangGraphApprovalTranslator()
        tools = SkillToolAdapter(WikiToolResultRenderer()).to_tools(registry, user)

        return WikiAgentRuntime(
            principal=self._principal,
            user=user,
            manifest=manifest,
            registry=registry,
            agent=create_agent(
                model=self._chat_model,
                tools=list(tools),
                system_prompt=manifest.instructions,
                middleware=[
                    HumanInTheLoopMiddleware(
                        interrupt_on=approvals.interrupt_on(registry, policy, user),
                        description_prefix="This operation changes the wiki and needs approval",
                    )
                ],
                # Human-in-the-loop requires checkpointing: an interrupted turn
                # is resumed from persisted state. In-memory is right for a
                # console session and for tests; an HTTP deployment serving
                # several people wants a durable saver instead.
                checkpointer=InMemorySaver(),
                name=manifest.name,
            ),
            thread_id=thread_id_of(self._principal, session_id),
            skills=skills,
            policy=policy,
            approvals=approvals,
            audit=audit,
            wiki_tools=wiki_tools,
            provider=provider,
        )

    def _user_context(self, session_id: str) -> UserContext:
        """Build the identity every operation of this session carries."""
        return UserContext(
            user_id=self._principal.subject,
            session_id=session_id,
            permissions=WikiPermission.declared(),
        )

    def _policy(self) -> ConfirmationPolicy:
        """Build the deterministic confirmation policy of this deployment."""
        return ConfiguredConfirmationPolicy(
            InMemoryConfirmationPreferenceStore(
                {self._principal.subject: self._settings.confirmation_preferences()}
            ),
            WikiSecurityFloor().build(),
        )

    def _skills(self, manifest: AgentManifest, wiki_tools: WikiTools) -> WikiSkills:
        """Assemble the reusable domain capabilities."""
        thresholds = WikiFreshnessSettings()
        return WikiSkillsFactory(
            wiki_tools=wiki_tools,
            reasoner=self._reasoner(),
            manifest=manifest,
            context_builder=WikiContextBuilder(),
            freshness_detector=PageFreshnessDetector(
                ageing_after_days=thresholds.ageing_after_days,
                stale_after_days=thresholds.stale_after_days,
            ),
        ).build()

    def _reasoner(self) -> TextReasoner:
        """Build the reasoner used by the analysis skills."""
        if self._reasoner_override is not None:
            return self._reasoner_override
        return LangGraphTextReasoner(
            self._chat_model,
            PromptEnvelopeBuilder(source=WIKI_UNTRUSTED_SOURCE),
            temperature=ChatModelSettings().sampling_temperature(),
        )

    def _manifest(self) -> AgentManifest:
        """Load the configuration delivered for this agent."""
        directory = ConfigurationDirectory.resolve(base_path=self._base_path)
        skills = SkillManifestLoader(
            PermissionRegistry(WikiPermission.declared()),
            WikiSecurityFloor().build(),
        )
        return AgentManifestLoader(directory, skills).load(WIKI_AGENT)

    def _registry(
        self,
        manifest: AgentManifest,
        skills: WikiSkills,
        served: frozenset[WikiToolName],
    ) -> SkillRegistry:
        """Bind the delivered manifests to the code that runs them.

        A capability the bound server cannot serve is left out rather than
        advertised: a tool the model can select but no server can honour turns
        into a refusal in the middle of a conversation, after the person has
        already been told the agent could do it.
        """
        descriptors = WikiReadCapabilities(
            manifest,
            skills.search,
            skills.summary,
            skills.answer,
            skills.freshness,
            WikiSearchRequestFactory(),
        ).descriptors()
        return SkillRegistry(
            skills=[
                descriptor for descriptor in descriptors if self._is_serviceable(descriptor, served)
            ]
        )

    @staticmethod
    def _is_serviceable(descriptor: SkillDescriptor, served: frozenset[WikiToolName]) -> bool:
        """Whether the bound server can honour a capability.

        A capability that maps onto one MCP tool needs that tool. An analysis
        capability needs the tools it retrieves with, which are declared in
        ``REQUIRED_MCP_CAPABILITY`` because they cannot be read off the name.
        """
        required = REQUIRED_MCP_CAPABILITY.get(descriptor.tool_name)
        if required is not None:
            return all(capability in served for capability in required)
        try:
            return WikiToolName(descriptor.tool_name) in served
        except ValueError:
            return True
