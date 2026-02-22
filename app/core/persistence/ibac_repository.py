"""Repository for IBAC rule CRUD.

Admin-configurable guardrails stored in the database and loaded by the
IBAC engine at evaluation time.  Follows the same session/repository
pattern used by ``LLMConfigRepository`` and ``AgentRepository``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.core.persistence.database import get_session
from app.core.persistence.models import IBACRule, IBACRuleAction

logger = logging.getLogger(__name__)


class IBACRuleNotFoundError(Exception):
    """Raised when a referenced IBAC rule does not exist."""


class IBACRuleRepository:
    """CRUD operations for persisted IBAC rules."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def add(
        self,
        rule_id: str,
        name: str,
        *,
        description: str = "",
        enabled: bool = True,
        priority: int = 100,
        action: str = "deny",
        evaluation_points: list[str] | None = None,
        conditions: dict[str, Any] | None = None,
        created_by: str = "admin",
    ) -> IBACRule:
        """Create a new IBAC rule.

        Raises ``ValueError`` if a rule with the same *rule_id* exists.
        """
        with get_session() as session:
            existing = (
                session.query(IBACRule)
                .filter(IBACRule.rule_id == rule_id)
                .first()
            )
            if existing is not None:
                raise ValueError(f"IBAC rule {rule_id!r} already exists")

            now = datetime.now(timezone.utc)
            rule = IBACRule(
                rule_id=rule_id,
                name=name,
                description=description,
                enabled=enabled,
                priority=priority,
                action=IBACRuleAction(action),
                evaluation_points_json=evaluation_points or [],
                conditions_json=conditions or {},
                created_at=now,
                updated_at=now,
                created_by=created_by,
            )
            session.add(rule)
            session.commit()
            session.refresh(rule)

        logger.info("IBAC rule %r created (action=%s, priority=%d)", rule_id, action, priority)
        return rule

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, rule_id: str) -> IBACRule | None:
        """Return a single rule by *rule_id*, or ``None``."""
        with get_session() as session:
            return (
                session.query(IBACRule)
                .filter(IBACRule.rule_id == rule_id)
                .first()
            )

    def list_all(self, *, enabled_only: bool = False) -> list[IBACRule]:
        """Return all rules ordered by priority (ascending).

        If *enabled_only* is ``True`` only active rules are returned.
        """
        with get_session() as session:
            q = session.query(IBACRule)
            if enabled_only:
                q = q.filter(IBACRule.enabled == True)  # noqa: E712
            return list(q.order_by(IBACRule.priority.asc()).all())

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self,
        rule_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        priority: int | None = None,
        action: str | None = None,
        evaluation_points: list[str] | None = None,
        conditions: dict[str, Any] | None = None,
    ) -> IBACRule:
        """Update an existing rule.  Only provided fields are changed.

        Raises ``IBACRuleNotFoundError`` if the rule does not exist.
        """
        with get_session() as session:
            rule = (
                session.query(IBACRule)
                .filter(IBACRule.rule_id == rule_id)
                .first()
            )
            if rule is None:
                raise IBACRuleNotFoundError(f"IBAC rule {rule_id!r} not found")

            if name is not None:
                rule.name = name
            if description is not None:
                rule.description = description
            if enabled is not None:
                rule.enabled = enabled
            if priority is not None:
                rule.priority = priority
            if action is not None:
                rule.action = IBACRuleAction(action)
            if evaluation_points is not None:
                rule.evaluation_points_json = evaluation_points
            if conditions is not None:
                rule.conditions_json = conditions

            rule.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(rule)

        logger.info("IBAC rule %r updated", rule_id)
        return rule

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, rule_id: str) -> bool:
        """Delete a rule.  Returns ``True`` if it was found and deleted."""
        with get_session() as session:
            rule = (
                session.query(IBACRule)
                .filter(IBACRule.rule_id == rule_id)
                .first()
            )
            if rule is None:
                return False
            session.delete(rule)
            session.commit()

        logger.info("IBAC rule %r deleted", rule_id)
        return True
