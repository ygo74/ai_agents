"""Tests of confirming an operation across two turns.

Serving over HTTP removes the side channel a console has: the request must be
answered, so nothing can wait for a person. A gated operation therefore ends its
turn unperformed, and comes back as a ticket the user quotes in a later message.

What these tests pin is that the deferral is not a weakening. The operation still
does not happen without an explicit answer; the answer still authorises exactly
the operation that was described; and the replay takes its arguments from the
ticket rather than from whatever a model says the second time.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says

from ai_agent_lab.core.security.commands import ConfirmationCommandParser
from ai_agent_lab.core.security.tickets import (
    InMemoryPendingConfirmationStore,
    UnknownTicketError,
)
from ai_agent_lab.maf.approval import MafApprovalTranslator
from ai_agent_lab.mail.application.approval.tickets import (
    ConfirmedOperationRunner,
    TicketApprovalResolver,
)
from ai_agent_lab.mail.application.composition import MailAgentCompositionRoot
from ai_agent_lab.mail.application.session import MailAgentSession
from ai_agent_lab.mail.capabilities.results import MailToolResultRenderer
from ai_agent_lab.mail.catalog import MailToolName
from ai_agent_lab.mail.config.settings import MailAgentSettings
from ai_agent_lab.mail.inmemory.reasoner import ScriptedTextReasoner

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CONVERSATION = "conv-http-1"
MESSAGE_ID = "m-alpha-1"
LABEL_ID = "FINANCE"


def gated_settings() -> MailAgentSettings:
    """Settings under which labelling is confirmed.

    Stated here rather than inherited from the delivered packages: those are
    configuration a deployment is meant to tune, and `apply_label` ships
    unconfirmed. A test that borrowed whatever they happened to say would pass
    or fail for reasons unrelated to this code.
    """
    return MailAgentSettings(always_confirm_tools=MailToolName.APPLY_LABEL.value)


class TicketSurface:
    """A Mail Agent driven the way an HTTP request would drive it."""

    def __init__(self, script):
        self.client = ScriptedChatClient(script)
        self.runtime = MailAgentCompositionRoot(
            gated_settings(),
            self.client,
            reasoner=ScriptedTextReasoner({}),
            base_path=REPOSITORY_ROOT,
        ).build(session_id=CONVERSATION)
        self.store = InMemoryPendingConfirmationStore()
        self.session = MailAgentSession(
            self.runtime,
            TicketApprovalResolver(
                self.runtime.presenter,
                self.store,
                self.runtime.user,
                conversation_id=CONVERSATION,
            ),
            MafApprovalTranslator(),
        )
        self.runner = ConfirmedOperationRunner(
            self.runtime.registry,
            self.store,
            self.runtime.confirmation_ledger,
            MailToolResultRenderer(),
            self.runtime.user,
            conversation_id=CONVERSATION,
        )

    async def ask(self, message: str) -> str:
        """Run one turn, exactly as an HTTP request would."""
        return await self.session.ask(message)

    async def answer(self, text: str) -> str:
        """Read a confirmation out of a later message and honour it."""
        command = ConfirmationCommandParser().parse(text)
        assert command is not None, f"{text!r} is not a confirmation"
        return await self.runner.run(command)

    def tickets(self):
        """The confirmations this conversation is waiting on."""
        return self.store.pending(subject=self.runtime.user.user_id, conversation_id=CONVERSATION)

    async def labels_of(self, message_id: str) -> tuple[str, ...]:
        """Read back what the mailbox actually holds."""
        message = await self.runtime.mail_tools.get_message(message_id, self.runtime.user)
        return message.label_ids


def labelling_surface() -> TicketSurface:
    """A surface whose model asks to label one message."""
    return TicketSurface(
        [
            calls(ToolCall(MailToolName.APPLY_LABEL.value, {"message_id": MESSAGE_ID, "label_id": LABEL_ID})),
            says("I have asked for confirmation."),
        ]
    )


@pytest.mark.security
class TestTheFirstTurnChangesNothing:
    """Describing an operation must never perform it."""

    async def test_the_mailbox_is_untouched(self):
        surface = labelling_surface()
        before = await surface.labels_of(MESSAGE_ID)

        await surface.ask("Please file the Project Alpha message under Finance")

        assert await surface.labels_of(MESSAGE_ID) == before
        assert LABEL_ID not in await surface.labels_of(MESSAGE_ID)

    async def test_a_ticket_is_left_waiting(self):
        surface = labelling_surface()

        await surface.ask("Please file the Project Alpha message under Finance")

        pending = surface.tickets()
        assert len(pending) == 1
        assert pending[0].tool_name == MailToolName.APPLY_LABEL.value

    async def test_the_ticket_carries_what_will_run(self):
        """The arguments are kept so the replay cannot drift from the description."""
        surface = labelling_surface()

        await surface.ask("Please file the Project Alpha message under Finance")

        assert surface.tickets()[0].arguments == {"message_id": MESSAGE_ID, "label_id": LABEL_ID}

    async def test_the_turn_asks_nobody_and_still_ends(self):
        """An HTTP turn must answer; it cannot block on a person."""
        surface = labelling_surface()

        answer = await surface.ask("Please file the Project Alpha message under Finance")

        assert isinstance(answer, str)


class TestConfirmingPerformsExactlyWhatWasDescribed:
    """The second turn runs the stored operation, not a new one."""

    async def test_the_label_is_applied(self):
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]

        await surface.answer(f"confirm {ticket.ticket_id}")

        assert LABEL_ID in await surface.labels_of(MESSAGE_ID)

    async def test_the_ticket_cannot_be_used_twice(self):
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]
        await surface.answer(f"confirm {ticket.ticket_id}")

        with pytest.raises(UnknownTicketError):
            await surface.answer(f"confirm {ticket.ticket_id}")

    async def test_nothing_is_left_pending_afterwards(self):
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]

        await surface.answer(f"confirm {ticket.ticket_id}")

        assert surface.tickets() == ()


@pytest.mark.security
class TestCancellingChangesNothing:
    """A refusal must consume the ticket and leave the mailbox alone."""

    async def test_the_label_is_not_applied(self):
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]

        await surface.answer(f"cancel {ticket.ticket_id}")

        assert LABEL_ID not in await surface.labels_of(MESSAGE_ID)

    async def test_a_cancelled_ticket_cannot_then_be_confirmed(self):
        """Otherwise "no" would only mean "not yet"."""
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]
        await surface.answer(f"cancel {ticket.ticket_id}")

        with pytest.raises(UnknownTicketError):
            await surface.answer(f"confirm {ticket.ticket_id}")

    async def test_the_refusal_says_nothing_was_changed(self):
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]

        assert "Nothing was changed" in await surface.answer(f"cancel {ticket.ticket_id}")


@pytest.mark.security
class TestAConfirmationAuthorisesOneOperation:
    """An answer must not widen into a batch."""

    async def test_it_labels_the_message_it_named_and_no_other(self):
        """The ticket carries one message, so confirming it touches one message.

        This is what stops "yes" to a described operation from becoming "yes" to
        everything the model found while looking for it.
        """
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        ticket = surface.tickets()[0]

        await surface.answer(f"confirm {ticket.ticket_id}")

        assert LABEL_ID in await surface.labels_of(MESSAGE_ID)
        assert LABEL_ID not in await surface.labels_of("m-newsletter-1")
        assert LABEL_ID not in await surface.labels_of("m-injection-1")

    async def test_a_second_proposal_needs_its_own_ticket(self):
        """Confirming one operation must not clear the way for the next.

        The model asks to label another message in a later turn. That call is
        suspended and ticketed exactly like the first, so the mailbox is
        unchanged until somebody answers *that* ticket too.
        """
        surface = labelling_surface()
        await surface.ask("Please file the Project Alpha message under Finance")
        await surface.answer(f"confirm {surface.tickets()[0].ticket_id}")

        surface.client.append(
            calls(ToolCall(MailToolName.APPLY_LABEL.value, {"message_id": "m-newsletter-1", "label_id": LABEL_ID})),
            says("I have asked for confirmation."),
        )
        await surface.ask("Now file the newsletter under Finance too")

        assert LABEL_ID not in await surface.labels_of("m-newsletter-1")
        assert len(surface.tickets()) == 1
