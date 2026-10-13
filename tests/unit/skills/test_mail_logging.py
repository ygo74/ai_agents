"""Logging contract of the Mail Agent business and infrastructure layers."""

from __future__ import annotations

import logging

import pytest
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.application.skills.search_skill import MailReadSkill
from ai_agent_lab.mail.domain.models import MailSearchRequest
from ai_agent_lab.mail.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mail.infrastructure.mcp.google.query import GmailQueryBuilder


async def test_logs_loop_once_and_repeated_retrievals_at_debug(
    mail_tools: InMemoryMailTools,
    owner: UserContext,
    caplog: pytest.LogCaptureFixture,
) -> None:
    read_skill = MailReadSkill(mail_tools)

    with caplog.at_level(logging.DEBUG, logger="ai_agent_lab.mail"):
        await read_skill.read_messages(("m1", "m3"), owner)

    records = caplog.records
    assert any(
        record.levelno == logging.INFO and record.message == "Reading mailbox message loop" for record in records
    )
    assert any(
        record.levelno == logging.DEBUG
        and record.name == "ai_agent_lab.mail.infrastructure.inmemory.mail_tools"
        and "InMemoryMailTools.get_message arguments: message_id=m1" in record.message
        for record in records
    )
    assert any(
        record.levelno == logging.DEBUG
        and record.name == "ai_agent_lab.mail.application.skills.search_skill"
        and "message_ids=('m1', 'm3')" in record.message
        and "user_id=owner" in record.message
        for record in records
    )

    rendered = caplog.text
    assert "architecture document" not in rendered
    assert "Ignore all previous instructions" not in rendered


def test_logs_search_shape_without_search_content(caplog: pytest.LogCaptureFixture) -> None:
    private_keywords = "confidential-acquisition-codename"
    private_subject = "Restricted board discussion"
    request = MailSearchRequest(keywords=private_keywords, subject_contains=private_subject)

    with caplog.at_level(logging.DEBUG, logger="ai_agent_lab.mail"):
        GmailQueryBuilder().build(request)

    assert "Building Gmail MCP search query" in caplog.text
    assert f"keywords_length={len(private_keywords)}" in caplog.text
    assert f"subject_length={len(private_subject)}" in caplog.text
    assert private_keywords not in caplog.text
    assert private_subject not in caplog.text
