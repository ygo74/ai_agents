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
from dataclasses import dataclass

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.reasoning.ports import TextReasoner
from ai_agent_lab.core.security.audit import AuditTrail
from ai_agent_lab.core.security.confirmation import ConfirmationGate, ConfirmationPolicy
from ai_agent_lab.mail.catalog import MailOperations
from ai_agent_lab.mail.domain.ports import MailboxOwnerDirectory
from ai_agent_lab.mail.skills.action_extraction_skill import MailActionExtractionSkill
from ai_agent_lab.mail.skills.analysis import MailAnalysisMapper
from ai_agent_lab.mail.skills.categories import MailCategoryCatalog
from ai_agent_lab.mail.skills.classification_skill import MailClassificationSkill
from ai_agent_lab.mail.skills.context import MailContextBuilder
from ai_agent_lab.mail.skills.gating import GatedMailOperationRunner
from ai_agent_lab.mail.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.skills.reply_skill import MailReplySkill, ReplyRecipientPlanner
from ai_agent_lab.mail.skills.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.mail.skills.send_skill import SendMailSkill
from ai_agent_lab.mail.skills.summary_skill import MailSummarySkill
from ai_agent_lab.mail.tools_port import MailTools

SUMMARISE_MAIL = "summarise_mail"
CLASSIFY_MAIL = "classify_mail"
EXTRACT_MAIL_ACTIONS = "extract_mail_actions"
DRAFT_MAIL_REPLY = "draft_mail_reply"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MailSkills:
    """The mail skills, assembled and ready to be exposed."""

    search: MailSearchSkill
    read: MailReadSkill
    summary: MailSummarySkill
    classification: MailClassificationSkill
    actions: MailActionExtractionSkill
    reply: MailReplySkill
    send: SendMailSkill
    management: MailManagementSkill


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
