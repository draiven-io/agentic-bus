#!/usr/bin/env sh
#
# Coordinator container bootstrap.
#
# Everything here is idempotent: the container is restarted freely and the
# database lives on a volume, so each step checks whether it already ran
# rather than assuming a clean slate.
#
# Controlled by:
#   AGBUS_BOOTSTRAP_LLM_PROVIDER  register this provider as the active LLM
#   AGBUS_BOOTSTRAP_LLM_MODEL     model name for that provider
#   AGBUS_BOOTSTRAP_LLM_BASE_URL  base URL (Ollama) — also used for readiness
#   AGBUS_BOOTSTRAP_LLM_API_KEY   API key (hosted providers)
#   AGBUS_SEED_DEMO               "true" seeds the logistics demo agents
#
# With none of them set the container just runs the coordinator, which is
# what a production deployment wants.

set -eu

log() { printf '[bootstrap] %s\n' "$1"; }

# --------------------------------------------------------------------------
# Wait for the LLM backend, when it is one we start alongside us
# --------------------------------------------------------------------------
# Ollama pulls its model on first boot, so the coordinator can otherwise come
# up and register an LLM that isn't answering yet.
if [ -n "${AGBUS_BOOTSTRAP_LLM_BASE_URL:-}" ]; then
    log "waiting for LLM backend at ${AGBUS_BOOTSTRAP_LLM_BASE_URL}"
    attempt=0
    until curl -sf "${AGBUS_BOOTSTRAP_LLM_BASE_URL}/api/tags" >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 60 ]; then
            log "LLM backend did not become ready after 60 attempts — continuing anyway"
            log "the coordinator will start, but intents will fail until it is reachable"
            break
        fi
        sleep 2
    done
    if [ "$attempt" -lt 60 ]; then
        log "LLM backend is ready"
    fi
fi

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
# init_db() creates missing tables and adds missing columns, so this is safe
# on both a fresh volume and an existing one.
log "ensuring database schema"
agbus db init

# --------------------------------------------------------------------------
# LLM configuration
# --------------------------------------------------------------------------
# Stored in the database rather than the environment, so it survives restarts
# and only needs registering once.
if [ -n "${AGBUS_BOOTSTRAP_LLM_PROVIDER:-}" ]; then
    config_name="${AGBUS_BOOTSTRAP_LLM_PROVIDER}-default"

    set -- llm add \
        --name "$config_name" \
        --provider "$AGBUS_BOOTSTRAP_LLM_PROVIDER" \
        --model "${AGBUS_BOOTSTRAP_LLM_MODEL:-llama3}" \
        --activate

    if [ -n "${AGBUS_BOOTSTRAP_LLM_BASE_URL:-}" ]; then
        set -- "$@" --base-url "$AGBUS_BOOTSTRAP_LLM_BASE_URL"
    fi
    if [ -n "${AGBUS_BOOTSTRAP_LLM_API_KEY:-}" ]; then
        set -- "$@" --api-key "$AGBUS_BOOTSTRAP_LLM_API_KEY"
    fi

    if agbus "$@" >/dev/null 2>&1; then
        log "registered LLM configuration '$config_name'"
    else
        # Already present from an earlier boot — just make sure it is active.
        agbus llm activate "$config_name" >/dev/null 2>&1 \
            && log "LLM configuration '$config_name' already existed — activated" \
            || log "could not register or activate '$config_name'; configure it via 'agbus llm add'"
    fi
fi

# --------------------------------------------------------------------------
# Demo agents
# --------------------------------------------------------------------------
# The seeder skips agents that already exist, and creates them ACTIVE — the
# coordinator auto-starts every active managed agent when it boots, so no
# separate agent containers are needed.
if [ "${AGBUS_SEED_DEMO:-false}" = "true" ]; then
    log "seeding logistics demo agents"
    python -m app.agents.examples.logistics_agent.seed_managed_agents >/dev/null 2>&1 \
        && log "demo agents ready" \
        || log "demo agent seeding failed — the coordinator will start without them"
fi

log "starting coordinator"
exec "$@"
