"""Resolution of the identifiers a confirmation would otherwise show raw.

A person asked to approve "apply_label to 1a0027bd9c6c5d17 with Label_5" is not
being asked anything: they cannot tell which message it is, nor which label, so
the only honest answer is no. Approving without understanding is the failure
mode a confirmation exists to prevent, and an unreadable prompt produces it.

So the identifiers are resolved into what the mailbox owner actually recognises:
the subject and sender of the message, and the name of the label.

Two properties matter here:

- **Nothing is invented.** A lookup that fails leaves the identifier in place
  rather than guessing, because a confirmation that misdescribes an operation is
  worse than one that under-describes it.
- **Content stays fenced.** A subject is written by whoever sent the message, so
  it is shown as untrusted text and never given any other standing.
"""

from __future__ import annotations

from ai_agent_lab.core.errors import DomainError
from ai_agent_lab.core.security.context import UserContext
from ai_agent_lab.mail.skills.management_skill import MailManagementSkill
from ai_agent_lab.mail.skills.search_skill import MailReadSkill

# Enough to recognise a message; not so much that the prompt scrolls away.
_SUBJECT_LIMIT = 80


class MailSubject:
    """What a message is, in the terms its owner would use."""

    def __init__(self, subject: str, sender: str) -> None:
        self.subject = subject
        self.sender = sender


class ConfirmationSubjectResolver:
    """Turns the identifiers of a pending operation into readable facts.

    Results are cached for the lifetime of the resolver. Labelling twenty
    messages would otherwise list the mailbox labels twenty times, and each of
    those calls sits between the user and the question they are being asked.
    """

    def __init__(self, read_skill: MailReadSkill, management_skill: MailManagementSkill) -> None:
        self._read_skill = read_skill
        self._management_skill = management_skill
        self._messages: dict[str, MailSubject | None] = {}
        self._labels: dict[str, str] | None = None

    async def message(self, message_id: str, user: UserContext) -> MailSubject | None:
        """Return what a message is about, or ``None`` when it cannot be read."""
        if message_id in self._messages:
            return self._messages[message_id]
        described = await self._describe(message_id, user)
        self._messages[message_id] = described
        return described

    async def label_name(self, label_id: str, user: UserContext) -> str | None:
        """Return the name of a label, or ``None`` when it cannot be resolved."""
        names = await self._label_names(user)
        return names.get(label_id)

    async def _describe(self, message_id: str, user: UserContext) -> MailSubject | None:
        """Read a message for the sole purpose of naming it."""
        if not message_id:
            return None
        try:
            message = await self._read_skill.read_message(message_id, user)
        except DomainError:
            return None
        return MailSubject(subject=_shortened(message.subject.expose()), sender=str(message.sender.address))

    async def _label_names(self, user: UserContext) -> dict[str, str]:
        """Return every label name, reading the mailbox at most once."""
        if self._labels is not None:
            return self._labels
        try:
            labels = await self._management_skill.list_labels(user)
        except DomainError:
            self._labels = {}
            return self._labels
        self._labels = {label.label_id: label.name.expose() for label in labels}
        return self._labels


def _shortened(subject: str) -> str:
    """Keep a subject to one readable line."""
    collapsed = " ".join(subject.split())
    if len(collapsed) <= _SUBJECT_LIMIT:
        return collapsed
    return f"{collapsed[: _SUBJECT_LIMIT - 1]}…"
