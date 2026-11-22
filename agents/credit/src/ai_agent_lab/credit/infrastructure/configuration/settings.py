"""Typed local settings loaded alongside the runtime-validated agent manifests."""

import os
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field
from ygo74.agent_runtime.domains.configuration.manifests import YamlDocument

from ai_agent_lab.core.config.chat import ChatProvider


class CreditCapability(StrEnum):
    """The single read-only business capability this delivery supports."""

    IDENTIFY_COMPANY = "identify_company"


class CreditSettings(BaseModel):
    """Nonsecret model routing and bounded MCP read policy."""

    model_config = ConfigDict(extra="forbid")
    model_provider: ChatProvider = ChatProvider.OPENAI
    model: str = ""
    azure_endpoint: str = ""
    azure_api_version: str = ""
    search_limit: int = Field(default=50, ge=2, le=100)
    max_attempts: int = Field(default=2, ge=1, le=3)
    retry_delay: float = Field(default=1, ge=0, le=30)

    @classmethod
    def load(cls, path: Path) -> Self:
        """Validate YAML then allow designated nonsecret route overrides from the environment."""
        settings = YamlDocument(path).validate(cls)
        values = settings.model_dump()
        for key in ("model_provider", "model", "azure_endpoint", "azure_api_version"):
            value = os.environ.get(f"CREDIT_{key.upper()}")
            if value:
                values[key] = value
        return cls.model_validate(values)
