"""A mail MCP server implementing our contract, over stdio.

Its purpose is not to be a product. It is the reference implementation of the
mail tool surface: it exposes our ten logical tools, speaks the payload contract
of :mod:`ai_agent_lab.mcp.mail.payloads`, and is backed by a deterministic
dataset rather than by any real mail system.

That makes two things possible:

- the real MCP client can be exercised over a real protocol stack, with no
  network, no credentials and no mailbox, so the conformance suite runs offline;
- a server built on EWS or Microsoft Graph has something concrete to match. If
  it answers these ten tools with these payloads, the agent works against it
  without a single line of adaptation.

Authorisation is deliberately reproduced here: a server is the authority on who
may read a mailbox, and a double that ignored that would let the client pass
tests it would fail in production.
"""

from __future__ import annotations

import argparse
from collections.abc import Awaitable, Callable, Sequence
from functools import wraps
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field

from ai_agent_lab.domain.mail.models import MailSearchRequest, MailSendRequest
from ai_agent_lab.domain.mail.permissions import MailPermission
from ai_agent_lab.domain.security.context import UserContext
from ai_agent_lab.infrastructure.config.environment import EnvironmentFile
from ai_agent_lab.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.infrastructure.inmemory.mail_tools import InMemoryMailTools
from ai_agent_lab.mcp.mail.contracts import MailTools
from ai_agent_lab.mcp.mail.errors import MailToolError, encode_failure
from ai_agent_lab.mcp.mail.payloads import (
    DraftPayload,
    LabelsPayload,
    MessagePayload,
    SearchResultPayload,
    SendResultPayload,
    ThreadPayload,
)

DEFAULT_DATASET = Path("data/mail/sample_mailbox.json")
SERVER_NAME = "ai-agent-lab-mail"

MailboxOwner = Annotated[str, Field(description="Identifier of the mailbox owner the call acts for.")]
MessageId = Annotated[str, Field(description="Identifier of a message.")]
ThreadId = Annotated[str, Field(description="Identifier of a conversation.")]
LabelId = Annotated[str, Field(description="Identifier of a label.")]


def reporting[**P, R](tool: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Report a mail failure under the code the contract defines.

    Without the code, a client cannot tell a message that does not exist from a
    mailbox it may not read, and would be left guessing from prose.
    """

    @wraps(tool)
    async def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return await tool(*args, **kwargs)
        except MailToolError as error:
            raise ToolError(encode_failure(error)) from error

    return guarded


class ReferenceMailServer:
    """Serves the mail tool surface from a mailbox implementation.

    The backend is injected: a deterministic dataset for tests and demos, or the
    Gmail API for a real mailbox. The tools, the payloads and the error codes are
    identical either way, which is the whole point of putting a contract here.
    """

    def __init__(self, mail_tools: MailTools) -> None:
        self._mail_tools = mail_tools
        self._server = FastMCP(SERVER_NAME)
        self._register()

    def run(self) -> None:
        """Serve the tools over stdio until the client disconnects."""
        self._server.run()

    @staticmethod
    def _user(owner: str) -> UserContext:
        """Build the context a call acts under.

        A real server derives this from its own authentication. The reference
        server takes it as an argument so that mailbox isolation stays testable.
        """
        return UserContext(user_id=owner, session_id="mcp", permissions=MailPermission.declared())

    def _register(self) -> None:
        """Expose every tool of the contract."""
        self._register_read()
        self._register_write()

    def _register_read(self) -> None:
        """Expose the tools that never change anything."""

        @self._server.tool(description="Search the mailbox and return message headers.")
        @reporting
        async def search_mail(
            owner: MailboxOwner,
            keywords: str | None = None,
            sender: str | None = None,
            recipient: str | None = None,
            subject_contains: str | None = None,
            label_ids: Sequence[str] = (),
            date_from: str | None = None,
            date_to: str | None = None,
            unread_only: bool = False,
            has_attachments: bool | None = None,
            limit: int = 20,
            sort_order: str = "NEWEST_FIRST",
        ) -> SearchResultPayload:
            request = MailSearchRequest.model_validate(
                {
                    "keywords": keywords,
                    "sender": None if sender is None else {"value": sender},
                    "recipient": None if recipient is None else {"value": recipient},
                    "subject_contains": subject_contains,
                    "label_ids": tuple(label_ids),
                    "date_from": date_from,
                    "date_to": date_to,
                    "unread_only": unread_only,
                    "has_attachments": has_attachments,
                    "limit": limit,
                    "sort_order": sort_order,
                }
            )
            return SearchResultPayload.of(await self._mail_tools.search(request, self._user(owner)))

        @self._server.tool(description="Retrieve one complete message, body included.")
        @reporting
        async def get_mail(owner: MailboxOwner, message_id: MessageId) -> MessagePayload:
            return MessagePayload.of(await self._mail_tools.get_message(message_id, self._user(owner)))

        @self._server.tool(description="Retrieve every message of a conversation.")
        @reporting
        async def get_thread(owner: MailboxOwner, thread_id: ThreadId) -> ThreadPayload:
            return ThreadPayload.of(await self._mail_tools.get_thread(thread_id, self._user(owner)))

        @self._server.tool(description="List the labels available in the mailbox.")
        @reporting
        async def list_labels(owner: MailboxOwner) -> LabelsPayload:
            return LabelsPayload.of(await self._mail_tools.list_labels(self._user(owner)))

    def _register_write(self) -> None:
        """Expose the tools that change something."""

        @self._server.tool(description="Save a prepared message as a draft. Delivers nothing.")
        @reporting
        async def create_draft(owner: MailboxOwner, draft: DraftPayload) -> DraftPayload:
            stored = await self._mail_tools.create_draft(draft.to_domain(), self._user(owner))
            return DraftPayload.of(stored)

        @self._server.tool(description="Deliver a prepared message to its recipients. Irreversible.")
        @reporting
        async def send_mail(owner: MailboxOwner, draft: DraftPayload) -> SendResultPayload:
            request = MailSendRequest(draft=draft.to_domain())
            return SendResultPayload.of(await self._mail_tools.send(request, self._user(owner)))

        @self._server.tool(description="Mark a message as read or unread.")
        @reporting
        async def mark_read(owner: MailboxOwner, message_id: MessageId, is_read: bool) -> str:
            await self._mail_tools.set_read_state(message_id, is_read, self._user(owner))
            return "ok"

        @self._server.tool(description="Remove a message from the inbox without deleting it.")
        @reporting
        async def archive_mail(owner: MailboxOwner, message_id: MessageId) -> str:
            await self._mail_tools.archive(message_id, self._user(owner))
            return "ok"

        @self._server.tool(description="Attach a label to a message.")
        @reporting
        async def apply_label(owner: MailboxOwner, message_id: MessageId, label_id: LabelId) -> str:
            await self._mail_tools.apply_label(message_id, label_id, self._user(owner))
            return "ok"

        @self._server.tool(description="Detach a label from a message.")
        @reporting
        async def remove_label(owner: MailboxOwner, message_id: MessageId, label_id: LabelId) -> str:
            await self._mail_tools.remove_label(message_id, label_id, self._user(owner))
            return "ok"


def build_server(dataset: Path) -> ReferenceMailServer:
    """Assemble the server over a deterministic dataset."""
    return ReferenceMailServer(InMemoryMailTools(MailDatasetLoader().load_file(dataset)))


def build_gmail_server() -> ReferenceMailServer:
    """Assemble the server over a real mailbox, through the Gmail API.

    The Google credential lives in this process and nowhere else: the agent
    talks to this server over stdio and never sees a token.
    """
    from ai_agent_lab.infrastructure.gmail.api import GmailApiClient
    from ai_agent_lab.infrastructure.gmail.credentials import GmailCredentials
    from ai_agent_lab.infrastructure.gmail.mail_tools import GmailApiMailTools

    return ReferenceMailServer(GmailApiMailTools(GmailApiClient(GmailCredentials())))


def main() -> None:
    """Entry point of ``python -m ai_agent_lab.infrastructure.mcp.reference_server``."""
    parser = argparse.ArgumentParser(description="Mail MCP server implementing the contract.")
    parser.add_argument("--backend", choices=("dataset", "gmail"), default="dataset")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    arguments = parser.parse_args()

    if arguments.backend == "gmail":
        EnvironmentFile().load()
        build_gmail_server().run()
        return
    build_server(arguments.dataset).run()


if __name__ == "__main__":
    main()
