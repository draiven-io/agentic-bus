"""LLM factory – provider-agnostic chat model instantiation.

Every LangChain chat model implements ``BaseChatModel``, so callers never need
to know which provider is behind the interface.

Configuration hierarchy
-----------------------
1. Explicit keyword arguments passed to ``get_llm()``.
2. The **current** ``LLMConfig`` row in the database (``is_current=True``).
3. Environment variable fallbacks (``AGBUS_LLM_PROVIDER``, ``AGBUS_LLM_MODEL``,
   ``AGBUS_LLM_TEMPERATURE``).

The application **can start** without any LLM configuration.  However, any
subsystem that calls ``get_llm()`` without explicit overrides will receive a
``NoCurrentLLMConfigError`` if no database configuration exists and no env
vars are set.  The admin must configure an LLM provider before the bus can
process intents.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    OLLAMA = "ollama"
    AZURE = "azure"


# Default model per provider
_DEFAULT_MODELS: dict[LLMProvider, str] = {
    LLMProvider.OPENAI: "gpt-4o-mini",
    LLMProvider.ANTHROPIC: "claude-sonnet-4-20250514",
    LLMProvider.GOOGLE: "gemini-2.0-flash",
    LLMProvider.OLLAMA: "llama3",
    LLMProvider.AZURE: "gpt-4o-mini",
}


# ---------------------------------------------------------------------------
# Database configuration loader
# ---------------------------------------------------------------------------


def _load_db_config() -> dict[str, Any] | None:
    """Try to load the current LLM config from the database.

    Returns a dict with ``provider``, ``model``, ``temperature``,
    ``api_key``, and ``extra_config`` – or ``None`` if no current
    configuration is set or the database is not yet initialised.
    """
    try:
        from app.core.persistence.llm_repository import LLMConfigRepository

        repo = LLMConfigRepository()
        config = repo.get_current_or_none()
        if config is None:
            return None
        return {
            "provider": config.provider,
            "model": config.model,
            "temperature": config.temperature,
            "api_key": config.api_key,
            "extra_config": config.extra_config or {},
        }
    except Exception:
        # Database may not be initialised yet – that's fine.
        logger.debug("Could not load LLM config from database", exc_info=True)
        return None


def get_llm(
    *,
    provider: str | LLMProvider | None = None,
    model: str | None = None,
    temperature: float | None = None,
    **kwargs: Any,
) -> BaseChatModel:
    """Return a LangChain chat model for the configured provider.

    Parameters
    ----------
    provider:
        Override the provider.
    model:
        Override the model name.
    temperature:
        Override the sampling temperature.
    **kwargs:
        Extra keyword arguments forwarded to the underlying constructor.
    """
    # 1. Load DB config (only when caller did not supply explicit overrides)
    db_config: dict[str, Any] | None = None
    if provider is None and model is None and temperature is None:
        db_config = _load_db_config()

    # 2. Resolve provider
    if provider is not None:
        raw_provider = provider
    elif db_config is not None:
        raw_provider = db_config["provider"]
    else:
        raw_provider = os.getenv("AGBUS_LLM_PROVIDER", "")

    if not raw_provider:
        from app.core.persistence.llm_repository import NoCurrentLLMConfigError

        raise NoCurrentLLMConfigError(
            "No LLM provider configured. "
            "Use 'agbus llm add' or the admin API to configure an LLM provider, "
            "or set AGBUS_LLM_PROVIDER in the environment."
        )

    try:
        resolved_provider = LLMProvider(str(raw_provider).lower())
    except ValueError:
        valid = ", ".join(p.value for p in LLMProvider)
        raise ValueError(
            f"Unsupported LLM provider: {raw_provider!r}. Choose from: {valid}"
        ) from None

    # 3. Resolve model
    if model is not None:
        resolved_model = model
    elif db_config is not None:
        resolved_model = db_config["model"]
    else:
        resolved_model = os.getenv(
            "AGBUS_LLM_MODEL", _DEFAULT_MODELS[resolved_provider]
        )

    # 4. Resolve temperature
    if temperature is not None:
        resolved_temp = temperature
    elif db_config is not None:
        resolved_temp = db_config["temperature"]
    else:
        resolved_temp = float(os.getenv("AGBUS_LLM_TEMPERATURE", "0.0"))

    # 5. Inject API key and extra config from DB into kwargs
    if db_config is not None:
        api_key = db_config.get("api_key")
        extra = db_config.get("extra_config", {})

        # Set the provider-specific API key env var so that LangChain
        # constructors pick it up transparently.
        if api_key:
            _inject_api_key_env(resolved_provider, api_key)
            # Also pass api_key directly in kwargs for providers that need it
            kwargs.setdefault("api_key", api_key)

        # Merge extra_config into kwargs (kwargs take precedence)
        for k, v in extra.items():
            kwargs.setdefault(k, v)

    # 6. Build the chat model
    builder = _BUILDERS.get(resolved_provider)
    if builder is None:
        raise ValueError(
            f"Unsupported LLM provider: {resolved_provider!r}. "
            f"Choose from: {', '.join(p.value for p in LLMProvider)}"
        )

    llm = builder(resolved_model, resolved_temp, **kwargs)
    logger.info(
        "LLM initialised: provider=%s model=%s temperature=%s",
        resolved_provider.value,
        resolved_model,
        resolved_temp,
    )
    return llm


def _inject_api_key_env(provider: LLMProvider, api_key: str) -> None:
    """Set the env var that the LangChain provider constructor reads."""
    env_map = {
        LLMProvider.OPENAI: "OPENAI_API_KEY",
        LLMProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
        LLMProvider.GOOGLE: "GOOGLE_API_KEY",
        LLMProvider.AZURE: "AZURE_OPENAI_API_KEY",
        # Ollama is local – no API key needed
    }
    env_var = env_map.get(provider)
    if env_var:
        os.environ[env_var] = api_key


# ---------------------------------------------------------------------------
# Per-provider builders (lazy imports to avoid hard dependency on every SDK)
# ---------------------------------------------------------------------------


def _build_openai(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=model, temperature=temperature, **kwargs)


def _build_anthropic(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, temperature=temperature, **kwargs)


def _build_google(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=model, temperature=temperature, **kwargs)


def _build_ollama(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    from langchain_ollama import ChatOllama

    base_url = kwargs.pop("base_url", None) or os.getenv(
        "AGBUS_OLLAMA_BASE_URL", "http://localhost:11434"
    )
    return ChatOllama(model=model, temperature=temperature, base_url=base_url, **kwargs)


def _build_azure(model: str, temperature: float, **kwargs: Any) -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    # Support both naming conventions from DB extra_config
    azure_deployment = (
        kwargs.pop("azure_deployment", None)
        or kwargs.pop("azure_openai_deployment", None)
        or os.getenv("AZURE_OPENAI_DEPLOYMENT", model)
    )
    api_version = (
        kwargs.pop("api_version", None)
        or kwargs.pop("azure_openai_api_version", None)
        or os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    )
    azure_endpoint = (
        kwargs.pop("azure_endpoint", None)
        or kwargs.pop("azure_openai_endpoint", None)
        or os.getenv("AZURE_OPENAI_ENDPOINT")
    )
    api_key = kwargs.pop("api_key", None) or os.getenv("AZURE_OPENAI_API_KEY")

    return AzureChatOpenAI(
        azure_deployment=azure_deployment,
        api_version=api_version,
        azure_endpoint=azure_endpoint,
        api_key=api_key,
        temperature=temperature,
        **kwargs,
    )


_BUILDERS = {
    LLMProvider.OPENAI: _build_openai,
    LLMProvider.ANTHROPIC: _build_anthropic,
    LLMProvider.GOOGLE: _build_google,
    LLMProvider.OLLAMA: _build_ollama,
    LLMProvider.AZURE: _build_azure,
}
