"""Ports consumed by Mail application capabilities."""

from ai_agent_lab.mail.application.ports.draft_store import DraftStore
from ai_agent_lab.mail.application.ports.mailbox_owner_directory import MailboxOwnerDirectory

__all__ = ["DraftStore", "MailboxOwnerDirectory"]
