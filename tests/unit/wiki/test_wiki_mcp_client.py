"""Tests of the wiki MCP client layer.

The native client is exercised against the **real reference server**, over a real
stdio transport and a real protocol handshake. A test that mocked the session
would prove the client can talk to a mock.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.core.config.directory import ConfigurationDirectory
from ai_agent_lab.core.security.untrusted import UntrustedText
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.domain.models import WikiSearchRequest
from ai_agent_lab.wiki.mcp.binding import (
    McpBindingError,
    McpServerBinding,
    McpServerBindingLoader,
    McpTransport,
)
from ai_agent_lab.wiki.mcp.connection import McpConnection
from ai_agent_lab.wiki.mcp.dialects import DialectContext, WikiDialectRegistry
from ai_agent_lab.wiki.mcp.native.client import McpWikiTools
from ai_agent_lab.wiki.tools_port import WikiTools
from ai_agent_lab.wiki.wiki_errors import (
    WikiAccessDeniedError,
    WikiNotFoundError,
    WikiToolUnavailableError,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

ALL_TOOLS = {name.value: name.value for name in WikiToolName}


@pytest.fixture
def configuration() -> ConfigurationDirectory:
    """The delivered configuration of the repository."""
    return ConfigurationDirectory(REPOSITORY_ROOT / "config")


@pytest.fixture
async def native_tools() -> AsyncIterator[McpWikiTools]:
    """A client bound to the reference server, over a real stdio transport."""
    binding = McpServerBindingLoader(ConfigurationDirectory(REPOSITORY_ROOT / "config")).load("wiki-local")
    connection = McpConnection(binding)
    try:
        yield McpWikiTools(connection, binding)
    finally:
        await connection.aclose()


class TestBindingLoading:
    """What a delivered binding must say before it is usable."""

    def test_the_delivered_local_binding_loads(self, configuration: ConfigurationDirectory):
        binding = McpServerBindingLoader(configuration).load("wiki-local")

        assert binding.server == "wiki-local"
        assert binding.dialect == "native"
        assert binding.transport is McpTransport.STDIO
        assert binding.supports(WikiToolName.SEARCH_WIKI)

    def test_a_capability_with_no_tool_behind_it_is_refused(self, tmp_path: Path):
        """It would be advertised to the model and fail on the first call."""
        (tmp_path / "mcp").mkdir()
        (tmp_path / "mcp" / "broken.yaml").write_text(
            "server: broken\n"
            "transport: stdio\n"
            "command: python\n"
            "capabilities: [search_wiki, update_page]\n"
            "tools:\n"
            "  search_wiki: search_wiki\n",
            encoding="utf-8",
        )

        with pytest.raises(McpBindingError, match="names no tool"):
            McpServerBindingLoader(ConfigurationDirectory(tmp_path)).load("broken")

    def test_an_unknown_capability_is_refused(self, tmp_path: Path):
        (tmp_path / "mcp").mkdir()
        (tmp_path / "mcp" / "broken.yaml").write_text(
            "server: broken\ntransport: stdio\ncommand: python\n"
            "capabilities: [teleport_page]\ntools: {teleport_page: x}\n",
            encoding="utf-8",
        )

        with pytest.raises(McpBindingError, match="unknown capabilities"):
            McpServerBindingLoader(ConfigurationDirectory(tmp_path)).load("broken")

    def test_an_http_binding_without_a_url_is_refused(self, tmp_path: Path):
        (tmp_path / "mcp").mkdir()
        (tmp_path / "mcp" / "broken.yaml").write_text(
            "server: broken\ntransport: http\ncapabilities: [get_page]\ntools: {get_page: get_page}\n",
            encoding="utf-8",
        )

        with pytest.raises(McpBindingError, match="requires 'url'"):
            McpServerBindingLoader(ConfigurationDirectory(tmp_path)).load("broken")

    def test_a_capability_the_binding_omits_is_never_offered(self):
        """A server that simply cannot write says so by declaring nothing."""
        binding = McpServerBinding(
            server="read-only",
            transport=McpTransport.STDIO,
            capabilities=(WikiToolName.SEARCH_WIKI, WikiToolName.GET_PAGE),
            tools=ALL_TOOLS,
            command="python",
        )

        assert binding.supports(WikiToolName.SEARCH_WIKI)
        assert not binding.supports(WikiToolName.UPDATE_PAGE)
        assert not binding.supports(WikiToolName.DELETE_PAGE)


class TestReadOnlyDeployments:
    """A server told to refuse writes must not have writes offered for it.

    `sooperset/mcp-atlassian` started with `READ_ONLY_MODE=true` exposes nine
    tools and not one of them writes. A binding that declared the writes anyway
    would have the agent propose an edit, ask the user to approve it, and only
    then discover the tool does not exist.
    """

    def build(self, *, read_only_variable: str = "WIKI_MCP_READ_ONLY") -> McpServerBinding:
        """A binding declaring reads and writes alike."""
        return McpServerBinding(
            server="atlassian-like",
            transport=McpTransport.STDIO,
            capabilities=(
                WikiToolName.SEARCH_WIKI,
                WikiToolName.GET_PAGE,
                WikiToolName.CREATE_PAGE,
                WikiToolName.UPDATE_PAGE,
                WikiToolName.ADD_COMMENT,
                WikiToolName.DELETE_PAGE,
            ),
            tools=ALL_TOOLS,
            command="python",
            read_only_variable=read_only_variable,
        )

    @pytest.mark.security
    def test_writes_are_withdrawn_when_the_server_is_read_only(self):
        served = self.build().capabilities_in({"WIKI_MCP_READ_ONLY": "true"})

        assert WikiToolName.SEARCH_WIKI in served
        assert WikiToolName.GET_PAGE in served
        for write in (
            WikiToolName.CREATE_PAGE,
            WikiToolName.UPDATE_PAGE,
            WikiToolName.ADD_COMMENT,
            WikiToolName.DELETE_PAGE,
        ):
            assert write not in served

    def test_writes_are_served_when_the_server_accepts_them(self):
        served = self.build().capabilities_in({"WIKI_MCP_READ_ONLY": "false"})

        assert WikiToolName.UPDATE_PAGE in served
        assert WikiToolName.DELETE_PAGE in served

    @pytest.mark.security
    def test_an_absent_variable_is_read_as_read_only(self):
        """The safe reading, since the delivered default is read-only."""
        assert WikiToolName.UPDATE_PAGE not in self.build().capabilities_in({})

    @pytest.mark.security
    def test_an_unrecognised_value_is_read_as_read_only(self):
        """A misspelled value gets the safe answer, not an unintended write."""
        assert WikiToolName.UPDATE_PAGE not in self.build().capabilities_in(
            {"WIKI_MCP_READ_ONLY": "tru"}
        )

    def test_yes_and_on_are_accepted(self):
        for value in ("yes", "ON", "1", "True"):
            assert WikiToolName.UPDATE_PAGE not in self.build().capabilities_in(
                {"WIKI_MCP_READ_ONLY": value}
            )

    def test_the_ways_of_saying_writable_are_accepted(self):
        for value in ("false", "FALSE", "0", "no", "off"):
            assert WikiToolName.UPDATE_PAGE in self.build().capabilities_in(
                {"WIKI_MCP_READ_ONLY": value}
            )

    def test_a_binding_naming_no_variable_is_unaffected(self):
        """The reference server has no read-only mode to speak of."""
        served = self.build(read_only_variable="").capabilities_in({"WIKI_MCP_READ_ONLY": "true"})

        assert WikiToolName.UPDATE_PAGE in served

    def test_the_delivered_atlassian_binding_names_the_variable(
        self, configuration: ConfigurationDirectory
    ):
        """Otherwise the safeguard is code nothing reaches."""
        for name in ("mcp-atlassian", "mcp-atlassian-http"):
            binding = McpServerBindingLoader(configuration).load(name)
            assert binding.read_only_variable == "WIKI_MCP_READ_ONLY", name


class TestEnvironmentResolution:
    """A binding names credentials; it never carries them."""

    @pytest.mark.security
    def test_a_missing_credential_is_refused_before_the_server_starts(self):
        """An authentication failure several calls later is far harder to read."""
        binding = McpServerBinding(
            server="needs-token",
            transport=McpTransport.STDIO,
            capabilities=(WikiToolName.GET_PAGE,),
            tools=ALL_TOOLS,
            command="python",
            env={"CONFLUENCE_API_TOKEN": "CONFLUENCE_API_TOKEN"},
        )
        connection = McpConnection(binding, environment={})

        with pytest.raises(WikiToolUnavailableError, match="CONFLUENCE_API_TOKEN"):
            connection._stdio_parameters()

    @pytest.mark.security
    def test_a_declared_credential_reaches_the_server_process_only(self):
        binding = McpServerBinding(
            server="needs-token",
            transport=McpTransport.STDIO,
            capabilities=(WikiToolName.GET_PAGE,),
            tools=ALL_TOOLS,
            command="python",
            env={"CONFLUENCE_API_TOKEN": "SOURCE_VARIABLE"},
        )
        connection = McpConnection(binding, environment={"SOURCE_VARIABLE": "s3cret"})

        parameters = connection._stdio_parameters()

        assert parameters.env == {"CONFLUENCE_API_TOKEN": "s3cret"}
        assert "s3cret" not in repr(binding.env)


class TestDialectRegistry:
    """Which servers this build can reach."""

    def test_the_known_dialects_are_named(self):
        assert WikiDialectRegistry().known == ("atlassian", "native")

    def test_an_unimplemented_dialect_names_the_alternatives(self):
        """A typo in a binding must not fail deep inside a session."""
        binding = McpServerBinding(
            server="exotic",
            transport=McpTransport.STDIO,
            capabilities=(WikiToolName.GET_PAGE,),
            tools=ALL_TOOLS,
            dialect="notion",
            command="python",
        )

        with pytest.raises(WikiToolUnavailableError, match="Known dialects"):
            WikiDialectRegistry().build(McpConnection(binding), binding)

    def test_a_dialect_is_never_silently_replaced(self):
        registry = WikiDialectRegistry()

        with pytest.raises(WikiToolUnavailableError, match="already registered"):
            registry.register("native", lambda connection, binding, context: None)  # type: ignore[arg-type,return-value]

    @pytest.mark.security
    def test_the_atlassian_dialect_is_told_which_account_it_serves(self):
        """It takes no account argument, so it must know who it acts for."""
        binding = McpServerBinding(
            server="mcp-atlassian",
            transport=McpTransport.STDIO,
            capabilities=(WikiToolName.GET_PAGE,),
            tools=ALL_TOOLS,
            dialect="atlassian",
            command="docker",
        )

        tools = WikiDialectRegistry().build(McpConnection(binding), binding, DialectContext(account_id="diana"))

        assert tools._account_id == "diana"
        assert not tools._is_per_user

    @pytest.mark.security
    def test_a_per_user_connection_is_declared_as_one(self):
        """Over HTTP the server reads an Authorization header on every request."""
        binding = McpServerBinding(
            server="mcp-atlassian",
            transport=McpTransport.HTTP,
            capabilities=(WikiToolName.GET_PAGE,),
            tools=ALL_TOOLS,
            dialect="atlassian",
            url="https://wiki-mcp.internal/mcp",
        )

        tools = WikiDialectRegistry().build(McpConnection(binding), binding, DialectContext(is_per_user=True))

        assert tools._is_per_user


class TestNativeClientOverRealTransport:
    """The native client against the reference server, end to end."""

    def test_it_satisfies_the_whole_tool_surface(self, native_tools: McpWikiTools):
        assert isinstance(native_tools, WikiTools)

    async def test_a_search_crosses_the_protocol(self, native_tools: McpWikiTools):
        reader = UserContext(user_id="alice", session_id="s")

        result = await native_tools.search(WikiSearchRequest(text="VAT"), reader)

        assert [reference.page_id for reference in result.references] == ["apollo-scope"]

    async def test_a_page_comes_back_as_a_domain_model(self, native_tools: McpWikiTools):
        reader = UserContext(user_id="alice", session_id="s")

        page = await native_tools.get_page("apollo-architecture", reader)

        assert page.version == 2
        assert "PostgreSQL 16" in page.body.expose()

    @pytest.mark.security
    async def test_third_party_text_arrives_fenced(self, native_tools: McpWikiTools):
        """Nothing crosses the boundary as a bare string."""
        reader = UserContext(user_id="alice", session_id="s")

        page = await native_tools.get_page("apollo-onboarding", reader)

        assert isinstance(page.title, UntrustedText)
        assert isinstance(page.body, UntrustedText)
        assert "Ignore all previous instructions" in page.body.expose()
        assert "Ignore all previous instructions" not in repr(page)

    async def test_history_is_ordered_newest_first(self, native_tools: McpWikiTools):
        reader = UserContext(user_id="alice", session_id="s")

        history = await native_tools.get_history("apollo-scope", reader)

        assert [version.version for version in history.versions] == [4, 3, 2, 1]

    async def test_an_unknown_page_is_decoded_as_missing(self, native_tools: McpWikiTools):
        reader = UserContext(user_id="alice", session_id="s")

        with pytest.raises(WikiNotFoundError):
            await native_tools.get_page("no-such-page", reader)

    @pytest.mark.security
    async def test_a_refusal_is_decoded_as_a_refusal_not_as_absence(self, native_tools: McpWikiTools):
        """Collapsing the two would report restricted documentation as missing."""
        reader = UserContext(user_id="alice", session_id="s")

        with pytest.raises(WikiAccessDeniedError):
            await native_tools.get_page("apollo-salaries", reader)

    @pytest.mark.security
    async def test_the_calling_identity_reaches_the_server(self, native_tools: McpWikiTools):
        """The server scopes results per account; the client must carry who asks."""
        reader = UserContext(user_id="alice", session_id="s")
        owner = UserContext(user_id="diana", session_id="s")

        hidden = await native_tools.search(WikiSearchRequest(text="over budget"), reader)
        visible = await native_tools.search(WikiSearchRequest(text="over budget"), owner)

        assert not hidden.references
        assert [reference.page_id for reference in visible.references] == ["board-budget"]

    @pytest.mark.security
    async def test_spaces_are_scoped_to_the_caller(self, native_tools: McpWikiTools):
        reader = UserContext(user_id="alice", session_id="s")
        owner = UserContext(user_id="diana", session_id="s")

        assert "BOARD" not in {space.key for space in await native_tools.list_spaces(reader)}
        assert "BOARD" in {space.key for space in await native_tools.list_spaces(owner)}
