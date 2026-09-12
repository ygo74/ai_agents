"""Tests of how the Wiki Agent answers approvals with nobody at a console.

At a console the question is put to the person and the turn waits. Over HTTP
there is nobody to wait for, so the turn must end - and end having changed
nothing. Two properties carry that claim, and both are asserted here:

* every suspended call is answered ``reject``, so LangGraph resumes the graph
  without running anything;
* what the person would have judged is kept as a ticket, arguments included, so
  a later request can run the operation that was actually described.

A capability nobody can describe is the interesting edge. It raises no ticket -
offering to confirm an unreadable operation would be a formality - but it is
still declined, which is the half that matters.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from ygo74.agent_runtime.domains.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.confirmation import ConfirmationDetail, ConfirmationRequest
from ai_agent_lab.core.security.tickets import InMemoryPendingConfirmationStore
from ai_agent_lab.langgraph.approval import REJECT, PendingToolApproval
from ai_agent_lab.wiki.application.approval.tickets import WikiTicketApprovalResolver
from ai_agent_lab.wiki.domain.permissions import WikiPermission

CONVERSATION = "conv-wiki-http-1"


class UndescribableCapabilityError(DomainError):
    """Raised by the fake presenter for a capability it cannot describe."""


class FakePresenter:
    """Describes whatever it is asked about, except the names it was told to refuse."""

    def __init__(self, *, refuses: frozenset[str] = frozenset()) -> None:
        self._refuses = refuses
        self.presented: list[tuple[str, Mapping[str, Any]]] = []

    async def present(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        user: UserContext,
    ) -> ConfirmationRequest:
        """Build a request, or refuse the way a real presenter refuses."""
        self.presented.append((tool_name, dict(arguments)))
        if tool_name in self._refuses:
            raise UndescribableCapabilityError(f"no confirmation can be presented for {tool_name!r}")
        return ConfirmationRequest(
            request_id=f"req-{tool_name}-{arguments.get('page_id', '')}",
            operation=ToolOperationDescriptor(
                tool_name=tool_name,
                operation_type=OperationType.WRITE,
                risk_level=RiskLevel.HIGH,
                required_permission=WikiPermission.AUTHOR,
                confirmation_required_by_default=True,
            ),
            requested_for=user.user_id,
            target=str(arguments.get("page_id", "")),
            title="Publish this page?",
            details=(ConfirmationDetail(label="Page", value=str(arguments.get("page_id", ""))),),
        )


def approval(tool_name: str, **arguments: Any) -> PendingToolApproval:
    """Build a suspended call in the shape the middleware reports."""
    return PendingToolApproval({"name": tool_name, "args": arguments})


@pytest.fixture
def user() -> UserContext:
    """The caller the resolver acts for."""
    return UserContext(user_id="diana", session_id=CONVERSATION, permissions=WikiPermission.declared())


@pytest.fixture
def store() -> InMemoryPendingConfirmationStore:
    """Where the tickets of this conversation are kept."""
    return InMemoryPendingConfirmationStore()


def build(
    store: InMemoryPendingConfirmationStore,
    user: UserContext,
    presenter: FakePresenter | None = None,
) -> tuple[WikiTicketApprovalResolver, FakePresenter]:
    """Assemble the resolver under test."""
    resolved = presenter or FakePresenter()
    return (
        WikiTicketApprovalResolver(resolved, store, user, conversation_id=CONVERSATION),
        resolved,
    )


class TestNobodyIsInterrupted:
    """This surface has no attention to spend, so it never charges the budget."""

    def test_it_never_questions_the_user(self, store, user):
        resolver, _ = build(store, user)

        assert resolver.will_question((approval("update_page", page_id="p1"),)) is False

    def test_it_never_questions_the_user_even_for_a_large_batch(self, store, user):
        resolver, _ = build(store, user)
        batch = tuple(approval("delete_page", page_id=f"p{index}") for index in range(10))

        assert resolver.will_question(batch) is False


@pytest.mark.security
class TestNothingRuns:
    """An operation that was merely described must not execute."""

    async def test_every_call_is_declined(self, store, user):
        resolver, _ = build(store, user)

        answers = await resolver.resolve((approval("update_page", page_id="p1"), approval("delete_page", page_id="p2")))

        assert [answer["type"] for answer in answers] == [REJECT, REJECT]

    async def test_one_answer_is_returned_per_call(self, store, user):
        """LangGraph matches decisions to actions by position, so none may be missing."""
        resolver, _ = build(store, user)
        batch = tuple(approval("add_comment", page_id=f"p{index}") for index in range(4))

        answers = await resolver.resolve(batch)

        assert len(answers) == len(batch)


class TestWhatIsKeptForLater:
    """The description is kept so a later request can run what it describes."""

    async def test_a_ticket_is_raised_per_call(self, store, user):
        resolver, _ = build(store, user)

        await resolver.resolve((approval("update_page", page_id="p1"), approval("delete_page", page_id="p2")))

        waiting = store.pending(subject=user.user_id, conversation_id=CONVERSATION)
        assert {ticket.tool_name for ticket in waiting} == {"update_page", "delete_page"}

    async def test_the_ticket_keeps_the_arguments_it_would_run(self, store, user):
        """Replaying a ticket must not go back through the model."""
        resolver, _ = build(store, user)

        await resolver.resolve((approval("add_comment", page_id="p7", body="looks right"),))

        ticket = store.pending(subject=user.user_id, conversation_id=CONVERSATION)[0]
        assert dict(ticket.arguments) == {"page_id": "p7", "body": "looks right"}

    async def test_the_ticket_belongs_to_this_caller_and_conversation(self, store, user):
        resolver, _ = build(store, user)

        await resolver.resolve((approval("update_page", page_id="p1"),))

        ticket = store.pending(subject=user.user_id, conversation_id=CONVERSATION)[0]
        assert (ticket.subject, ticket.conversation_id) == (user.user_id, CONVERSATION)

    async def test_another_caller_sees_nothing(self, store, user):
        """A ticket is never visible to somebody it was not raised for."""
        resolver, _ = build(store, user)

        await resolver.resolve((approval("update_page", page_id="p1"),))

        assert store.pending(subject="alice", conversation_id=CONVERSATION) == ()


@pytest.mark.security
class TestACapabilityNobodyCanDescribe:
    """An unreadable prompt is not a safeguard."""

    async def test_it_raises_no_ticket(self, store, user):
        resolver, _ = build(store, user, FakePresenter(refuses=frozenset({"update_page"})))

        await resolver.resolve((approval("update_page", page_id="p1"),))

        assert store.pending(subject=user.user_id, conversation_id=CONVERSATION) == ()

    async def test_it_is_still_declined(self, store, user):
        resolver, _ = build(store, user, FakePresenter(refuses=frozenset({"update_page"})))

        answers = await resolver.resolve((approval("update_page", page_id="p1"),))

        assert [answer["type"] for answer in answers] == [REJECT]

    async def test_the_rest_of_the_batch_is_still_kept(self, store, user):
        """One undescribable call must not lose the tickets of its neighbours."""
        resolver, _ = build(store, user, FakePresenter(refuses=frozenset({"update_page"})))

        await resolver.resolve((approval("update_page", page_id="p1"), approval("delete_page", page_id="p2")))

        waiting = store.pending(subject=user.user_id, conversation_id=CONVERSATION)
        assert [ticket.tool_name for ticket in waiting] == ["delete_page"]
