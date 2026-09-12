"""Tests of the mailbox dataset loader."""

from __future__ import annotations

from pathlib import Path

import pytest
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.mail.domain.permissions import MailPermission
from ai_agent_lab.mail.inmemory.dataset import MailDatasetError, MailDatasetLoader
from ai_agent_lab.mail.inmemory.mail_tools import InMemoryMailTools

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATASET = REPOSITORY_ROOT / "data" / "mail" / "sample_mailbox.json"

LOCAL_USER = UserContext(user_id="local-user", session_id="s1", permissions=MailPermission.declared())


@pytest.fixture
def mailboxes():
    """Load the sample mailbox shipped with the repository."""
    return MailDatasetLoader().load_file(SAMPLE_DATASET)


class TestMailDatasetLoader:
    """Loading of the reference dataset."""

    def test_loads_every_mailbox(self, mailboxes):
        assert set(mailboxes) == {"local-user", "other-user"}

    def test_wraps_free_text_as_untrusted(self, mailboxes):
        message = mailboxes["local-user"].message("m-alpha-1")

        assert "not trusted" not in repr(message.body)
        assert "review it" in message.body.expose()
        assert "review it" not in repr(message.body)

    def test_parses_timestamps_with_a_timezone(self, mailboxes):
        assert mailboxes["local-user"].message("m-alpha-1").sent_at.tzinfo is not None

    def test_loads_attachments_and_labels(self, mailboxes):
        message = mailboxes["local-user"].message("m-alpha-1")

        assert message.has_attachments
        assert message.attachments[0].media_type == "application/pdf"
        assert "PROJECT_ALPHA" in message.label_ids

    async def test_the_dataset_is_usable_through_the_mcp_contract(self, mailboxes):
        tools = InMemoryMailTools(mailboxes)

        thread = await tools.get_thread("t-alpha", LOCAL_USER)

        assert [m.message_id for m in thread.messages] == ["m-alpha-1", "m-alpha-2", "m-alpha-3"]

    @pytest.mark.security
    def test_the_dataset_carries_a_prompt_injection_case(self, mailboxes):
        body = mailboxes["local-user"].message("m-injection-1").body.expose()

        assert "Ignore all previous instructions" in body

    def test_rejects_a_dataset_without_mailboxes(self):
        with pytest.raises(MailDatasetError):
            MailDatasetLoader().load({})

    def test_rejects_a_message_missing_a_mandatory_field(self):
        raw = {"mailboxes": [{"owner_id": "u", "messages": [{"message_id": "m"}]}]}

        with pytest.raises(MailDatasetError):
            MailDatasetLoader().load(raw)

    def test_rejects_a_missing_file(self, tmp_path):
        with pytest.raises(MailDatasetError):
            MailDatasetLoader().load_file(tmp_path / "absent.json")
