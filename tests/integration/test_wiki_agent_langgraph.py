"""Integration tests of the Wiki Agent on LangGraph.

The agent, the tools, the human-in-the-loop middleware, the skills and the
in-memory wiki are all the real ones. Only the model is scripted, so a scenario
proves something about the wiring rather than about a sentence a model produced.
"""

from __future__ import annotations

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

from ai_agent_lab.core.security.principal import Principal
from ai_agent_lab.wiki.application.composition import (
    WikiAgentCompositionRoot,
    WikiAgentRuntime,
    thread_id_of,
)
from ai_agent_lab.wiki.capabilities.read_capabilities import ANSWER_FROM_WIKI, SUMMARISE_PAGE
from ai_agent_lab.wiki.catalog import WikiToolName
from ai_agent_lab.wiki.config.settings import WikiAgentMode, WikiAgentSettings
from ai_agent_lab.wiki.skills.analysis import AnswerOutput

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class ScriptedReasoner:
    """Returns a prepared analysis without reaching a model."""

    def __init__(self, output: object) -> None:
        self._output = output

    async def reason(self, request: object, response_model: type) -> object:
        """Return the prepared output."""
        del request, response_model
        return self._output


def build_runtime(
    script: list[ScriptedTurn] | None = None,
    *,
    reasoner: object | None = None,
    settings: WikiAgentSettings | None = None,
    principal: Principal | None = None,
    session_id: str = "integration",
) -> WikiAgentRuntime:
    """Assemble the Wiki Agent with a scripted model and the sample dataset."""
    return WikiAgentCompositionRoot(
        settings or WikiAgentSettings(mode=WikiAgentMode.MOCK),
        ScriptedChatModel(script or [says("nothing to do")]),
        principal=principal or Principal(subject="diana"),
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

    def test_no_capability_changes_the_wiki_in_this_increment(self):
        """The write capabilities exist in code but are not delivered yet."""
        runtime = build_runtime()

        assert runtime.registry.write_skills() == ()


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

    @staticmethod
    def _deliver_binding(root: Path, *, capabilities: list[str]) -> None:
        """Deliver a configuration directory with one partial binding."""
        source = REPOSITORY_ROOT / "config"
        for folder in ("agents", "skills"):
            _copy_tree(source / folder, root / folder)
        (root / "mcp").mkdir(parents=True, exist_ok=True)
        tools = "\n".join(f"  {name}: {name}" for name in capabilities)
        (root / "mcp" / "partial.yaml").write_text(
            "server: partial\ntransport: stdio\ncommand: python\ndialect: native\n"
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
        mine = thread_id_of(Principal(subject="diana"), "conversation-1")
        theirs = thread_id_of(Principal(subject="alice"), "conversation-1")

        assert mine != theirs

    def test_the_identifier_is_stable_for_one_person(self):
        first = thread_id_of(Principal(subject="diana"), "conversation-1")
        second = thread_id_of(Principal(subject="diana"), "conversation-1")

        assert first == second

    def test_a_subject_cannot_be_shaped_to_collide_with_another(self):
        """A delimiter inside a subject is the classic composite-key ambiguity."""
        crafted = thread_id_of(Principal(subject="diana:conversation"), "1")
        genuine = thread_id_of(Principal(subject="diana"), "conversation:1")

        assert crafted != genuine

    def test_the_runtime_uses_the_derived_identifier(self):
        runtime = build_runtime(session_id="conversation-1")

        assert runtime.thread_id == thread_id_of(Principal(subject="diana"), "conversation-1")

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
            principal=Principal(subject="alice"),
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


class TestReasonerWiring:
    """The reasoning port, through the real LangChain path."""

    async def test_the_reasoner_asks_for_structured_output(self):
        from ai_agent_lab.core.reasoning.envelope import PromptEnvelopeBuilder
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
        from ai_agent_lab.core.reasoning.envelope import PromptEnvelopeBuilder
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
