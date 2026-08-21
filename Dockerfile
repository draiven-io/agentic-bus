# Agentic Bus coordinator — WebSocket bus (8765) + Admin REST API (8766).
#
# Built with [server] (the coordinator stack), [agents] so it can run the
# CrewAI-backed managed agents it auto-starts on boot, and [mcp] so MCP
# servers registered through the dashboard can be bridged onto the bus.

FROM python:3.12-slim AS builder

# Building crewai's dependency tree needs a compiler for a few sdists.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install into an isolated prefix that the runtime stage copies wholesale,
# leaving the toolchain behind.
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# LICENSE is required at build time: pyproject.toml declares
# `license = { file = "LICENSE" }`, and hatchling reads it to fill in the
# package metadata.
COPY pyproject.toml README.md LICENSE ./
COPY agentic_bus ./agentic_bus

RUN pip install --prefix=/install ".[server,agents,mcp]"


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Agentic Bus" \
      org.opencontainers.image.description="Reference implementation of the Liquid Interfaces Protocol" \
      org.opencontainers.image.source="https://github.com/draiven-io/agentic-bus" \
      org.opencontainers.image.licenses="MIT"

# curl is used by the compose healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# The database lives on a volume; the app writes nothing else at runtime.
RUN useradd --create-home --uid 10001 agbus \
    && mkdir -p /data \
    && chown agbus:agbus /data

WORKDIR /app
COPY --chown=agbus:agbus agentic_bus ./agentic_bus
COPY --chown=agbus:agbus docker/coordinator-entrypoint.sh /usr/local/bin/coordinator-entrypoint.sh
RUN chmod +x /usr/local/bin/coordinator-entrypoint.sh

USER agbus

ENV AGBUS_HOST=0.0.0.0 \
    AGBUS_PORT=8765 \
    AGBUS_API_PORT=8766 \
    AGBUS_DATABASE_URL=sqlite:////data/agbus.db \
    PYTHONUNBUFFERED=1

# 8765 = LIP WebSocket transport, 8766 = admin REST API.
EXPOSE 8765 8766

ENTRYPOINT ["coordinator-entrypoint.sh"]
CMD ["agbus", "serve"]
