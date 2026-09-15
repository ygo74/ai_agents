# The Gmail MCP server, served over HTTP.
#
# This container is the one that holds a credential, and everything about it
# follows from that.
#
# It carries no agent and no agentic framework - which is not an accident of
# packaging but the claim its `pyproject` makes: a mail MCP server needs neither.
# The image proves it.
#
# Two things it cannot do, and both are deployment facts rather than limitations:
#
#   * It cannot obtain the initial Google consent. That flow opens a browser and
#     listens on the loopback interface. Run `mail-mcp-gmail-authorise` once on a
#     workstation and mount the resulting token file read-only.
#   * It cannot be safely exposed. Over stdio this server was protected by being
#     a child process; over HTTP it is protected by a token and nothing else.
#     Without `MAIL_MCP_HTTP_TOKEN` it refuses to start, deliberately.
#
# See docs/deployment.md.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- build stage
FROM python:${PYTHON_VERSION}-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY mcp-servers/protocol mcp-servers/protocol
COPY mcp-servers/gmail mcp-servers/gmail

# Locally built runtime wheels, when there are any. Empty in a normal build, so the
# runtime comes from the index like every other dependency. It exists because a
# release cannot be verified in a container before it is published, and the one
# defect that cost this repository a production-shaped incident was invisible
# outside one. See deploy/README.md.
COPY deploy/wheels /wheels

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip wheel \
 && /opt/venv/bin/pip install $(ls /wheels/*.whl >/dev/null 2>&1 && echo "--find-links /wheels") \
      "./mcp-servers/protocol[serving,http]" \
      ./mcp-servers/gmail

# ------------------------------------------------------------- runtime stage
FROM python:${PYTHON_VERSION}-slim AS runtime

LABEL org.opencontainers.image.title="mail-mcp-gmail" \
      org.opencontainers.image.description="Mail MCP server backed by the Gmail REST API, over authenticated HTTP." \
      org.opencontainers.image.source="https://github.com/ygo74/ai_agents" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GMAIL_OAUTH_TOKEN_FILE=/secrets/gmail-token.json

RUN useradd --create-home --uid 10002 mcp

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY deploy/healthcheck.py /app/healthcheck.py

# Where the mounted token is expected. Created empty and owned by the runtime
# user so a read-only bind mount lands somewhere that already exists.
RUN mkdir -p /secrets && chown mcp:mcp /secrets

USER mcp

EXPOSE 9100

# `/healthz` is the one unauthenticated path, on purpose: an orchestrator must be
# able to ask whether the process is alive without being handed a credential, and
# the answer discloses nothing about the mailbox.
HEALTHCHECK --interval=30s --timeout=6s --start-period=15s --retries=3 \
    CMD ["python", "/app/healthcheck.py", "http://127.0.0.1:9100/healthz"]

ENTRYPOINT ["mail-mcp-gmail"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "9100"]
