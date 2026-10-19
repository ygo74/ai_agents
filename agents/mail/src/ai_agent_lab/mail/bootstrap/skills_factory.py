"""Assembly of the mail skills.

Skills are pure business components: they receive their collaborators and know
nothing about where those come from. This factory is one of the two places in
the application allowed to instantiate them, the other being the tests.

Reasoning instructions are collaborators too. They come from the delivered skill
packages, so changing how the agent summarises or classifies is a configuration
change, not a release.
"""

from __future__ import annotations

import logging

from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.humanapproval.confirmation import ConfirmationGate, ConfirmationPolicy
from ygo74.agent_runtime.domains.reasoning.ports import TextReasoner
from ygo74.agent_runtime.domains.security.audit import AuditTrail

from ai_agent_lab.mail.application.capability_names import (
    CLASSIFY_MAIL,
    DRAFT_MAIL_REPLY,
    EXTRACT_MAIL_ACTIONS,
    SUMMARISE_MAIL,
)
from ai_agent_lab.mail.application.ports import MailboxOwnerDirectory
from ai_agent_lab.mail.application.ports.mail_tools import MailTools
from ai_agent_lab.mail.application.ports.operations import MailOperations
from ai_agent_lab.mail.application.skills.action_extraction_skill import MailActionExtractionSkill
from ai_agent_lab.mail.application.skills.analysis import MailAnalysisMapper
from ai_agent_lab.mail.application.skills.bundle import MailSkills
from ai_agent_lab.mail.application.skills.categories import MailCategoryCatalog
from ai_agent_lab.mail.application.skills.classification_skill import MailClassificationSkill
from ai_agent_lab.mail.application.skills.context import MailContextBuilder
from ai_agent_lab.mail.application.skills.gating import GatedMailOperationRunner
from ai_agent_lab.mail.application.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.application.skills.reply_skill import MailReplySkill
from ai_agent_lab.mail.application.skills.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.mail.application.skills.send_skill import SendMailSkill
from ai_agent_lab.mail.application.skills.summary_skill import MailSummarySkill
from ai_agent_lab.mail.domain.services.reply_recipient_planner import ReplyRecipientPlanner

_logger = logging.getLogger(__name__)


class MailSkillsFactory:
    """Builds the mail skills from their collaborators."""

    def __init__(
        self,
        mail_tools: MailTools,
        reasoner: TextReasoner,
        operations: MailOperations,
        policy: ConfirmationPolicy,
        audit: AuditTrail,
        owner_directory: MailboxOwnerDirectory,
        category_catalog: MailCategoryCatalog,
        context_builder: MailContextBuilder,
        manifest: AgentManifest,
    ) -> None:
        _logger.info("Initializing Mail Agent skills factory")
        _logger.debug(
            "MailSkillsFactory.__init__ arguments: mail_tools_type=%s, reasoner_type=%s, "
            "operations_type=%s, policy_type=%s, audit_type=%s, owner_directory_type=%s, "
            "category_catalog_type=%s, context_builder_type=%s, manifest=%s",
            type(mail_tools).__name__,
            type(reasoner).__name__,
            type(operations).__name__,
            type(policy).__name__,
            type(audit).__name__,
            type(owner_directory).__name__,
            type(category_catalog).__name__,
            type(context_builder).__name__,
            manifest.name,
        )
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._operations = operations
        self._policy = policy
        self._audit = audit
        self._owner_directory = owner_directory
        self._category_catalog = category_catalog
        self._context_builder = context_builder
        self._manifest = manifest

    def build(self) -> MailSkills:
        """Assemble every mail skill."""
        _logger.info("Assembling Mail Agent domain skills")
        _logger.debug(
            "MailSkillsFactory.build arguments: manifest=%s, mail_tools_type=%s, reasoner_type=%s",
            self._manifest.name,
            type(self._mail_tools).__name__,
            type(self._reasoner).__name__,
        )
        mapper = MailAnalysisMapper(self._category_catalog)
        runner = GatedMailOperationRunner(
            self._operations,
            self._policy,
            ConfirmationGate(self._policy),
            self._audit,
        )
        search = MailSearchSkill(self._mail_tools)
        read = MailReadSkill(self._mail_tools)
        summary = MailSummarySkill(
            self._mail_tools,
            self._reasoner,
            self._context_builder,
            mapper,
            self._prompt(SUMMARISE_MAIL),
        )
        classification = MailClassificationSkill(
            self._mail_tools,
            self._reasoner,
            self._context_builder,
            mapper,
            self._category_catalog,
            self._prompt(CLASSIFY_MAIL),
        )
        actions = MailActionExtractionSkill(
            self._mail_tools,
            self._reasoner,
            self._context_builder,
            mapper,
            self._prompt(EXTRACT_MAIL_ACTIONS),
        )
        reply = MailReplySkill(
            self._mail_tools,
            self._reasoner,
            self._context_builder,
            self._owner_directory,
            ReplyRecipientPlanner(),
            self._prompt(DRAFT_MAIL_REPLY),
        )
        send = SendMailSkill(self._mail_tools, self._mail_tools, runner)
        management = MailManagementSkill(self._mail_tools, self._mail_tools, self._mail_tools, runner)
        _logger.info("Mail Agent domain skills successfully assembled")
        _logger.debug(
            "MailSkillsFactory.build result: skills=%s",
            (
                type(search).__name__,
                type(read).__name__,
                type(summary).__name__,
                type(classification).__name__,
                type(actions).__name__,
                type(reply).__name__,
                type(send).__name__,
                type(management).__name__,
            ),
        )
        return MailSkills(
            search=search,
            read=read,
            summary=summary,
            classification=classification,
            actions=actions,
            reply=reply,
            send=send,
            management=management,
        )

    def _prompt(self, tool_name: str) -> str:
        """Return the reasoning instructions delivered for a capability."""
        _logger.info("Loading Mail Agent skill prompt")
        _logger.debug("MailSkillsFactory._prompt arguments: tool_name=%s", tool_name)
        prompt = self._manifest.skill(tool_name).prompt
        _logger.debug("Loaded Mail Agent skill prompt: tool_name=%s, prompt_length=%d", tool_name, len(prompt))
        return prompt
