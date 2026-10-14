"""Business rules remain usable without skills, infrastructure or frameworks."""

import pytest
from tests.conftest import make_message, make_participant

from ai_agent_lab.mail.domain.enums import MailCategory
from ai_agent_lab.mail.domain.errors import NoReplyRecipientError
from ai_agent_lab.mail.domain.models import EmailAddress
from ai_agent_lab.mail.domain.services.categories import MailCategories
from ai_agent_lab.mail.domain.services.reply_recipient_planner import ReplyRecipientPlanner


def test_reply_all_removes_owner_and_duplicate_recipients():
    message = make_message(
        sender="john@example.com",
        to=("owner@example.com", "john@example.com", "sarah@example.com", "SARAH@example.com"),
    ).model_copy(update={"cc": (make_participant("sarah@example.com"), make_participant("kate@example.com"))})

    to, cc = ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=True)

    assert tuple(str(address) for address in to) == ("john@example.com",)
    assert tuple(str(address) for address in cc) == ("sarah@example.com", "kate@example.com")


def test_reply_all_to_own_message_uses_other_recipients():
    message = make_message(sender="owner@example.com", to=("john@example.com", "owner@example.com"))

    to, cc = ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=True)

    assert tuple(str(address) for address in to) == ("john@example.com",)
    assert cc == ()


def test_reply_without_any_recipient_is_rejected():
    message = make_message(sender="owner@example.com")

    with pytest.raises(NoReplyRecipientError):
        ReplyRecipientPlanner().plan(message, EmailAddress(value="owner@example.com"), reply_all=False)


def test_category_rules_preserve_priority_and_fallback():
    rules = MailCategories((MailCategory.PROJECT, MailCategory.OTHER), MailCategory.OTHER)

    assert rules.categories() == (MailCategory.PROJECT, MailCategory.OTHER)
    assert rules.contains(MailCategory.PROJECT)
    assert rules.normalise(MailCategory.PROJECT) is MailCategory.PROJECT
    assert rules.normalise(MailCategory.FINANCIAL) is MailCategory.OTHER


def test_category_fallback_must_be_offered():
    with pytest.raises(ValueError, match="must be part of the catalogue"):
        MailCategories((MailCategory.PROJECT,), MailCategory.OTHER)
