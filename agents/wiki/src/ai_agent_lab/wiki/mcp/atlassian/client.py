"""Translation between `sooperset/mcp-atlassian` and the wiki domain.

That server was not written for us, and adapting to it is the normal case. What
follows is what its v0.23.1 source actually does, verified against the code
rather than its documentation - several things differ.

**Everything comes back as a JSON string.** Every tool is annotated ``-> str``
and ends in ``json.dumps(...)``, so the payload is text inside a content block.
FastMCP does emit ``structuredContent``, but wrapped as ``{"result": "<json
string>"}`` - the value is still a string. This dialect therefore parses text,
which is exactly the fragility documented in the repository structure notes.

**Failures arrive two different ways.** Some tools raise, and the call is marked
as an error. Others catch the failure and return ``{"error": ...}`` or
``{"success": false}`` as a *successful* result. A client that only checked
``isError`` would read a failure as a success, so both are checked here.

**Three capabilities do not exist on that server**, and the binding therefore
does not declare them:

- there is no space-listing tool, so :meth:`list_spaces` runs a CQL search for
  ``type = space``;
- ``confluence_get_page_history`` returns *one named revision*, not the list of
  revisions. Our ``get_page_history`` capability cannot be honoured and is left
  out of the binding rather than faked;
- there is no optimistic concurrency on ``confluence_update_page``. See
  :meth:`update_page`.

**Identity comes from the transport, never from an argument.** No Confluence tool
takes an account parameter; the server resolves the caller from the
``Authorization`` header. Over stdio there is no per-request header, so such a
deployment acts as exactly one person, and this dialect refuses to serve anybody
else.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from mcp.types import CallToolResult, TextContent
from ygo74.agent_runtime.domains.security.untrusted import untrusted
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.enums import WikiContentFormat, WikiPageStatus, WikiSortOrder
from ai_agent_lab.wiki.domain.models import (
    MAX_SEARCH_LIMIT,
    WikiAuthor,
    WikiComment,
    WikiPage,
    WikiPageHistory,
    WikiPageReference,
    WikiPageTree,
    WikiSearchRequest,
    WikiSearchResult,
    WikiSpace,
)
from ai_agent_lab.wiki.domain.origins import WikiOrigin
from ai_agent_lab.wiki.mcp.binding import McpServerBinding
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.wiki_errors import (
    WikiAccessDeniedError,
    WikiConcurrentEditError,
    WikiNotFoundError,
    WikiToolError,
    WikiToolProtocolError,
    WikiToolUnavailableError,
)

_logger = logging.getLogger(__name__)

# Aliases this dialect knows how to call. A binding names the ones it serves;
# `list_spaces` is absent because this server has no space-listing tool and the
# capability is served by the search tool instead.
KNOWN_ALIASES = (
    "search_wiki",
    "get_page",
    "get_page_children",
    "get_comments",
    "create_page",
    "update_page",
    "delete_page",
    "add_comment",
)

# `to_simplified_dict` reformats timestamps to this, in the server's local time
# zone, rather than leaving them ISO 8601.
_ATLASSIAN_TIMESTAMP = "%Y-%m-%d %H:%M:%S"

_DENIED_MARKERS = ("permission", "not permitted", "unauthorized", "unauthorised", "forbidden", "denied")
_MISSING_MARKERS = ("not found", "does not exist", "no such")


class AtlassianWikiTools:
    """Wiki tools served by `sooperset/mcp-atlassian`."""

    def __init__(
        self,
        connection: McpConnection,
        binding: McpServerBinding,
        *,
        account_id: str = "",
        is_per_user: bool = False,
    ) -> None:
        binding.require_aliases(self._needed_aliases(binding))
        self._connection = connection
        self._binding = binding
        self._account_id = account_id
        self._is_per_user = is_per_user

    @staticmethod
    def _needed_aliases(binding: McpServerBinding) -> tuple[str, ...]:
        """Return the tool names this dialect must be able to call.

        The tools of the declared capabilities, plus the search tool whenever
        ``list_spaces`` is declared: this server exposes no space-listing tool,
        so that capability is served by a CQL search and would otherwise fail on
        its first call rather than at load time.
        """
        needed = {capability.value for capability in binding.capabilities}
        if WikiToolName.LIST_SPACES in binding.capabilities:
            needed.add(WikiToolName.SEARCH_WIKI.value)
        return tuple(sorted(needed))

    async def search(self, request: WikiSearchRequest, user: UserContext) -> WikiSearchResult:
        """Return the page references matching a structured query."""
        self._require_served_account(user)
        payload = await self._call(
            "search_wiki",
            query=CqlQueryBuilder().build(request),
            limit=min(request.limit, MAX_SEARCH_LIMIT),
        )
        pages = self._as_list(payload, "search_wiki")
        return WikiSearchResult(
            references=tuple(self._reference(item) for item in pages),
            # The server reports no total, so what came back is all we know of.
            # Claiming a larger total would be inventing a number.
            total_count=len(pages),
            truncated=len(pages) >= request.limit,
        )

    async def get_page(self, page_id: str, user: UserContext) -> WikiPage:
        """Return one complete page, body included."""
        self._require_served_account(user)
        payload = await self._call("get_page", page_id=page_id, include_metadata=True, convert_to_markdown=True)
        document = self._as_object(payload, "get_page")
        metadata = document.get("metadata")
        if not isinstance(metadata, Mapping):
            raise WikiToolProtocolError("confluence_get_page returned no page metadata")
        return self._page(metadata)

    async def get_children(self, page_id: str, user: UserContext) -> WikiPageTree:
        """Return the direct children of a page."""
        self._require_served_account(user)
        payload = await self._call("get_page_children", parent_id=page_id, limit=MAX_SEARCH_LIMIT)
        document = self._as_object(payload, "get_page_children")
        results = document.get("results")
        if not isinstance(results, list):
            raise WikiToolProtocolError("confluence_get_page_children returned no results")
        return WikiPageTree(
            parent_id=page_id,
            children=tuple(self._reference(item) for item in results),
        )

    async def list_spaces(self, user: UserContext) -> tuple[WikiSpace, ...]:
        """Return the spaces this user may read.

        The server exposes no space-listing tool, so this is a CQL search for
        ``type = space``. Results come back shaped like pages, with the space key
        and name in the ``space`` object, which is what is read here.
        """
        self._require_served_account(user)
        payload = await self._call("search_wiki", query="type = space", limit=MAX_SEARCH_LIMIT)
        spaces = {}
        for item in self._as_list(payload, "list_spaces"):
            space = self._space(item)
            if space is not None:
                spaces[space.key] = space
        return tuple(sorted(spaces.values(), key=lambda space: space.key))

    async def get_comments(self, page_id: str, user: UserContext) -> tuple[WikiComment, ...]:
        """Return the comments attached to a page."""
        self._require_served_account(user)
        payload = await self._call("get_comments", page_id=page_id)
        comments = tuple(self._comment(item, page_id) for item in self._as_list(payload, "get_comments"))
        return tuple(sorted(comments, key=lambda comment: comment.created_at))

    async def get_history(self, page_id: str, user: UserContext) -> WikiPageHistory:
        """Not available on this server.

        ``confluence_get_page_history`` takes a version number and returns that
        one revision; there is no tool enumerating the revisions of a page.
        Synthesising a history from a single revision would be a lie the agent
        would then reason from, so this refuses.

        The binding does not declare ``get_page_history``, so the capability is
        never offered to the model and this is only reachable by a caller
        bypassing it.
        """
        del page_id, user
        raise WikiToolUnavailableError(
            "this wiki server exposes no page-history listing; the capability is not offered"
        )

    async def create_page(
        self,
        space_key: str,
        title: str,
        body: str,
        user: UserContext,
        *,
        parent_id: str | None = None,
    ) -> WikiPage:
        """Create a page and return it as the wiki stored it."""
        self._require_served_account(user)
        payload = await self._call(
            "create_page",
            space_key=space_key,
            title=title,
            content=body,
            parent_id=parent_id,
            content_format="markdown",
            include_content=True,
        )
        return self._written_page(payload, "create_page")

    async def update_page(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        title: str | None = None,
        expected_version: int | None = None,
    ) -> WikiPage:
        """Replace the body of a page and return the new revision.

        Two things this server forces, both worth knowing about.

        ``confluence_update_page`` requires a title, so a caller changing only
        the body would blank the heading. The current title is read first and
        resent unchanged.

        There is **no optimistic concurrency**: the server offers no way to say
        "write only if the page is still at version N". The version is therefore
        compared against the page that was just read, which *narrows* the window
        in which a colleague's edit can be lost without closing it. That is
        better than ignoring ``expected_version`` - it catches the ordinary case,
        where the other edit happened minutes or hours ago - but it is not an
        atomic compare-and-set, and it must not be described as one.
        """
        self._require_served_account(user)
        current = await self.get_page(page_id, user)
        self._require_current_version(current, expected_version)

        payload = await self._call(
            "update_page",
            page_id=page_id,
            title=title if title is not None else current.title.expose(),
            content=body,
            content_format="markdown",
            include_content=True,
        )
        return self._written_page(payload, "update_page")

    async def delete_page(self, page_id: str, user: UserContext) -> None:
        """Delete a page."""
        self._require_served_account(user)
        payload = await self._call("delete_page", page_id=page_id)
        self._as_object(payload, "delete_page")

    async def add_comment(
        self,
        page_id: str,
        body: str,
        user: UserContext,
        *,
        parent_comment_id: str | None = None,
    ) -> WikiComment:
        """Post a comment on a page and return it as stored.

        Replying to a comment is a different tool on this server
        (``confluence_reply_to_comment``). Rather than silently post a top-level
        comment where a reply was asked for - which would detach an answer from
        its question - an unsupported reply is refused.
        """
        self._require_served_account(user)
        if parent_comment_id is not None:
            raise WikiToolUnavailableError("this wiki server posts replies through a separate tool, which is not bound")
        payload = await self._call("add_comment", page_id=page_id, body=body)
        document = self._as_object(payload, "add_comment")
        comment = document.get("comment")
        if not isinstance(comment, Mapping):
            raise WikiToolProtocolError("confluence_add_comment returned no comment")
        return self._comment(comment, page_id)

    def _require_served_account(self, user: UserContext) -> None:
        """Refuse to act for somebody this connection cannot represent.

        This server has two identity modes, and the guard only applies to one.

        Over **HTTP** it reads an ``Authorization`` header on every request and
        builds a client for that person, so the connection genuinely acts on
        their behalf and there is nothing to guard: ``is_per_user`` says so, and
        this returns immediately. The server itself refuses an unauthenticated
        request with a 401 rather than falling back to the operator's
        credentials, unless somebody sets ``ALLOW_GLOBAL_CRED_FALLBACK``.

        Over **stdio** there is no per-request header. The process holds one set
        of credentials and acts as exactly one person, configured once. Serving a
        second user through it would return that first person's view of the wiki
        under somebody else's name - including pages the second user may not
        read - so it is refused here.
        """
        if self._is_per_user:
            return
        if not self._account_id or user.user_id == self._account_id:
            return
        raise WikiAccessDeniedError(
            f"this wiki connection acts for {self._account_id!r} and cannot serve {user.user_id!r}"
        )

    @staticmethod
    def _require_current_version(page: WikiPage, expected_version: int | None) -> None:
        """Refuse a write based on a revision somebody has since replaced."""
        if expected_version is None or expected_version == page.version:
            return
        raise WikiConcurrentEditError(page.page_id, expected_version, page.version)

    def _written_page(self, payload: object, alias: str) -> WikiPage:
        """Read the page out of a create or update answer."""
        document = self._as_object(payload, alias)
        page = document.get("page")
        if not isinstance(page, Mapping):
            raise WikiToolProtocolError(f"{alias} returned no page")
        return self._page(page)

    def _page(self, entry: Mapping[str, Any]) -> WikiPage:
        """Map one page object into the domain."""
        created = self._moment(entry.get("created"))
        updated = self._moment(entry.get("updated")) or created
        content = entry.get("content")
        body, body_format = self._body(content)
        return self._built(
            WikiPage,
            page_id=self._identifier(entry, "id"),
            space_key=self._space_key(entry),
            title=untrusted(str(entry.get("title", "")), WikiOrigin.PAGE_TITLE),
            body=untrusted(body, WikiOrigin.PAGE_BODY),
            body_format=body_format,
            # This server does not serialise the publication status, so a page
            # is reported as current. Saying "archived" would be a guess, and
            # saying nothing is not an option the domain offers.
            status=WikiPageStatus.CURRENT,
            parent_id=self._parent_of(entry),
            created_at=created,
            created_by=None,
            last_modified_at=updated,
            last_modified_by=self._author(entry.get("author")),
            version=self._version_of(entry),
            url=str(entry.get("url") or ""),
        )

    def _reference(self, entry: object) -> WikiPageReference:
        """Map one search hit or child into the domain.

        The server has no excerpt field: a search puts the excerpt in the page's
        ``content``, so that is where it is read from. A child listing has no
        content at all, and the excerpt is simply absent.
        """
        if not isinstance(entry, Mapping):
            raise WikiToolProtocolError("the wiki server returned a page that is not an object")
        created = self._moment(entry.get("created"))
        excerpt, _ = self._body(entry.get("content"))
        return self._built(
            WikiPageReference,
            page_id=self._identifier(entry, "id"),
            space_key=self._space_key(entry),
            title=untrusted(str(entry.get("title", "")), WikiOrigin.PAGE_TITLE),
            excerpt=(None if not excerpt else untrusted(excerpt, WikiOrigin.PAGE_EXCERPT)),
            status=WikiPageStatus.CURRENT,
            last_modified_at=self._moment(entry.get("updated")) or created,
            version=self._version_of(entry),
            url=str(entry.get("url") or ""),
        )

    def _comment(self, entry: object, page_id: str) -> WikiComment:
        """Map one comment into the domain."""
        if not isinstance(entry, Mapping):
            raise WikiToolProtocolError("the wiki server returned a comment that is not an object")
        return self._built(
            WikiComment,
            comment_id=self._identifier(entry, "id"),
            page_id=page_id,
            body=untrusted(str(entry.get("body", "")), WikiOrigin.COMMENT_BODY),
            # Comment bodies come back as rendered view content rather than
            # Markdown, and the server offers no conversion for them.
            body_format=WikiContentFormat.PLAIN_TEXT,
            author=self._author(entry.get("author")),
            created_at=self._moment(entry.get("created")),
            parent_comment_id=self._optional_identifier(entry, "parent_comment_id"),
        )

    def _space(self, entry: object) -> WikiSpace | None:
        """Map a space-typed search hit, skipping anything without a key."""
        if not isinstance(entry, Mapping):
            return None
        space = entry.get("space")
        if not isinstance(space, Mapping):
            return None
        key = str(space.get("key") or "").strip()
        if not key:
            return None
        name = str(space.get("name") or entry.get("title") or key)
        return WikiSpace(key=key, name=untrusted(name, WikiOrigin.SPACE_NAME))

    @staticmethod
    def _author(value: object) -> WikiAuthor | None:
        """Map an author, which this server flattens to a display name.

        There is no stable account identifier in the payload, so the display name
        stands in for one. It is untrusted either way.
        """
        if not isinstance(value, str) or not value.strip():
            return None
        return WikiAuthor(
            account_id=value.strip(),
            display_name=untrusted(value, WikiOrigin.AUTHOR_NAME),
        )

    @staticmethod
    def _body(content: object) -> tuple[str, WikiContentFormat]:
        """Read a body and its format out of a content object."""
        if not isinstance(content, Mapping):
            return "", WikiContentFormat.PLAIN_TEXT
        value = str(content.get("value", ""))
        declared = str(content.get("format", ""))
        if declared == "markdown":
            return value, WikiContentFormat.MARKDOWN
        # "storage" is processed HTML and "view" is a rendered excerpt. Neither
        # is Markdown, and claiming otherwise would have a caller trust headings
        # that are not there.
        return value, WikiContentFormat.PLAIN_TEXT

    @staticmethod
    def _space_key(entry: Mapping[str, Any]) -> str:
        """Read the space key, which is nested inside a space object."""
        space = entry.get("space")
        key = space.get("key") if isinstance(space, Mapping) else None
        text = str(key or "").strip()
        if not text:
            raise WikiToolProtocolError("the wiki server returned a page with no space key")
        return text

    @staticmethod
    def _parent_of(entry: Mapping[str, Any]) -> str | None:
        """Read the parent, which only appears as the last ancestor."""
        ancestors = entry.get("ancestors")
        if not isinstance(ancestors, Sequence) or isinstance(ancestors, str | bytes) or not ancestors:
            return None
        last = ancestors[-1]
        if not isinstance(last, Mapping):
            return None
        identifier = str(last.get("id") or "").strip()
        return identifier or None

    @staticmethod
    def _version_of(entry: Mapping[str, Any]) -> int:
        """Read the version, which this server flattens to an integer."""
        value = entry.get("version")
        if isinstance(value, bool):
            return 1
        if isinstance(value, int) and value >= 1:
            return value
        if isinstance(value, str) and value.isdigit() and int(value) >= 1:
            return int(value)
        # A page always has at least one revision, and the domain refuses zero.
        return 1

    @staticmethod
    def _identifier(entry: Mapping[str, Any], key: str) -> str:
        """Read a mandatory identifier, which may arrive as a number."""
        value = entry.get(key)
        text = "" if value is None else str(value).strip()
        if not text:
            raise WikiToolProtocolError(f"the wiki server returned an object with no {key!r}")
        return text

    @staticmethod
    def _optional_identifier(entry: Mapping[str, Any], key: str) -> str | None:
        """Read an optional identifier."""
        value = entry.get(key)
        text = "" if value is None else str(value).strip()
        return text or None

    @staticmethod
    def _moment(value: object) -> datetime:
        """Parse a timestamp, tolerating the two shapes this server produces.

        ``to_simplified_dict`` reformats timestamps to ``%Y-%m-%d %H:%M:%S %Z``
        in the server's local time zone, so the offset is frequently absent or
        unparseable. A naive value is read as UTC: guessing the server's zone
        would be worse, and the domain refuses naive datetimes outright.
        """
        text = str(value or "").strip()
        if not text:
            return datetime.now(UTC)
        parsed = _parse_iso(text) or _parse_atlassian(text)
        if parsed is None:
            raise WikiToolProtocolError(f"the wiki server returned an unreadable timestamp {text!r}")
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _built[ModelT](model: type[ModelT], **fields: object) -> ModelT:
        """Build a domain model, reporting a payload the domain refuses."""
        try:
            return model(**fields)
        except ValueError as error:
            raise WikiToolProtocolError(f"the wiki server returned an unusable {model.__name__}: {error}") from error

    async def _call(self, alias: str, **arguments: Any) -> object:
        """Invoke a tool and decode the JSON document it returned as text."""
        session = await self._connection.session()
        payload = {key: value for key, value in arguments.items() if value is not None}
        remote_tool = self._binding.remote(alias)
        _logger.info("Calling Atlassian MCP tool '%s' (alias='%s')", remote_tool, alias)
        _logger.debug("Atlassian MCP tool '%s' payload: %s", remote_tool, payload)
        try:
            result = await session.call_tool(remote_tool, payload)
        except Exception as error:
            _logger.exception("Failed to invoke Atlassian MCP tool '%s'", remote_tool)
            raise WikiToolUnavailableError(
                f"wiki tool {alias!r} could not be called: {type(error).__name__}"
            ) from error
        if result.isError:
            error_text = self._text_of(result)
            _logger.warning("Atlassian MCP tool '%s' returned error: %s", remote_tool, error_text)
            raise _translated(error_text, alias)
        decoded = self._decoded(result, alias)
        _logger.debug("Atlassian MCP tool '%s' returned successfully", remote_tool)
        return decoded

    def _decoded(self, result: CallToolResult, alias: str) -> object:
        """Parse the JSON document a tool returned.

        The payload is a JSON *string*, either in a text block or wrapped by
        FastMCP as ``{"result": "<json string>"}``. Both are unwrapped here.
        """
        text = self._structured_text(result) or self._text_of(result)
        if not text:
            raise WikiToolProtocolError(f"wiki tool {alias!r} returned nothing")
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise WikiToolProtocolError(f"wiki tool {alias!r} returned text that is not JSON") from error

    @staticmethod
    def _structured_text(result: CallToolResult) -> str:
        """Return the JSON string FastMCP wrapped, when it wrapped one."""
        structured = result.structuredContent
        if not isinstance(structured, Mapping):
            return ""
        value = structured.get("result")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _text_of(result: CallToolResult) -> str:
        """Return the text a tool reported."""
        return " ".join(item.text for item in result.content if isinstance(item, TextContent)).strip()

    @staticmethod
    def _as_object(payload: object, alias: str) -> Mapping[str, Any]:
        """Read a JSON object, refusing an error this server reports as success.

        Several tools catch their own failures and return ``{"error": ...}`` or
        ``{"success": false}`` as a normal result. A client checking only
        ``isError`` would read those as successes and report to the user that a
        page had been deleted when it had not.
        """
        if not isinstance(payload, Mapping):
            raise WikiToolProtocolError(f"wiki tool {alias!r} did not return an object")
        reported = payload.get("error")
        if isinstance(reported, str) and reported.strip():
            raise _translated(reported, alias)
        if payload.get("success") is False:
            raise _translated(str(payload.get("message") or "the operation failed"), alias)
        return payload

    @staticmethod
    def _as_list(payload: object, alias: str) -> list[Any]:
        """Read a JSON array, refusing an error object returned in its place."""
        if isinstance(payload, list):
            return payload
        if isinstance(payload, Mapping):
            reported = payload.get("error")
            if isinstance(reported, str) and reported.strip():
                raise _translated(reported, alias)
        raise WikiToolProtocolError(f"wiki tool {alias!r} did not return a list")


class CqlQueryBuilder:
    """Renders a structured search request as CQL.

    Every literal is escaped. A search term is user input on its way into a query
    language, and a term carrying a quote would otherwise close the string and
    have the rest of it read as CQL - the same shape of defect as SQL injection,
    with a wiki's contents behind it.
    """

    def build(self, request: WikiSearchRequest) -> str:
        """Return the CQL expression matching a request."""
        clauses = [
            *self._type_clause(request),
            *self._space_clause(request),
            *self._label_clauses(request),
            *self._title_clause(request),
            *self._text_clause(request),
            *self._window_clauses(request),
        ]
        expression = " AND ".join(clauses) if clauses else "type = page"
        return f"{expression} {self._ordering(request)}"

    @staticmethod
    def _type_clause(request: WikiSearchRequest) -> list[str]:
        """Restrict to pages unless the caller asked for other states."""
        del request
        return ["type = page"]

    def _space_clause(self, request: WikiSearchRequest) -> list[str]:
        """Restrict to the requested spaces."""
        if not request.space_keys:
            return []
        keys = ", ".join(self._quoted(key) for key in request.space_keys)
        return [f"space in ({keys})"]

    def _label_clauses(self, request: WikiSearchRequest) -> list[str]:
        """Require every requested label, as separate clauses."""
        return [f"label = {self._quoted(label)}" for label in request.labels]

    def _title_clause(self, request: WikiSearchRequest) -> list[str]:
        """Match a fragment of the title."""
        fragment = request.title_contains.strip()
        return [f"title ~ {self._quoted(fragment)}"] if fragment else []

    def _text_clause(self, request: WikiSearchRequest) -> list[str]:
        """Match the free-text terms."""
        text = request.text.strip()
        return [f"text ~ {self._quoted(text)}"] if text else []

    def _window_clauses(self, request: WikiSearchRequest) -> list[str]:
        """Restrict to a modification window, in the format CQL accepts."""
        clauses = []
        if request.modified_after is not None:
            clauses.append(f"lastmodified >= {self._quoted(self._day(request.modified_after))}")
        if request.modified_before is not None:
            clauses.append(f"lastmodified <= {self._quoted(self._day(request.modified_before))}")
        return clauses

    @staticmethod
    def _ordering(request: WikiSearchRequest) -> str:
        """Render the requested ordering.

        Relevance is CQL's own default, so it is expressed by asking for no
        ordering at all rather than by naming a field.
        """
        if request.sort_order is WikiSortOrder.TITLE:
            return "order by title asc"
        if request.sort_order is WikiSortOrder.CREATED:
            return "order by created desc"
        if request.sort_order is WikiSortOrder.LAST_MODIFIED:
            return "order by lastmodified desc"
        return ""

    @staticmethod
    def _day(moment: datetime) -> str:
        """Render a date the way CQL expects it."""
        return moment.astimezone(UTC).strftime("%Y-%m-%d")

    @staticmethod
    def _quoted(value: str) -> str:
        """Render a literal, escaping what would otherwise end the string."""
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'


def _parse_iso(text: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, if that is what this is."""
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _parse_atlassian(text: str) -> datetime | None:
    """Parse the reformatted timestamp, with or without a trailing zone name."""
    for candidate in (text, text.rsplit(" ", 1)[0]):
        try:
            return datetime.strptime(candidate, _ATLASSIAN_TIMESTAMP)
        except ValueError:
            continue
    return None


def _translated(reported: str, alias: str) -> WikiToolError:
    """Turn a reported failure into the domain failure it describes.

    This server has no error codes: a refusal and a missing page arrive as
    English prose. Reading the prose is unreliable by nature, so anything
    unrecognised stays a protocol failure rather than being guessed into
    something more specific.
    """
    lowered = reported.casefold()
    if any(marker in lowered for marker in _DENIED_MARKERS):
        return WikiAccessDeniedError(message=reported)
    if any(marker in lowered for marker in _MISSING_MARKERS):
        return WikiNotFoundError(message=reported)
    return WikiToolProtocolError(f"wiki tool {alias!r} failed: {reported}")
