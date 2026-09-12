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
import logging
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
from ai_agent_lab.core.observability.audit import InMemoryAuditTrail, LoggingAuditTrail
from ai_agent_lab.core.reasoning.envelope import PromptEnvelopeBuilder
from ai_agent_lab.core.reasoning.ports import TextReasoner
from ai_agent_lab.core.registry import SkillDescriptor, SkillRegistry
from ai_agent_lab.core.security.broker import ConfirmationBroker
from ai_agent_lab.core.security.confirmation import (
    ConfiguredConfirmationPolicy,
    ConfirmationGate,
    ConfirmationPolicy,
    InMemoryConfirmationPreferenceStore,
)
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.core.security.ledger import InMemoryConfirmationLedger
from ai_agent_lab.core.security.permissions import PermissionRegistry
from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.core.security.unattended import UnattendedApprovalAuthority
from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator
from ai_agent_lab.langgraph.reasoner import LangGraphTextReasoner
from ai_agent_lab.langgraph.tool_adapter import SkillToolAdapter
from ai_agent_lab.wiki.application.confirmation_presenter import WikiConfirmationPresenter
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
from ai_agent_lab.wiki.capabilities.write_capabilities import (
    REQUIRED_WRITE_MCP_CAPABILITY,
    WikiWriteCapabilities,
)
from ai_agent_lab.wiki.catalog import DeliveredWikiOperations, WikiToolName
from ai_agent_lab.wiki.config.settings import (
    ChatModelSettings,
    WikiAgentSettings,
    WikiFreshnessSettings,
)
from ai_agent_lab.wiki.domain.permissions import WikiPermission
from ai_agent_lab.wiki.inmemory.dataset import WikiDatasetLoader
from ai_agent_lab.wiki.inmemory.draft_store import InMemoryWikiDraftStore
from ai_agent_lab.wiki.security_floor import WikiSecurityFloor
from ai_agent_lab.wiki.skills.context import WikiContextBuilder
from ai_agent_lab.wiki.skills.freshness_skill import PageFreshnessDetector
from ai_agent_lab.wiki.skills.gating import GatedWikiOperationRunner
from ai_agent_lab.wiki.tools_port import WikiTools

WIKI_AGENT = "wiki"

_logger = logging.getLogger(__name__)


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
    presenter: WikiConfirmationPresenter
    confirmation_ledger: InMemoryConfirmationLedger
    draft_store: InMemoryWikiDraftStore

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
        _logger.info(
            "Assembling Wiki Agent runtime for principal '%s' (session_id='%s')",
            self._principal.subject,
            session_id,
        )
        _logger.info("Calling WikiAgentCompositionRoot._manifest() to load agent manifest...")
        manifest = self._manifest()
        _logger.info("Agent manifest '%s' loaded (%d skills declared)", manifest.name, len(manifest.skills))

        _logger.info("Calling WikiAgentCompositionRoot._user_context() to create security context...")
        user = self._user_context(session_id)
        _logger.debug("Created user context: user_id='%s', session_id='%s'", user.user_id, user.session_id)

        _logger.info("Calling WikiAgentCompositionRoot._policy() to configure confirmation policy...")
        policy = self._policy()
        audit = InMemoryAuditTrail()

        _logger.info(
            "Calling WikiToolsProvider.build() to assemble wiki tools backend (mode=%s)...",
            self._settings.mode.value,
        )
        provider = WikiToolsProvider(self._settings, WikiDatasetLoader(), user_id=self._principal.subject)
        wiki_tools = self._wiki_tools_override or provider.build(base_path=self._base_path)
        _logger.info("Calling WikiAgentCompositionRoot._skills() to assemble domain capabilities...")
        skills = self._skills(manifest, wiki_tools, policy, audit)

        draft_store = InMemoryWikiDraftStore()
        ledger = InMemoryConfirmationLedger()

        capabilities = provider.capabilities(base_path=self._base_path)
        _logger.info("Served capabilities count: %d", len(capabilities))

        registry = self._registry(
            manifest,
            skills,
            draft_store,
            ledger,
            capabilities,
        )

        approvals = LangGraphApprovalTranslator()
        interrupts = approvals.interrupt_on(registry, policy, user)
        _logger.debug("Configured interrupt_on table: %s", interrupts)

        _logger.info(
            "Calling SkillToolAdapter.to_tools() to adapt %d registered skills to LangChain...",
            len(registry.skills),
        )
        tools = SkillToolAdapter(WikiToolResultRenderer()).to_tools(registry, user)

        thread_id = thread_id_of(self._principal, session_id)
        _logger.debug("Derived LangGraph thread_id: %s", thread_id)

        _logger.info(
            "Calling LangChain create_agent() with model '%s' and %d tools...",
            type(self._chat_model).__name__,
            len(tools),
        )
        agent = create_agent(
            model=self._chat_model,
            tools=list(tools),
            system_prompt=manifest.instructions,
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on=interrupts,
                    description_prefix="This operation changes the wiki and needs approval",
                )
            ],
            # Human-in-the-loop requires checkpointing: an interrupted turn
            # is resumed from persisted state. In-memory is right for a
            # console session and for tests; an HTTP deployment serving
            # several people wants a durable saver instead.
            checkpointer=InMemorySaver(),
            name=manifest.name,
        )

        _logger.info("Wiki Agent runtime successfully assembled with %d tool(s)", len(tools))
        return WikiAgentRuntime(
            principal=self._principal,
            user=user,
            manifest=manifest,
            registry=registry,
            agent=agent,
            thread_id=thread_id,
            skills=skills,
            policy=policy,
            approvals=approvals,
            audit=audit,
            wiki_tools=wiki_tools,
            provider=provider,
            presenter=WikiConfirmationPresenter(skills, draft_store),
            confirmation_ledger=ledger,
            draft_store=draft_store,
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
            InMemoryConfirmationPreferenceStore({self._principal.subject: self._settings.confirmation_preferences()}),
            WikiSecurityFloor().build(),
        )

    def _skills(
        self,
        manifest: AgentManifest,
        wiki_tools: WikiTools,
        policy: ConfirmationPolicy,
        audit: InMemoryAuditTrail,
    ) -> WikiSkills:
        """Assemble the reusable domain capabilities."""
        thresholds = WikiFreshnessSettings()
        _logger.debug(
            "assembling wiki skills (freshness thresholds: ageing=%d days, stale=%d days)",
            thresholds.ageing_after_days,
            thresholds.stale_after_days,
        )
        return WikiSkillsFactory(
            wiki_tools=wiki_tools,
            reasoner=self._reasoner(),
            manifest=manifest,
            context_builder=WikiContextBuilder(),
            freshness_detector=PageFreshnessDetector(
                ageing_after_days=thresholds.ageing_after_days,
                stale_after_days=thresholds.stale_after_days,
            ),
            runner=GatedWikiOperationRunner(
                DeliveredWikiOperations(manifest),
                policy,
                ConfirmationGate(policy),
                LoggingAuditTrail(audit),
            ),
        ).build()

    def _reasoner(self) -> TextReasoner:
        """Build the reasoner used by the analysis skills."""
        if self._reasoner_override is not None:
            return self._reasoner_override
        temp = ChatModelSettings().sampling_temperature()
        _logger.debug("building LangGraphTextReasoner (temperature=%s)", temp)
        return LangGraphTextReasoner(
            self._chat_model,
            PromptEnvelopeBuilder(source=WIKI_UNTRUSTED_SOURCE),
            temperature=temp,
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
        draft_store: InMemoryWikiDraftStore,
        ledger: InMemoryConfirmationLedger,
        served: frozenset[WikiToolName],
    ) -> SkillRegistry:
        """Bind the delivered manifests to the code that runs them.

        A capability the bound server cannot serve is left out rather than
        advertised: a tool the model can select but no server can honour turns
        into a refusal in the middle of a conversation, after the person has
        already been told the agent could do it.

        That filter matters more for the write capabilities than for the read
        ones. A binding that declares no ``update_page`` is usually a deployment
        that runs the server read-only, and offering the tool anyway would have
        the agent promise an edit the server is configured to refuse.
        """
        broker = ConfirmationBroker(UnattendedApprovalAuthority(), ledger)
        descriptors = (
            *WikiReadCapabilities(
                manifest,
                skills.search,
                skills.summary,
                skills.answer,
                skills.freshness,
                WikiSearchRequestFactory(),
            ).descriptors(),
            *WikiWriteCapabilities(
                manifest,
                skills.drafting,
                skills.authoring,
                skills.comment,
                draft_store,
                broker,
            ).descriptors(),
        )
        _logger.info("Evaluating %d wiki capabilities against server capabilities...", len(descriptors))
        serviceable: list[SkillDescriptor] = []
        unserviceable: list[str] = []
        for descriptor in descriptors:
            if self._is_serviceable(descriptor, served):
                _logger.debug("Capability '%s': serviceable=True (registered)", descriptor.tool_name)
                serviceable.append(descriptor)
            else:
                _logger.debug("Capability '%s': serviceable=False (excluded)", descriptor.tool_name)
                unserviceable.append(descriptor.tool_name)

        _logger.info(
            "Registered %d serviceable capabilities out of %d total descriptors (excluded: %s)",
            len(serviceable),
            len(descriptors),
            unserviceable or "none",
        )

        return SkillRegistry(skills=serviceable)

    @staticmethod
    def _is_serviceable(descriptor: SkillDescriptor, served: frozenset[WikiToolName]) -> bool:
        """Whether the bound server can honour a capability.

        A capability that maps onto one MCP tool needs that tool. A capability
        that retrieves before it reasons - or before it drafts - needs the tools
        it retrieves with, which are declared in the two requirement tables
        because they cannot be read off the name.
        """
        required = REQUIRED_MCP_CAPABILITY.get(descriptor.tool_name) or REQUIRED_WRITE_MCP_CAPABILITY.get(
            descriptor.tool_name
        )
        if required is not None:
            return all(capability in served for capability in required)
        try:
            return WikiToolName(descriptor.tool_name) in served
        except ValueError:
            return True
