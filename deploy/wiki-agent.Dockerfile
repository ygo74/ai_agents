# The Wiki Agent, served over HTTP.
#
# Same shape as the Mail Agent, one framework apart: this one runs on
# LangChain/LangGraph, and no `agent-framework` package enters the image. That
# separation is what keeps the comparison between the two agents meaningful, and
# it is worth preserving in the images rather than only in the environments.
#
# No MCP server is bundled. The Wiki Agent reaches `sooperset/mcp-atlassian`,
# which is a third-party image started alongside - and over HTTP it forwards the
# caller's own credential, so the agent acts on behalf of the person asking
# rather than as one shared account. See docs/deployment.md.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build stage
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY agents/core agents/core
COPY agents/langgraph agents/langgraph
COPY agents/wiki agents/wiki
COPY mcp-servers/wiki-protocol mcp-servers/wiki-protocol

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip wheel \
 && /opt/venv/bin/pip install \
      ./mcp-servers/wiki-protocol \
      ./agents/core \
      ./agents/langgraph \
      "./agents/wiki[http,langgraph,native]"

# ------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="wiki-agent" \
      org.opencontainers.image.description="Wiki Agent, exposed as an OpenAI-compatible HTTP service." \
      org.opencontainers.image.source="https://github.com/ygo74/ai_agents" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_AGENT_LAB_CONFIG_DIR=/app/config

RUN useradd --create-home --uid 10001 agent

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY config /app/config
COPY data /app/data
COPY deploy/healthcheck.py /app/healthcheck.py

USER agent

EXPOSE 8124

# Answered with 401: the agent refuses unauthenticated callers, and that refusal
# is the policy working. See deploy/healthcheck.py.
HEALTHCHECK --interval=30s --timeout=6s --start-period=25s --retries=3 \
    CMD ["python", "/app/healthcheck.py", "http://127.0.0.1:8124/v1/models"]

ENTRYPOINT ["uvicorn", "ai_agent_lab.wiki.application.entrypoints.service:build_app", "--factory"]
CMD ["--host", "0.0.0.0", "--port", "8124"]
