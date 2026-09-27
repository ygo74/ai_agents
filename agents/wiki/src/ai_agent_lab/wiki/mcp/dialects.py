"""Wiki dialect factories registered with the generic runtime registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ygo74.agent_runtime.domains.mcp.dialects import DialectRegistry

from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.mcp.atlassian.client import AtlassianWikiTools
from ai_agent_lab.wiki.mcp.binding import McpServerBinding
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.mcp.native.client import McpWikiTools
from ai_agent_lab.wiki.tools_port import WikiTools
from ai_agent_lab.wiki.wiki_errors import WikiToolUnavailableError


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


class WikiDialectRegistry(DialectRegistry[WikiTools, [McpConnection, DialectContext]]):
    """Supply Wiki's dialect choices to the shared registry mechanics."""

    def __init__(self, dialects: Mapping[str, DialectFactory] | None = None) -> None:
        super().__init__(dialects or {NATIVE: _native, ATLASSIAN: _atlassian}, unavailable=WikiToolUnavailableError)
