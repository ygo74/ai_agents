"""Framework-neutral bundle of the assembled Mail use cases."""

from dataclasses import dataclass

from ai_agent_lab.mail.application.skills.action_extraction_skill import MailActionExtractionSkill
from ai_agent_lab.mail.application.skills.classification_skill import MailClassificationSkill
from ai_agent_lab.mail.application.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.application.skills.reply_skill import MailReplySkill
from ai_agent_lab.mail.application.skills.search_skill import MailReadSkill, MailSearchSkill
from ai_agent_lab.mail.application.skills.send_skill import SendMailSkill
from ai_agent_lab.mail.application.skills.summary_skill import MailSummarySkill


@dataclass(frozen=True, slots=True)
class MailSkills:
    """The Mail skills, assembled and ready to be exposed."""

    search: MailSearchSkill
    read: MailReadSkill
    summary: MailSummarySkill
    classification: MailClassificationSkill
    actions: MailActionExtractionSkill
    reply: MailReplySkill
    send: SendMailSkill
    management: MailManagementSkill
