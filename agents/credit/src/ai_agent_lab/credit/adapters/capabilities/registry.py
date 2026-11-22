"""Bind the deterministic use case to the runtime's public capability contract."""

from collections.abc import Sequence

from pydantic import BaseModel
from ygo74.agent_runtime.domains.contracts.capability_registry import ResultRenderer, SkillDescriptor, SkillRegistry
from ygo74.agent_runtime.domains.contracts.manifests import AgentManifest
from ygo74.agent_runtime.domains.security.permissions import Permission
from ygo74.agent_runtime.domains.security.user_context import UserContext

from ai_agent_lab.credit.application.skills.identification import IdentificationSkill
from ai_agent_lab.credit.domain.models import IdentificationRequest

IDENTIFY_PERMISSION = Permission("credit", "identify")


class CreditResultRenderer(ResultRenderer):
    """Fence validated JSON so external strings remain data for the model."""

    def render(self, result: BaseModel | Sequence[BaseModel]) -> str:
        """Encode tool output safely rather than concatenating external instructions."""
        if not isinstance(result, BaseModel):
            raise TypeError("credit renderer expects one typed result")
        encoded = result.model_dump_json().replace("<", "\\u003c").replace(">", "\\u003e")
        return "<untrusted_sec_data>\n" + encoded + "\n</untrusted_sec_data>"


def build_registry(manifest: AgentManifest, skill: IdentificationSkill) -> SkillRegistry:
    """Refuse unexpected delivered implementations and bind one read-only invocation."""
    if len(manifest.skills) != 1 or manifest.skills[0].implementation != "credit.identify":
        raise ValueError("credit agent must expose only credit.identify")
    declared = manifest.skills[0]
    if declared.tool_name != "identify_company" or set(declared.mcp_tools) != {"edgar_search", "edgar_company"}:
        raise ValueError("credit identification MCP allowlist mismatch")
    if declared.operation.is_write or declared.operation.required_permission != IDENTIFY_PERMISSION:
        raise ValueError("credit identification must be a read with credit:identify permission")

    async def invoke(payload: BaseModel, user: UserContext) -> BaseModel:
        """Enforce runtime caller permission before deterministic business execution."""
        user.require_permission(IDENTIFY_PERMISSION)
        return await skill.execute(payload.model_dump())

    return SkillRegistry(skills=(SkillDescriptor.from_manifest(declared, IdentificationRequest, invoke),))
