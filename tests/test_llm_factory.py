"""Tests for the centralized LLM factory.

The factory reads from:
1. Explicit keyword arguments (highest priority)
2. Current LLMConfig in the database
3. Environment variables (fallback)
"""

import os
from unittest.mock import patch

import pytest

from app.core.llm.factory import get_llm, LLMProvider, _DEFAULT_MODELS


# Helper: patch _load_db_config to return None (no DB config), so env vars
# are used.  This keeps existing tests stable.
_NO_DB = patch("app.core.llm.factory._load_db_config", return_value=None)


class TestLLMProvider:
    def test_all_providers_defined(self):
        expected = {"openai", "anthropic", "google", "ollama", "azure"}
        actual = {p.value for p in LLMProvider}
        assert actual == expected

    def test_every_provider_has_default_model(self):
        for provider in LLMProvider:
            assert provider in _DEFAULT_MODELS


class TestGetLLM:
    def test_openai_default_from_env(self):
        """When no DB config, env fallback returns a ChatOpenAI instance."""
        with _NO_DB, patch.dict(os.environ, {
            "AGBUS_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "test-key",
        }, clear=False):
            llm = get_llm()
        assert type(llm).__name__ == "ChatOpenAI"

    def test_openai_explicit(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
            llm = get_llm(provider="openai", model="gpt-4o", temperature=0.5)
        assert type(llm).__name__ == "ChatOpenAI"

    def test_provider_from_env(self):
        """AGBUS_LLM_PROVIDER env var selects the provider when no DB config."""
        env = {"AGBUS_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "k"}
        with _NO_DB, patch.dict(os.environ, env, clear=False):
            llm = get_llm()
        assert type(llm).__name__ == "ChatOpenAI"

    def test_model_from_env(self):
        env = {"AGBUS_LLM_PROVIDER": "openai", "AGBUS_LLM_MODEL": "gpt-4o", "OPENAI_API_KEY": "k"}
        with _NO_DB, patch.dict(os.environ, env, clear=False):
            llm = get_llm()
        assert llm.model_name == "gpt-4o"

    def test_temperature_from_env(self):
        env = {"AGBUS_LLM_PROVIDER": "openai", "AGBUS_LLM_TEMPERATURE": "0.7", "OPENAI_API_KEY": "k"}
        with _NO_DB, patch.dict(os.environ, env, clear=False):
            llm = get_llm()
        assert llm.temperature == 0.7

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            get_llm(provider="not_a_provider")

    def test_explicit_params_override_env(self):
        env = {
            "AGBUS_LLM_PROVIDER": "anthropic",
            "AGBUS_LLM_MODEL": "claude-ignored",
            "OPENAI_API_KEY": "k",
        }
        with patch.dict(os.environ, env, clear=False):
            llm = get_llm(provider="openai", model="gpt-4o-mini")
        assert type(llm).__name__ == "ChatOpenAI"

    def test_azure_builder(self):
        """Azure provider returns AzureChatOpenAI."""
        env = {
            "AZURE_OPENAI_API_KEY": "az-key",
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
            "AZURE_OPENAI_API_VERSION": "2024-12-01-preview",
        }
        with patch.dict(os.environ, env, clear=False):
            llm = get_llm(provider="azure", model="gpt-4o-mini")
        assert type(llm).__name__ == "AzureChatOpenAI"

    def test_db_config_used_when_present(self):
        """When a DB config is available, it takes precedence over env."""
        db_cfg = {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.3,
            "api_key": "db-test-key",
            "extra_config": {},
        }
        with patch("app.core.llm.factory._load_db_config", return_value=db_cfg):
            llm = get_llm()
        assert type(llm).__name__ == "ChatOpenAI"
        assert llm.model_name == "gpt-4o"
        assert llm.temperature == 0.3

    def test_no_config_at_all_raises(self):
        """When no DB config and no env vars, raise NoCurrentLLMConfigError."""
        from app.core.persistence.llm_repository import NoCurrentLLMConfigError

        clean_env = {
            k: v for k, v in os.environ.items()
            if k not in ("AGBUS_LLM_PROVIDER",)
        }
        with _NO_DB, patch.dict(os.environ, clean_env, clear=True):
            with pytest.raises(NoCurrentLLMConfigError, match="No LLM provider configured"):
                get_llm()

    def test_explicit_params_skip_db_lookup(self):
        """When all params are explicit, DB is not consulted."""
        with patch("app.core.llm.factory._load_db_config") as mock_db:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=False):
                _llm = get_llm(provider="openai", model="gpt-4o-mini", temperature=0.0)
            mock_db.assert_not_called()


class TestLazyImports:
    """Verify that unsupported provider packages produce a clear error."""

    def test_anthropic_import_error(self):
        """If langchain-anthropic is not installed, the error message is clear."""
        with patch.dict(
            "sys.modules", {"langchain_anthropic": None}
        ):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                get_llm(provider="anthropic")

    def test_google_import_error(self):
        with patch.dict(
            "sys.modules", {"langchain_google_genai": None}
        ):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                get_llm(provider="google")

    def test_ollama_import_error(self):
        with patch.dict(
            "sys.modules", {"langchain_ollama": None}
        ):
            with pytest.raises((ImportError, ModuleNotFoundError)):
                get_llm(provider="ollama")
