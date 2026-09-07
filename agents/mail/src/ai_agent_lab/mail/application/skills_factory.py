"""Assembly of the mail skills.

Skills are pure business components: they receive their collaborators and know
nothing about where those come from. This factory is one of the two places in
the application allowed to instantiate them, the other being the tests.

Reasoning instructions are collaborators too. They come from the delivered skill
packages, so changing how the agent summarises or classifies is a configuration
change, not a release.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_agent_lab.domain.mail.ports import MailboxOwnerDirectory
from ai_agent_lab.domain.manifests import AgentManifest
from ai_agent_lab.domain.reasoning.ports import TextReasoner
from ai_agent_lab.domain.security.audit import AuditTrail
from ai_agent_lab.domain.security.confirmation import ConfirmationGate, ConfirmationPolicy
from ai_agent_lab.mcp.mail.catalog import MailToolCatalog
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.skills.mail.action_extraction_skill import MailActionExtractionSkill
from ai_agent_lab.skills.mail.analysis import MailAnalysisMapper
from ai_agent_lab.skills.mail.categories import MailCategoryCatalog
from ai_agent_lab.skills.mail.classification_skill import MailClassificationSkill
from ai_agent_lab.skills.mail.context import MailContextBuilder
from ai_agent_lab.skills.mail.gating import GatedMailOperationRunner
from ai_agent_lab.skills.mail.management_skill import MailManagementSkill
from ai_agent_lab.skills.mail.reply_skill import MailReplySkill, ReplyRecipientPlanner
from ai_agent_lab.skills.mail.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.skills.mail.send_skill import SendMailSkill
from ai_agent_lab.skills.mail.summary_skill import MailSummarySkill

SUMMARISE_MAIL = "summarise_mail"
CLASSIFY_MAIL = "classify_mail"
EXTRACT_MAIL_ACTIONS = "extract_mail_actions"
DRAFT_MAIL_REPLY = "draft_mail_reply"


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
        catalog: MailToolCatalog,
        policy: ConfirmationPolicy,
        audit: AuditTrail,
        owner_directory: MailboxOwnerDirectory,
        category_catalog: MailCategoryCatalog,
        context_builder: MailContextBuilder,
        manifest: AgentManifest,
    ) -> None:
        self._mail_tools = mail_tools
        self._reasoner = reasoner
        self._catalog = catalog
        self._policy = policy
        self._audit = audit
        self._owner_directory = owner_directory
        self._category_catalog = category_catalog
        self._context_builder = context_builder
        self._manifest = manifest

    def build(self) -> MailSkills:
        """Assemble every mail skill."""
        mapper = MailAnalysisMapper(self._category_catalog)
        runner = GatedMailOperationRunner(
            self._catalog,
            self._policy,
            ConfirmationGate(self._policy),
            self._audit,
        )
        return MailSkills(
            search=MailSearchSkill(self._mail_tools),
            read=MailReadSkill(self._mail_tools),
            summary=MailSummarySkill(
                self._mail_tools,
                self._reasoner,
                self._context_builder,
                mapper,
                self._prompt(SUMMARISE_MAIL),
            ),
            classification=MailClassificationSkill(
                self._mail_tools,
                self._reasoner,
                self._context_builder,
                mapper,
                self._category_catalog,
                self._prompt(CLASSIFY_MAIL),
            ),
            actions=MailActionExtractionSkill(
                self._mail_tools,
                self._reasoner,
                self._context_builder,
                mapper,
                self._prompt(EXTRACT_MAIL_ACTIONS),
            ),
            reply=MailReplySkill(
                self._mail_tools,
                self._reasoner,
                self._context_builder,
                self._owner_directory,
                ReplyRecipientPlanner(),
                self._prompt(DRAFT_MAIL_REPLY),
            ),
            send=SendMailSkill(self._mail_tools, self._mail_tools, runner),
            management=MailManagementSkill(self._mail_tools, self._mail_tools, runner),
        )

    def _prompt(self, tool_name: str) -> str:
        """Return the reasoning instructions delivered for a capability."""
        return self._manifest.skill(tool_name).prompt
