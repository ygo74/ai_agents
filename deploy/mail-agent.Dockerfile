# The Mail Agent, served over HTTP.
#
# Two stages. The first resolves and builds wheels; the second carries only what
# is needed to run, so a compiler that was useful for five seconds does not sit
# in a production image for a year.
#
# The agent holds no mail credential. In `mcp` mode it reaches a mail MCP server
# over HTTP, and that server holds the credential - which is the whole point of
# splitting them into two containers. See docs/deployment.md.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build stage
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Only the distributions this agent needs. The Wiki Agent's LangChain stack is
# deliberately absent: one agent, one framework, which is what keeps the
# comparison between them meaningful and the image small.
COPY agents/core agents/core
COPY agents/maf agents/maf
COPY agents/mail agents/mail
COPY mcp-servers/protocol mcp-servers/protocol

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip wheel \
 && /opt/venv/bin/pip install \
      ./mcp-servers/protocol \
      ./agents/core \
      ./agents/maf \
      "./agents/mail[http,maf,native]"

# ------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="mail-agent" \
      org.opencontainers.image.description="Mail Agent, exposed as an OpenAI-compatible HTTP service." \
      org.opencontainers.image.source="https://github.com/ygo74/ai_agents" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AI_AGENT_LAB_CONFIG_DIR=/app/config

# Non-root, and owning nothing it does not need. The agent writes no file at
# runtime: its state is in memory and its configuration is read-only.
RUN useradd --create-home --uid 10001 agent

WORKDIR /app

COPY --from=build /opt/venv /opt/venv

# Delivered configuration: agent manifest, skill packages, MCP bindings. Bundled
# so the image runs as it stands, and overridable by mounting over /app/config
# when a deployment binds a different server.
COPY config /app/config

# The deterministic dataset, so `MAIL_AGENT_MODE=mock` works with no mailbox and
# no credential - which is how the image should first be tried.
COPY data /app/data

COPY deploy/healthcheck.py /app/healthcheck.py

USER agent

EXPOSE 8123

# The agent refuses to start without a way to identify a caller, so the probe is
# answered with 401 - which is the security policy working, not the process
# failing. See deploy/healthcheck.py for why it carries no credential.
HEALTHCHECK --interval=30s --timeout=6s --start-period=25s --retries=3 \
    CMD ["python", "/app/healthcheck.py", "http://127.0.0.1:8123/v1/models"]

ENTRYPOINT ["uvicorn", "ai_agent_lab.mail.application.entrypoints.service:build_app", "--factory"]
CMD ["--host", "0.0.0.0", "--port", "8123"]
