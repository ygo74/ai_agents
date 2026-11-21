"""Prove native MAF actually invokes the runtime-registered deterministic skill."""

from pathlib import Path

from tests.support.maf_fakes import ScriptedChatClient, ToolCall, calls, says
from tests.unit.credit.test_identification import FakeEdgar, company

from ai_agent_lab.credit.adapters.capabilities.registry import build_registry
from ai_agent_lab.credit.application.skills.identification import IdentificationSkill
from ai_agent_lab.credit.bootstrap.composition import CreditApplication


async def test_native_framework_invokes_registered_skill():
    application = CreditApplication(Path("config"))
    fake = FakeEdgar([company(tickers=("AAPL",))])
    application.registry = build_registry(application.manifest, IdentificationSkill(fake))
    model = ScriptedChatClient(
        [
            calls(ToolCall("identify_company", {"query": "aapl", "query_type": "ticker"})),
            says("Issuer identified for analyst review."),
        ]
    )
    try:
        agent = application.native_agent(model)
        response = await agent.run("Identify Apple")
        assert response.text == "Issuer identified for analyst review."
        assert fake.calls == [("search", "AAPL"), ("profile", "0000320193")]
        assert model.offered_tools[0] == ("identify_company",)
        contents = " ".join(
            str(content.result)
            for message in model.received_messages[-1]
            for content in message.contents
            if content.type == "function_result"
        )
        assert "0000320193" in contents
        assert "untrusted_sec_data" in contents
    finally:
        await application.aclose()
