FROM python:3.13-slim

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG CLAUDE_CODE_VERSION=2.1.322
ARG HA_MCP_VERSION=9.2.0

ENV PATH="/root/.local/bin:${PATH}" \
    DISABLE_AUTOUPDATER=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -fsSL https://claude.ai/install.sh | bash -s "${CLAUDE_CODE_VERSION}" \
    && claude --version \
    && pip install --no-cache-dir "ha-mcp==${HA_MCP_VERSION}"

COPY gateway.py prompts.py /app/
COPY web /app/web
WORKDIR /app

LABEL \
    io.hass.name="Voice Agent Bridge" \
    io.hass.description="Talk to Claude through Assist and your voice satellites" \
    io.hass.type="addon" \
    io.hass.arch="amd64|aarch64" \
    org.opencontainers.image.title="Voice Agent Bridge" \
    org.opencontainers.image.authors="Pintjes" \
    org.opencontainers.image.source="https://github.com/Pintjes/ha-addons" \
    org.opencontainers.image.licenses="GPL-3.0-or-later"

CMD [ "python3", "-u", "/app/gateway.py" ]
