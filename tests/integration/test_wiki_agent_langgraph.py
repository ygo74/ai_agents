"""Integration tests of the Wiki Agent on LangGraph.

The agent, the tools, the human-in-the-loop middleware, the skills and the
in-memory wiki are all the real ones. Only the model is scripted, so a scenario
proves something about the wiring rather than about a sentence a model produced.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tests.support.langgraph_fakes import (
    ScriptedChatModel,
    ScriptedStructuredModel,
    ScriptedTurn,
    ToolCall,
    calls,
    says,
)
from ygo74.agent_runtime.domains.auth.agent_principal import AgentPrincipal
from ygo74.agent_runtime.domains.security.audit import AuditOutcome

from ai_agent_lab.langgraph.approval import LangGraphApprovalTranslator
from ai_agent_lab.wiki.application.composition import (
    WikiAgentCompositionRoot,
    WikiAgentRuntime,
    thread_id_of,
)
from ai_agent_lab.wiki.application.console import ConsoleApprovalResolver
from ai_agent_lab.wiki.application.session import WikiAgentSession
from ai_agent_lab.wiki.capabilities.read_capabilities import ANSWER_FROM_WIKI, SUMMARISE_PAGE
from ai_agent_lab.wiki.capabilities.write_capabilities import DRAFT_PAGE_CONTENT
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.config.settings import WikiAgentMode, WikiAgentSettings
from ai_agent_lab.wiki.skills.analysis import AnswerOutput, PageDraftOutput

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ScriptedReasoner:
    """Returns a prepared analysis without reaching a model.

    Keyed by the requested output type, so one runtime can serve both an
    analysis capability and the drafting capability in the same scenario.
    """

    def __init__(self, output: object, **by_type: object) -> None:
        self._output = output
        self._by_type = dict(by_type)

    async def reason(self, request: object, response_model: type) -> object:
        """Return the prepared output for the requested shape."""
        del request
        return self._by_type.get(response_model.__name__, self._output)


def build_runtime(
    script: list[ScriptedTurn] | None = None,
    *,
    reasoner: object | None = None,
    settings: WikiAgentSettings | None = None,
    principal: AgentPrincipal | None = None,
    session_id: str = "integration",
) -> WikiAgentRuntime:
    """Assemble the Wiki Agent with a scripted model and the sample dataset."""
    return WikiAgentCompositionRoot(
        settings or WikiAgentSettings(mode=WikiAgentMode.MOCK),
        ScriptedChatModel(script or [says("nothing to do")]),
        principal=principal or AgentPrincipal(subject="diana"),
        reasoner=reasoner or ScriptedReasoner(AnswerOutput(answer="scripted", cited_page_ids=[])),
        base_path=REPOSITORY_ROOT,
    ).build(session_id=session_id)


class TestComposition:
    """What the composition root assembles."""

    def test_the_delivered_capabilities_are_registered(self):
        runtime = build_runtime()

        names = [descriptor.tool_name for descriptor in runtime.registry.skills]

        assert names[0] == ANSWER_FROM_WIKI
        assert WikiToolName.SEARCH_WIKI.value in names
        assert SUMMARISE_PAGE in names

    def test_the_agent_carries_the_delivered_instructions(self):
        runtime = build_runtime()

        assert "You assist a member of a project team" in runtime.manifest.instructions

    def test_the_write_capabilities_are_delivered_and_gated(self):
        """Phase two delivers the four writes, and every one of them is gated."""
        runtime = build_runtime()

        gated = {descriptor.tool_name for descriptor in runtime.registry.write_skills()}

        assert gated == {
            WikiToolName.CREATE_PAGE.value,
            WikiToolName.UPDATE_PAGE.value,
            WikiToolName.ADD_COMMENT.value,
            WikiToolName.DELETE_PAGE.value,
        }

    def test_drafting_changes_nothing(self):
        """Composing a page is a read: it is the publishing that is a write."""
        runtime = build_runtime()

        names = [descriptor.tool_name for descriptor in runtime.registry.write_skills()]

        assert DRAFT_PAGE_CONTENT not in names
        assert DRAFT_PAGE_CONTENT in [d.tool_name for d in runtime.registry.skills]

    @pytest.mark.security
    def test_every_write_is_interrupted_by_the_middleware(self):
        """The interrupt table is built from the policy, never from the model."""
        runtime = build_runtime()

        table = runtime.approvals.interrupt_on(runtime.registry, runtime.policy, runtime.user)

        for name in (
            WikiToolName.CREATE_PAGE.value,
            WikiToolName.UPDATE_PAGE.value,
            WikiToolName.ADD_COMMENT.value,
            WikiToolName.DELETE_PAGE.value,
        ):
            assert table[name] is not False, f"{name} would run without asking"
        assert table[WikiToolName.SEARCH_WIKI.value] is False
        assert table[DRAFT_PAGE_CONTENT] is False


class TestCapabilityExposure:
    """A capability no server can serve is never offered."""

    def test_a_binding_that_omits_a_capability_withdraws_it(self, tmp_path: Path, monkeypatch):
        """`sooperset/mcp-atlassian` cannot list revisions, and says so."""
        self._deliver_binding(tmp_path, capabilities=["search_wiki", "get_page"])
        monkeypatch.setenv("AI_AGENT_LAB_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("WIKI_MCP_SERVER", "partial")

        runtime = build_runtime(settings=WikiAgentSettings(mode=WikiAgentMode.MCP))

        names = {descriptor.tool_name for descriptor in runtime.registry.skills}
        assert WikiToolName.GET_PAGE_HISTORY.value not in names
        assert WikiToolName.SEARCH_WIKI.value in names

    def test_an_analysis_capability_needs_the_tools_it_retrieves_with(self, tmp_path: Path, monkeypatch):
        """Summarising is useless against a server that cannot return a page."""
        self._deliver_binding(tmp_path, capabilities=["search_wiki"])
        monkeypatch.setenv("AI_AGENT_LAB_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("WIKI_MCP_SERVER", "partial")

        runtime = build_runtime(settings=WikiAgentSettings(mode=WikiAgentMode.MCP))

        names = {descriptor.tool_name for descriptor in runtime.registry.skills}
        assert SUMMARISE_PAGE not in names
        assert ANSWER_FROM_WIKI not in names

    @pytest.mark.security
    def test_a_read_only_server_is_offered_no_write_capability(
        self, tmp_path: Path, monkeypatch
    ):
        """The failure this guards against was reported from a real session.

        `sooperset/mcp-atlassian` started with `READ_ONLY_MODE=true` exposes no
        write tool. With the writes declared in the binding and nothing tying the
        two together, the agent drafted a revision, asked the user to approve it,
        and only then discovered `confluence_update_page` did not exist.
        """
        self._deliver_binding(
            tmp_path,
            capabilities=["search_wiki", "get_page", "update_page", "delete_page"],
            read_only_variable="WIKI_MCP_READ_ONLY",
        )
        monkeypatch.setenv("AI_AGENT_LAB_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("WIKI_MCP_SERVER", "partial")
        monkeypatch.setenv("WIKI_MCP_READ_ONLY", "true")

        runtime = build_runtime(settings=WikiAgentSettings(mode=WikiAgentMode.MCP))

        names = {descriptor.tool_name for descriptor in runtime.registry.skills}
        assert runtime.registry.write_skills() == ()
        assert WikiToolName.GET_PAGE.value in names
        assert DRAFT_PAGE_CONTENT in names

    def test_a_writable_server_is_offered_the_write_capabilities(
        self, tmp_path: Path, monkeypatch
    ):
        self._deliver_binding(
            tmp_path,
            capabilities=["search_wiki", "get_page", "update_page", "delete_page"],
            read_only_variable="WIKI_MCP_READ_ONLY",
        )
        monkeypatch.setenv("AI_AGENT_LAB_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("WIKI_MCP_SERVER", "partial")
        monkeypatch.setenv("WIKI_MCP_READ_ONLY", "false")

        runtime = build_runtime(settings=WikiAgentSettings(mode=WikiAgentMode.MCP))

        offered = {descriptor.tool_name for descriptor in runtime.registry.write_skills()}
        assert offered == {WikiToolName.UPDATE_PAGE.value, WikiToolName.DELETE_PAGE.value}

    @staticmethod
    def _deliver_binding(
        root: Path,
        *,
        capabilities: list[str],
        read_only_variable: str = "",
    ) -> None:
        """Deliver a configuration directory with one partial binding."""
        source = REPOSITORY_ROOT / "config"
        for folder in ("agents", "skills"):
            _copy_tree(source / folder, root / folder)
        (root / "mcp").mkdir(parents=True, exist_ok=True)
        tools = "\n".join(f"  {name}: {name}" for name in capabilities)
        switch = f"read_only_variable: {read_only_variable}\n" if read_only_variable else ""
        (root / "mcp" / "partial.yaml").write_text(
            "server: partial\ntransport: stdio\ncommand: python\ndialect: native\n"
            f"{switch}"
            f"capabilities:\n{chr(10).join(f'  - {name}' for name in capabilities)}\n"
            f"tools:\n{tools}\n",
            encoding="utf-8",
        )


def _copy_tree(source: Path, target: Path) -> None:
    """Copy a delivered configuration folder."""
    import shutil

    shutil.copytree(source, target, dirs_exist_ok=True)


@pytest.mark.security
class TestThreadIsolation:
    """LangGraph keys persisted state by thread identifier."""

    def test_the_same_conversation_of_two_people_is_two_threads(self):
        """A caller-supplied identifier must not reach another person's state."""
        mine = thread_id_of(AgentPrincipal(subject="diana"), "conversation-1")
        theirs = thread_id_of(AgentPrincipal(subject="alice"), "conversation-1")

        assert mine != theirs

    def test_the_identifier_is_stable_for_one_person(self):
        first = thread_id_of(AgentPrincipal(subject="diana"), "conversation-1")
        second = thread_id_of(AgentPrincipal(subject="diana"), "conversation-1")

        assert first == second

    def test_a_subject_cannot_be_shaped_to_collide_with_another(self):
        """A delimiter inside a subject is the classic composite-key ambiguity."""
        crafted = thread_id_of(AgentPrincipal(subject="diana:conversation"), "1")
        genuine = thread_id_of(AgentPrincipal(subject="diana"), "conversation:1")

        assert crafted != genuine

    def test_the_runtime_uses_the_derived_identifier(self):
        runtime = build_runtime(session_id="conversation-1")

        assert runtime.thread_id == thread_id_of(AgentPrincipal(subject="diana"), "conversation-1")

    def test_the_conversation_identifier_never_appears_in_the_thread(self):
        """It is opaque, so nothing can be guessed back out of it."""
        runtime = build_runtime(session_id="conversation-1")

        assert "conversation-1" not in runtime.thread_id
        assert "diana" not in runtime.thread_id


class TestAgentLoop:
    """The real LangGraph loop, over the real tools."""

    async def test_a_read_capability_runs_and_reaches_the_model(self):
        runtime = build_runtime(
            [
                calls(ToolCall("get_page", {"page_id": "apollo-architecture"})),
                says("The architecture page describes a Python service."),
            ]
        )

        result = await runtime.agent.ainvoke(
            {"messages": [{"role": "user", "content": "read the architecture page"}]},
            config={"configurable": {"thread_id": runtime.thread_id}},
        )

        text = str(result["messages"][-1].content)
        assert "Python service" in text

    @pytest.mark.security
    async def test_page_content_reaches_the_model_fenced(self):
        """A planted instruction must arrive as delimited data."""
        runtime = build_runtime(
            [
                calls(ToolCall("get_page", {"page_id": "apollo-onboarding"})),
                says("done"),
            ]
        )

        await runtime.agent.ainvoke(
            {"messages": [{"role": "user", "content": "read the onboarding page"}]},
            config={"configurable": {"thread_id": runtime.thread_id}},
        )

        tool_output = _tool_messages(runtime)
        assert "Ignore all previous instructions" in tool_output
        assert "not trusted" in tool_output
        assert "UNTRUSTED_" in tool_output

    @pytest.mark.security
    async def test_a_refused_page_is_reported_not_swallowed(self):
        """The model must be able to tell the user, rather than assume success."""
        runtime = build_runtime(
            [
                calls(ToolCall("get_page", {"page_id": "apollo-salaries"})),
                says("done"),
            ],
            principal=AgentPrincipal(subject="alice"),
        )

        await runtime.agent.ainvoke(
            {"messages": [{"role": "user", "content": "read the compensation page"}]},
            config={"configurable": {"thread_id": runtime.thread_id}},
        )

        tool_output = _tool_messages(runtime)
        assert "did not run" in tool_output
        assert "WikiAccessDeniedError" in tool_output

    async def test_an_ungrounded_answer_is_flagged_to_the_model(self):
        """The warning has to come before the text it applies to."""
        runtime = build_runtime(
            [
                calls(ToolCall("answer_from_wiki", {"question": "What is the VAT scope?"})),
                says("done"),
            ],
            reasoner=ScriptedReasoner(AnswerOutput(answer="Confidently wrong.", cited_page_ids=[])),
        )

        await runtime.agent.ainvoke(
            {"messages": [{"role": "user", "content": "what is the VAT scope?"}]},
            config={"configurable": {"thread_id": runtime.thread_id}},
        )

        tool_output = _tool_messages(runtime)
        assert "NOT grounded" in tool_output
        assert tool_output.index("NOT grounded") < tool_output.index("Confidently wrong.")


def _tool_messages(runtime) -> str:
    """Return every tool result the model was shown."""
    state = runtime.agent.get_state({"configurable": {"thread_id": runtime.thread_id}})
    return "\n".join(
        str(message.content) for message in state.values["messages"] if message.__class__.__name__ == "ToolMessage"
    )


class RecordingConsole:
    """A console that answers every prompt the same way and keeps what it read."""

    def __init__(self, *, answer: str) -> None:
        self._answer = answer
        self.lines: list[str] = []

    def write(self, text: str = "") -> None:
        """Keep the line instead of printing it."""
        self.lines.append(text)

    def prompt(self, label: str) -> str:
        """Answer the confirmation the same way every time."""
        del label
        return self._answer

    def is_exit(self, message: str) -> bool:
        """Never leave: the session loop is driven by the test."""
        del message
        return False

    @property
    def transcript(self) -> str:
        """Everything the person at the console was shown."""
        return "\n".join(self.lines)


def build_session(runtime: WikiAgentRuntime, console: RecordingConsole) -> WikiAgentSession:
    """Drive a runtime through the real console approval path.

    The resolver, the presenter and the ledger are the production ones. Only the
    terminal is replaced, so the scenario exercises the bridge between a
    LangGraph interrupt and the domain confirmation rather than a stand-in for
    it.
    """
    return WikiAgentSession(
        runtime,
        ConsoleApprovalResolver(console, runtime.presenter, runtime.confirmation_ledger, runtime.user),
        LangGraphApprovalTranslator(),
    )


def build_write_runtime(
    script: list[ScriptedTurn],
    *,
    body: str = "A revised body.",
    principal: AgentPrincipal | None = None,
) -> tuple[WikiAgentRuntime, ScriptedChatModel]:
    """Assemble a runtime whose reasoner drafts a fixed page body.

    The model is returned as well, because a publishing turn has to name the
    draft reference the drafting turn produced, and that reference does not
    exist until the first turn has run.
    """
    model = ScriptedChatModel(script)
    runtime = WikiAgentCompositionRoot(
        WikiAgentSettings(mode=WikiAgentMode.MOCK),
        model,
        principal=principal or AgentPrincipal(subject="diana"),
        reasoner=ScriptedReasoner(
            AnswerOutput(answer="scripted", cited_page_ids=[]),
            PageDraftOutput=PageDraftOutput(title="Architecture overview", body=body),
        ),
        base_path=REPOSITORY_ROOT,
    ).build(session_id="write")
    return runtime, model


def draft_reference_of(runtime: WikiAgentRuntime) -> str:
    """Read the draft reference the drafting capability handed the model."""
    found = re.search(r'"draft_reference":\s*"([^"]+)"', _tool_messages(runtime))
    assert found is not None, "the drafting capability returned no reference"
    return found.group(1)


def revision_script(instruction: str) -> list[ScriptedTurn]:
    """Script a first turn that drafts a revision of the architecture page."""
    return [
        calls(ToolCall(DRAFT_PAGE_CONTENT, {"page_id": "apollo-architecture", "instruction": instruction})),
        says("Here is the draft."),
    ]


async def publish(
    runtime: WikiAgentRuntime,
    model: ScriptedChatModel,
    console: RecordingConsole,
    *,
    tool: str = WikiToolName.UPDATE_PAGE.value,
) -> str:
    """Run the drafting turn, then ask for the draft to be published."""
    session = build_session(runtime, console)
    await session.ask("draft a revision of the architecture page")
    reference = draft_reference_of(runtime)
    model.script.extend(
        [calls(ToolCall(tool, {"draft_reference": reference})), says("The architecture page is updated.")]
    )
    return await session.ask("publish it")


class TestWriteApproval:
    """The whole write path: draft, suspend, answer, enforce."""

    async def test_an_approved_update_reaches_the_wiki(self):
        runtime, model = build_write_runtime(revision_script("mention the new queue"))
        console = RecordingConsole(answer="y")

        answer = await publish(runtime, model, console)

        assert "updated" in answer
        page = await runtime.wiki_tools.get_page("apollo-architecture", runtime.user)
        assert page.body.expose() == "A revised body."
        assert page.version == 3

    @pytest.mark.security
    async def test_a_declined_update_changes_nothing(self):
        runtime, model = build_write_runtime(revision_script("rewrite it"))
        console = RecordingConsole(answer="n")

        await publish(runtime, model, console)

        page = await runtime.wiki_tools.get_page("apollo-architecture", runtime.user)
        assert page.version == 2
        assert "A revised body." not in page.body.expose()

    @pytest.mark.security
    async def test_the_user_is_shown_the_body_before_approving(self):
        """Approving a page nobody read is not approving anything."""
        runtime, model = build_write_runtime(revision_script("mention the new queue"))
        console = RecordingConsole(answer="y")

        await publish(runtime, model, console)

        assert "A revised body." in console.transcript
        assert "apollo-architecture" in console.transcript
        assert "Replaces version: 2" in console.transcript

    @pytest.mark.security
    async def test_an_approval_authorises_one_execution_only(self):
        """The ledger entry is consumed, so a second write finds nothing."""
        runtime, model = build_write_runtime(revision_script("mention the new queue"))
        console = RecordingConsole(answer="y")

        await publish(runtime, model, console)

        assert runtime.confirmation_ledger.pending_count(runtime.user) == 0

    async def test_the_write_is_audited(self):
        runtime, model = build_write_runtime(revision_script("mention the new queue"))
        console = RecordingConsole(answer="y")

        await publish(runtime, model, console)

        records = runtime.audit.records_for(WikiToolName.UPDATE_PAGE.value)
        assert [record.outcome for record in records] == [AuditOutcome.EXECUTED]
        assert records[0].target_id == "apollo-architecture"

    @pytest.mark.security
    async def test_a_declined_write_never_reaches_the_domain(self):
        """The middleware refuses the call, so the skill is never entered.

        Same shape as the Mail Agent on Microsoft Agent Framework: a refusal is
        answered by the framework and the tool function never runs, so the audit
        trail holds nothing for it. What the trail records is what happened to
        the wiki, and nothing happened.

        The DECLINED outcome is therefore not dead code: it is what the gated
        runner writes when a skill is invoked directly, from a script or from
        another framework, with a refusal in hand. That path is covered by the
        unit tests.
        """
        runtime, model = build_write_runtime(revision_script("rewrite it"))
        console = RecordingConsole(answer="n")

        await publish(runtime, model, console)

        assert runtime.audit.records_for(WikiToolName.UPDATE_PAGE.value) == ()
        assert "Replace the content of this page?" in console.transcript

    @pytest.mark.security
    async def test_drafting_alone_writes_nothing(self):
        """The drafting turn is never suspended, and the page is untouched."""
        runtime, _ = build_write_runtime(revision_script("mention the new queue"))
        console = RecordingConsole(answer="n")

        await build_session(runtime, console).ask("draft a revision")

        page = await runtime.wiki_tools.get_page("apollo-architecture", runtime.user)
        assert page.version == 2
        assert console.transcript == ""

    @pytest.mark.security
    async def test_an_approved_deletion_names_the_page_to_the_user(self):
        runtime, _ = build_write_runtime(
            [
                calls(ToolCall(WikiToolName.DELETE_PAGE.value, {"page_id": "apollo-old-plan"})),
                says("done"),
            ]
        )
        console = RecordingConsole(answer="y")

        await build_session(runtime, console).ask("delete the old plan page")

        assert "apollo-old-plan" in console.transcript
        assert "Delete this page?" in console.transcript


class TestReasonerWiring:
    """The reasoning port, through the real LangChain path."""

    async def test_the_reasoner_asks_for_structured_output(self):
        from ygo74.agent_runtime.domains.security.prompt_envelope import PromptEnvelopeBuilder

        from ai_agent_lab.core.reasoning.ports import ReasoningRequest
        from ai_agent_lab.langgraph.reasoner import LangGraphTextReasoner

        expected = AnswerOutput(answer="from the model", cited_page_ids=[])
        reasoner = LangGraphTextReasoner(
            ScriptedStructuredModel(expected),
            PromptEnvelopeBuilder(source="a documentation wiki"),
        )

        answer = await reasoner.reason(
            ReasoningRequest(instructions="You are a documentation assistant.", task="Answer."),
            AnswerOutput,
        )

        assert answer.answer == "from the model"

    async def test_a_wrongly_shaped_answer_is_refused(self):
        from ygo74.agent_runtime.domains.security.prompt_envelope import PromptEnvelopeBuilder

        from ai_agent_lab.core.reasoning.errors import ReasoningOutputError
        from ai_agent_lab.core.reasoning.ports import ReasoningRequest
        from ai_agent_lab.langgraph.reasoner import LangGraphTextReasoner

        reasoner = LangGraphTextReasoner(
            ScriptedStructuredModel("not a model at all"),
            PromptEnvelopeBuilder(source="a documentation wiki"),
        )

        with pytest.raises(ReasoningOutputError):
            await reasoner.reason(
                ReasoningRequest(instructions="You are an assistant.", task="Answer."),
                AnswerOutput,
            )
