"""Repository for LLM configuration CRUD.

Manages multiple LLM provider configurations in the database.
Exactly one configuration can be marked as *current* at a time.
The LLM factory reads the current configuration to instantiate the
appropriate LangChain chat model.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from agentic_bus.core.persistence.database import get_session
from agentic_bus.core.persistence.models import LLMConfig

logger = logging.getLogger(__name__)


class LLMConfigNotFoundError(Exception):
    """Raised when a referenced LLM configuration does not exist."""


class NoCurrentLLMConfigError(Exception):
    """Raised when no LLM configuration is marked as current.

    This is NOT a fatal error – the application can start without an LLM
    configuration, but the admin must configure one before the bus can
    process intents.
    """


class LLMConfigRepository:
    """CRUD operations for LLM provider configurations."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def add(
        self,
        name: str,
        provider: str,
        model: str,
        *,
        temperature: float = 0.0,
        api_key: str | None = None,
        extra_config: dict[str, Any] | None = None,
        is_current: bool = False,
        created_by: str = "admin",
    ) -> LLMConfig:
        """Add a new LLM configuration.

        If *is_current* is ``True`` any previously-current configuration
        is automatically deactivated.
        """
        with get_session() as session:
            # Check for duplicate name
            existing = (
                session.query(LLMConfig)
                .filter(LLMConfig.name == name)
                .first()
            )
            if existing is not None:
                raise ValueError(f"LLM configuration {name!r} already exists")

            # If this one should be current, deactivate others
            if is_current:
                self._deactivate_all(session)

            now = datetime.now(timezone.utc)
            config = LLMConfig(
                name=name,
                provider=provider,
                model=model,
                temperature=temperature,
                api_key=api_key,
                extra_config=extra_config or {},
                is_current=is_current,
                created_at=now,
                updated_at=now,
                created_by=created_by,
            )
            session.add(config)
            session.commit()
            session.refresh(config)

        logger.info(
            "LLM config %r added (provider=%s, model=%s, current=%s)",
            name,
            provider,
            model,
            is_current,
        )
        return config

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_current(self) -> LLMConfig:
        """Return the currently active LLM configuration.

        Raises ``NoCurrentLLMConfigError`` if none is marked as current.
        """
        with get_session() as session:
            config = (
                session.query(LLMConfig)
                .filter(LLMConfig.is_current == True)  # noqa: E712
                .first()
            )
            if config is None:
                raise NoCurrentLLMConfigError(
                    "No LLM configuration is active. "
                    "Use 'agbus llm add' or the admin API to configure an LLM provider."
                )
            return config

    def get_current_or_none(self) -> LLMConfig | None:
        """Return the currently active LLM configuration, or ``None``."""
        with get_session() as session:
            return (
                session.query(LLMConfig)
                .filter(LLMConfig.is_current == True)  # noqa: E712
                .first()
            )

    def get_by_name(self, name: str) -> LLMConfig | None:
        """Return a configuration by name."""
        with get_session() as session:
            return (
                session.query(LLMConfig)
                .filter(LLMConfig.name == name)
                .first()
            )

    def get_by_id(self, config_id: int) -> LLMConfig | None:
        """Return a configuration by primary key."""
        with get_session() as session:
            return session.get(LLMConfig, config_id)

    def list_all(self) -> list[LLMConfig]:
        """Return all configurations ordered by name."""
        with get_session() as session:
            return list(
                session.query(LLMConfig).order_by(LLMConfig.name).all()
            )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def activate(self, name: str) -> LLMConfig:
        """Mark the configuration with *name* as current.

        Deactivates any previously-current configuration.
        """
        with get_session() as session:
            config = (
                session.query(LLMConfig)
                .filter(LLMConfig.name == name)
                .first()
            )
            if config is None:
                raise LLMConfigNotFoundError(
                    f"LLM configuration {name!r} not found"
                )
            self._deactivate_all(session)
            config.is_current = True
            config.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(config)

        logger.info("LLM config %r activated", name)
        return config

    def update(
        self,
        name: str,
        *,
        provider: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        api_key: str | None = None,
        extra_config: dict[str, Any] | None = None,
    ) -> LLMConfig:
        """Update fields of an existing configuration."""
        with get_session() as session:
            config = (
                session.query(LLMConfig)
                .filter(LLMConfig.name == name)
                .first()
            )
            if config is None:
                raise LLMConfigNotFoundError(
                    f"LLM configuration {name!r} not found"
                )
            if provider is not None:
                config.provider = provider
            if model is not None:
                config.model = model
            if temperature is not None:
                config.temperature = temperature
            if api_key is not None:
                config.api_key = api_key
            if extra_config is not None:
                config.extra_config = extra_config
            config.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(config)

        logger.info("LLM config %r updated", name)
        return config

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, name: str) -> bool:
        """Remove a configuration by name. Returns ``True`` if found."""
        with get_session() as session:
            config = (
                session.query(LLMConfig)
                .filter(LLMConfig.name == name)
                .first()
            )
            if config is None:
                return False
            session.delete(config)
            session.commit()
        logger.info("LLM config %r deleted", name)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _deactivate_all(session) -> None:
        """Set ``is_current=False`` for every configuration in this session."""
        session.query(LLMConfig).filter(
            LLMConfig.is_current == True  # noqa: E712
        ).update({"is_current": False})
