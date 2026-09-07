"""Catalogue of the mail MCP tools.

Every capability declares, as data, what it does to the outside world. That
declaration feeds the confirmation policy and the audit trail, and it is written
in code so no model output can alter it.

What is written here is the *default*. A delivered skill package may change it,
within the limits :class:`MailSecurityFloor` imposes, and what a deployment
actually runs under is then read back through :class:`DeliveredMailOperations`.
Both guards read the same one, which is the point.

Descriptions matter: the language model uses them to choose a tool, so an
ambiguous description is a correctness defect, not a cosmetic one.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ai_agent_lab.core.manifests import AgentManifest
from ai_agent_lab.core.security.operations import (
    OperationType,
    RiskLevel,
    ToolOperationDescriptor,
)
from ai_agent_lab.core.security.permissions import Permission
from ai_agent_lab.mail.domain.permissions import MailPermission


class MailToolName(StrEnum):
    """Stable identifiers of the mail MCP tools."""

    SEARCH_MAIL = "search_mail"
    GET_MAIL = "get_mail"
    GET_THREAD = "get_thread"
    LIST_LABELS = "list_labels"
    CREATE_DRAFT = "create_draft"
    SEND_MAIL = "send_mail"
    MARK_READ = "mark_read"
    ARCHIVE_MAIL = "archive_mail"
    APPLY_LABEL = "apply_label"
    REMOVE_LABEL = "remove_label"
    CREATE_LABEL = "create_label"
    DELETE_LABEL = "delete_label"


def _read(name: MailToolName) -> ToolOperationDescriptor:
    """Build the descriptor of a read-only, ungated operation."""
    return ToolOperationDescriptor(
        tool_name=name.value,
        operation_type=OperationType.READ,
        risk_level=RiskLevel.LOW,
        required_permission=MailPermission.READ,
        confirmation_required_by_default=False,
    )


def _write(
    name: MailToolName,
    risk_level: RiskLevel,
    permission: Permission,
    *,
    confirmation_required: bool = True,
) -> ToolOperationDescriptor:
    """Build the descriptor of a state-changing operation."""
    return ToolOperationDescriptor(
        tool_name=name.value,
        operation_type=OperationType.WRITE,
        risk_level=risk_level,
        required_permission=permission,
        confirmation_required_by_default=confirmation_required,
    )


_DESCRIPTORS: Mapping[MailToolName, ToolOperationDescriptor] = {
    MailToolName.SEARCH_MAIL: _read(MailToolName.SEARCH_MAIL),
    MailToolName.GET_MAIL: _read(MailToolName.GET_MAIL),
    MailToolName.GET_THREAD: _read(MailToolName.GET_THREAD),
    MailToolName.LIST_LABELS: _read(MailToolName.LIST_LABELS),
    # Creating a draft mutates the mailbox but delivers nothing, so it is a
    # low-risk write that is not gated by default. It stays configurable.
    MailToolName.CREATE_DRAFT: _write(
        MailToolName.CREATE_DRAFT,
        RiskLevel.LOW,
        MailPermission.DRAFT,
        confirmation_required=False,
    ),
    MailToolName.SEND_MAIL: _write(MailToolName.SEND_MAIL, RiskLevel.HIGH, MailPermission.SEND),
    MailToolName.MARK_READ: _write(MailToolName.MARK_READ, RiskLevel.LOW, MailPermission.MANAGE),
    MailToolName.ARCHIVE_MAIL: _write(MailToolName.ARCHIVE_MAIL, RiskLevel.MEDIUM, MailPermission.MANAGE),
    MailToolName.APPLY_LABEL: _write(MailToolName.APPLY_LABEL, RiskLevel.MEDIUM, MailPermission.MANAGE),
    MailToolName.REMOVE_LABEL: _write(MailToolName.REMOVE_LABEL, RiskLevel.MEDIUM, MailPermission.MANAGE),
    # Creating a label changes the mailbox but destroys nothing and is undone by
    # deleting it, so it is not gated by default. It stays configurable.
    MailToolName.CREATE_LABEL: _write(
        MailToolName.CREATE_LABEL,
        RiskLevel.LOW,
        MailPermission.MANAGE,
        confirmation_required=False,
    ),
    # Deleting a label also strips it from every message that carried it, and
    # nothing records which those were. That is why it sits at the same risk
    # level as sending.
    MailToolName.DELETE_LABEL: _write(MailToolName.DELETE_LABEL, RiskLevel.HIGH, MailPermission.MANAGE),
}

_DESCRIPTIONS: Mapping[MailToolName, str] = {
    MailToolName.SEARCH_MAIL: (
        "Search the mailbox and return message headers. Supports sender, recipient, subject, "
        "free-text keywords, label, date range, unread state and attachment filters, alone or "
        "combined. Labels are given as identifiers from the label listing, and several labels "
        "narrow the search to messages carrying all of them. Returns previews only, never "
        "message bodies. Has no side effect."
    ),
    MailToolName.GET_MAIL: "Retrieve one complete message, body included, by message identifier. Has no side effect.",
    MailToolName.GET_THREAD: (
        "Retrieve every message of a conversation, bodies included, by thread identifier. Has no side effect."
    ),
    MailToolName.LIST_LABELS: "List the labels and folders available in the mailbox. Has no side effect.",
    MailToolName.CREATE_DRAFT: (
        "Save a prepared message as a draft in the mailbox. The message is NOT delivered to anyone."
    ),
    MailToolName.SEND_MAIL: (
        "Deliver a prepared message to its recipients. This is irreversible and always requires "
        "an explicit confirmation from the user."
    ),
    MailToolName.MARK_READ: "Mark a message as read or unread. Modifies the mailbox.",
    MailToolName.ARCHIVE_MAIL: "Remove a message from the inbox without deleting it. Modifies the mailbox.",
    MailToolName.APPLY_LABEL: "Attach a label or category to a message. Modifies the mailbox.",
    MailToolName.REMOVE_LABEL: "Detach a label or category from a message. Modifies the mailbox.",
    MailToolName.CREATE_LABEL: (
        "Make a label exist in the mailbox, so messages can be filed under it. Use this before "
        "applying a label that does not appear in the label listing. If a label with that name "
        "already exists it is returned unchanged and nothing is created. Creates no message and "
        "sends nothing."
    ),
    MailToolName.DELETE_LABEL: (
        "Delete a label from the mailbox. The label is also detached from every message that "
        "carried it, and which messages those were is not recorded anywhere. This is irreversible "
        "and requires an explicit confirmation from the user. To take a label off a single message, "
        "use remove_label instead. Labels belonging to the mail system cannot be deleted."
    ),
}


class MailToolCatalog:
    """Read-only registry of the mail MCP tool metadata."""

    def descriptor(self, name: MailToolName) -> ToolOperationDescriptor:
        """Return the security metadata of a tool."""
        return _DESCRIPTORS[name]

    def description(self, name: MailToolName) -> str:
        """Return the description used by a model to select a tool."""
        return _DESCRIPTIONS[name]

    def names(self) -> tuple[MailToolName, ...]:
        """Return every catalogued tool name."""
        return tuple(_DESCRIPTORS)

    def write_tools(self) -> tuple[MailToolName, ...]:
        """Return the tools that modify external state."""
        return tuple(name for name, descriptor in _DESCRIPTORS.items() if descriptor.is_write)


@runtime_checkable
class MailOperations(Protocol):
    """Where the security posture of a mail operation is read from.

    There must be exactly one answer per deployment. The framework decides
    whether to suspend a call, and the skill decides whether to run it; if those
    two consulted different sources, a capability could be one the framework
    never asks about and the skill always refuses. It would then be impossible
    to perform, and the model would report that the mailbox had refused.
    """

    def descriptor(self, name: MailToolName) -> ToolOperationDescriptor:
        """Return the security metadata of a tool."""
        ...


class DeliveredMailOperations:
    """The posture the delivered configuration declares.

    :class:`MailToolCatalog` holds what the code proposes; a skill package may
    change it, within what :class:`MailSecurityFloor` allows. This reads back
    what was actually loaded, so the confirmation policy, the framework adapter
    and the domain guard all obey the same file.

    A tool the manifest does not describe falls back to the coded default: the
    manifest only carries the capabilities a deployment offers, and a guard
    asked about anything else should be no weaker for it.
    """

    def __init__(self, manifest: AgentManifest, fallback: MailToolCatalog | None = None) -> None:
        self._manifest = manifest
        self._fallback = fallback or MailToolCatalog()
        self._declared = {skill.tool_name: skill.operation for skill in manifest.skills}

    def descriptor(self, name: MailToolName) -> ToolOperationDescriptor:
        """Return the security metadata this deployment declares."""
        declared = self._declared.get(name.value)
        return declared if declared is not None else self._fallback.descriptor(name)
