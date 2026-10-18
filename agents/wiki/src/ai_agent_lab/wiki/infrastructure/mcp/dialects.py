"""Wiki dialect factories registered with the generic runtime registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ygo74.agent_runtime.domains.mcp.binding import McpConnection, McpServerBinding
from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry

from ai_agent_lab.wiki.application.ports.wiki_tools import WikiTools
from ai_agent_lab.wiki.domain.operation_names import WikiToolName
from ai_agent_lab.wiki.domain.tool_errors import WikiToolUnavailableError
from ai_agent_lab.wiki.infrastructure.mcp.atlassian.client import AtlassianWikiTools
from ai_agent_lab.wiki.infrastructure.mcp.native.client import McpWikiTools


@dataclass(frozen=True, slots=True)
class DialectContext:
    """Application identity data needed by a concrete Wiki dialect."""

    account_id: str = ""
    is_per_user: bool = False


NATIVE = "native"
ATLASSIAN = "atlassian"
DialectFactory = Callable[[McpServerBinding[WikiToolName], McpConnection, DialectContext], WikiTools]


def _native(
    binding: McpServerBinding[WikiToolName], connection: McpConnection, context: DialectContext
) -> WikiTools:
    """Build the client of a server implementing the Wiki protocol."""
    del context
    return McpWikiTools(connection, binding)


def _atlassian(
    binding: McpServerBinding[WikiToolName], connection: McpConnection, context: DialectContext
) -> WikiTools:
    """Build the client of sooperset/mcp-atlassian for one account context."""
    return AtlassianWikiTools(
        connection,
        binding,
        account_id=context.account_id,
        is_per_user=context.is_per_user,
    )


def create_dialect_registry(
    dialects: Mapping[str, DialectFactory] | None = None,
) -> DialectRegistry[WikiTools, [McpConnection, DialectContext]]:
    """Create the runtime registry populated with Wiki's concrete dialects.

    Args:
        dialects: Optional application dialect factories used in place of the defaults.
    """
    return DialectRegistry(
        dialects or {NATIVE: _native, ATLASSIAN: _atlassian},
        unavailable=WikiToolUnavailableError,
    )
