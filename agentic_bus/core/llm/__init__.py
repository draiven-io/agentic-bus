"""Centralized LLM instantiation for Agentic Bus.

Provides a single ``get_llm()`` factory that reads the current LLM
configuration from the database and returns the corresponding LangChain
chat model.  Falls back to environment variables when no database
configuration is available.

Configuration hierarchy:
1. Explicit keyword arguments to ``get_llm()``.
2. Current ``LLMConfig`` row in the database (``is_current=True``).
3. Environment variables (``AGBUS_LLM_PROVIDER``, ``AGBUS_LLM_MODEL``, etc.).

The application can start without any LLM configured.  The admin must
configure a provider before the bus can process intents.

Supported providers:

- ``openai``   – OpenAI  (API key stored in DB or ``OPENAI_API_KEY``)
- ``anthropic``– Anthropic  (API key stored in DB or ``ANTHROPIC_API_KEY``)
- ``google``   – Google Gemini  (API key stored in DB or ``GOOGLE_API_KEY``)
- ``ollama``   – Ollama local  (base_url in extra_config or ``AGBUS_OLLAMA_BASE_URL``)
- ``azure``    – Azure OpenAI  (API key + endpoint in DB or env vars)

Usage::

    from agentic_bus.core.llm import get_llm

    llm = get_llm()                       # uses DB config (or env fallback)
    llm = get_llm(provider="anthropic")   # explicit override
"""

from agentic_bus.core.llm.factory import get_llm, LLMProvider

__all__ = ["get_llm", "LLMProvider"]
