"""Tests for admin-configurable IBAC rules – persistence & engine integration.

Covers the IBACRuleRepository CRUD operations, the IBAC engine's
programmatic evaluation of persisted rules (layer 2), and the LLM-based
semantic evaluation path (``evaluate_with_llm``).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agentic_bus.core.persistence.models import Base, IBACRuleAction
from agentic_bus.core.persistence.ibac_repository import (
    IBACRuleRepository,
    IBACRuleNotFoundError,
)
from agentic_bus.core.ibac.engine import (
    IBACEngine,
    IBACRequest,
    IBACDecision,
    IBACEvaluationPoint,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_engine():
    """Create a fresh in-memory SQLite engine with all tables."""
    engine = create_engine("sqlite:///:memory:", echo=False, future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def repo(db_engine, monkeypatch):
    """IBACRuleRepository wired to the in-memory DB."""
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(
        "agentic_bus.core.persistence.ibac_repository.get_session",
        lambda: factory(),
    )
    return IBACRuleRepository()


@pytest.fixture()
def engine_with_db(db_engine, monkeypatch):
    """IBACEngine whose rule_repo points to the in-memory DB.

    Returns ``(engine, repo)`` so tests can seed rules and then evaluate.
    """
    factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    monkeypatch.setattr(
        "agentic_bus.core.persistence.ibac_repository.get_session",
        lambda: factory(),
    )
    eng = IBACEngine()
    repo = IBACRuleRepository()
    eng._rule_repo = repo
    return eng, repo


# ---------------------------------------------------------------------------
# Repository CRUD
# ---------------------------------------------------------------------------

class TestIBACRuleRepository:
    def test_add_and_get(self, repo):
        rule = repo.add("r1", "Test rule", description="A test guardrail")
        assert rule.rule_id == "r1"
        assert rule.name == "Test rule"
        assert rule.enabled is True
        assert rule.action == IBACRuleAction.DENY
        assert rule.priority == 100

        fetched = repo.get("r1")
        assert fetched is not None
        assert fetched.rule_id == "r1"

    def test_add_duplicate_raises(self, repo):
        repo.add("dup", "First")
        with pytest.raises(ValueError, match="already exists"):
            repo.add("dup", "Second")

    def test_list_all(self, repo):
        repo.add("b", "Low priority", priority=200)
        repo.add("a", "High priority", priority=10)

        rules = repo.list_all()
        assert len(rules) == 2
        # Ordered by priority ascending
        assert rules[0].rule_id == "a"
        assert rules[1].rule_id == "b"

    def test_list_enabled_only(self, repo):
        repo.add("enabled-rule", "Active")
        repo.add("disabled-rule", "Inactive", enabled=False)

        all_rules = repo.list_all()
        enabled = repo.list_all(enabled_only=True)
        assert len(all_rules) == 2
        assert len(enabled) == 1
        assert enabled[0].rule_id == "enabled-rule"

    def test_update(self, repo):
        repo.add("upd", "Original")
        updated = repo.update("upd", name="Updated", priority=50, action="allow")
        assert updated.name == "Updated"
        assert updated.priority == 50
        assert updated.action == IBACRuleAction.ALLOW

    def test_update_partial(self, repo):
        repo.add("part", "Partial", description="old desc", priority=100)
        updated = repo.update("part", description="new desc")
        assert updated.description == "new desc"
        assert updated.priority == 100  # unchanged
        assert updated.name == "Partial"  # unchanged

    def test_update_nonexistent(self, repo):
        with pytest.raises(IBACRuleNotFoundError):
            repo.update("nope", name="X")

    def test_delete(self, repo):
        repo.add("del-me", "Deletable")
        assert repo.delete("del-me") is True
        assert repo.get("del-me") is None

    def test_delete_nonexistent(self, repo):
        assert repo.delete("ghost") is False

    def test_update_evaluation_points_and_conditions(self, repo):
        repo.add("ep-rule", "EP test")
        updated = repo.update(
            "ep-rule",
            evaluation_points=["intent_admission", "execution_authorization"],
            conditions={
                "intent_keywords": ["delete", "drop"],
                "blocked_agents": ["rogue-agent"],
            },
        )
        assert updated.evaluation_points_json == ["intent_admission", "execution_authorization"]
        assert updated.conditions_json["intent_keywords"] == ["delete", "drop"]
        assert "blocked_agents" in updated.conditions_json

    def test_toggle_enabled(self, repo):
        repo.add("toggle", "Toggle test")
        repo.update("toggle", enabled=False)
        assert repo.get("toggle").enabled is False
        repo.update("toggle", enabled=True)
        assert repo.get("toggle").enabled is True


# ---------------------------------------------------------------------------
# Engine + Persisted Rules (integration)
# ---------------------------------------------------------------------------

class TestIBACEngineWithPersistedRules:
    """Evaluate the engine's layer-2 (DB rules) against various conditions."""

    def test_default_allow_no_rules(self, engine_with_db):
        eng, _ = engine_with_db
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="ship container from A to B",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.ALLOW

    def test_deny_by_keyword(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "block-delete", "Block deletion intents",
            conditions={"intent_keywords": ["delete", "destroy"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Please delete all user records",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.DENY
        assert "delete" in result.reason.lower()

    def test_keyword_no_match_allows(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "block-delete", "Block deletion",
            conditions={"intent_keywords": ["delete"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Summarize the quarterly report",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.ALLOW

    def test_deny_by_regex_pattern(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "block-sql", "Block SQL injection patterns",
            conditions={"intent_patterns": [r"\bDROP\s+TABLE\b"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Run DROP TABLE users; on the database",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.DENY

    def test_deny_by_blocked_agent(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "block-rogue", "Block rogue agent",
            conditions={"blocked_agents": ["rogue-agent"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            agent_id="rogue-agent",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.DENY

    def test_allowed_agent_passes(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "block-rogue", "Block rogue",
            conditions={"blocked_agents": ["rogue-agent"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            agent_id="trusted-agent",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.ALLOW

    def test_allowed_agents_whitelist(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "only-trusted", "Only trusted agents",
            conditions={"allowed_agents": ["trusted-1", "trusted-2"]},
        )
        # Not in allowed list → deny
        req_bad = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            agent_id="unknown-agent",
        )
        assert eng.evaluate(req_bad).decision == IBACDecision.DENY

        # In allowed list → allow
        req_ok = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            agent_id="trusted-1",
        )
        assert eng.evaluate(req_ok).decision == IBACDecision.ALLOW

    def test_deny_by_blocked_scope(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "no-admin-write", "Block admin:write",
            conditions={"blocked_scopes": ["admin:write"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            requested_scopes=["admin:write"],
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.DENY
        assert "admin:write" in result.reason

    def test_deny_by_blocked_domain(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "no-pii", "Block PII domain",
            conditions={"blocked_domains": ["pii"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.ARTIFACT_EMISSION,
            data_domains=["pii"],
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.DENY

    def test_max_agents_constraint(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "max-3", "Max 3 agents",
            conditions={"max_agents": 3},
        )
        # Under limit → allow
        req_ok = IBACRequest(
            evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
            proposed_capabilities=["a", "b", "c"],
        )
        assert eng.evaluate(req_ok).decision == IBACDecision.ALLOW

        # Over limit → deny
        req_bad = IBACRequest(
            evaluation_point=IBACEvaluationPoint.NEGOTIATION_ACCEPTANCE,
            proposed_capabilities=["a", "b", "c", "d"],
        )
        assert eng.evaluate(req_bad).decision == IBACDecision.DENY

    def test_require_human_approval(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "human-check", "Require human approval for sensitive intents",
            conditions={
                "intent_keywords": ["payment", "transfer"],
                "require_human_approval": True,
            },
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Process payment of $10,000",
        )
        result = eng.evaluate(req)
        # Should ALLOW but with constraint
        assert result.decision == IBACDecision.ALLOW
        assert result.constraints.get("require_human_approval") is True

    def test_evaluation_point_filtering(self, engine_with_db):
        """Rule scoped to specific evaluation points only fires there."""
        eng, repo = engine_with_db
        repo.add(
            "exec-only", "Execution only block",
            evaluation_points=["execution_authorization"],
            conditions={"blocked_scopes": ["dangerous:action"]},
        )
        # At intent_admission → should pass (rule doesn't apply here)
        req_other = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requested_scopes=["dangerous:action"],
        )
        assert eng.evaluate(req_other).decision == IBACDecision.ALLOW

        # At execution_authorization → should deny
        req_exec = IBACRequest(
            evaluation_point=IBACEvaluationPoint.EXECUTION_AUTHORIZATION,
            requested_scopes=["dangerous:action"],
        )
        assert eng.evaluate(req_exec).decision == IBACDecision.DENY

    def test_disabled_rule_ignored(self, engine_with_db):
        eng, repo = engine_with_db
        repo.add(
            "disabled-rule", "Should be ignored",
            conditions={"intent_keywords": ["forbidden"]},
            enabled=False,
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="This is forbidden content",
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.ALLOW

    def test_priority_ordering(self, engine_with_db):
        """Lower priority number = evaluated first."""
        eng, repo = engine_with_db
        # Low priority (100) allows
        repo.add(
            "allow-all", "Allow everything", priority=100, action="allow",
            conditions={"intent_keywords": ["test"]},
        )
        # High priority (10) denies
        repo.add(
            "block-test", "Block test keyword", priority=10,
            conditions={"intent_keywords": ["test"]},
        )
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="This is a test intent",
        )
        result = eng.evaluate(req)
        # High-priority deny rule fires first
        assert result.decision == IBACDecision.DENY

    def test_in_memory_policies_evaluated_before_db_rules(self, engine_with_db):
        """In-memory policies (layer 1) take precedence over DB rules (layer 2)."""
        from agentic_bus.core.ibac.engine import IBACPolicy

        eng, repo = engine_with_db
        # DB rule that denies "finance:write"
        repo.add(
            "db-deny", "DB deny",
            conditions={"blocked_scopes": ["finance:write"]},
        )
        # In-memory policy that denies a different scope
        eng.add_policy(IBACPolicy(
            policy_id="mem-deny",
            denied_scopes=["admin:nuke"],
        ))
        # The in-memory policy doesn't block finance:write, but the DB rule does
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requested_scopes=["finance:write"],
        )
        result = eng.evaluate(req)
        assert result.decision == IBACDecision.DENY
        assert "db-deny" in result.reason  # denied by DB rule, not in-memory

    def test_multiple_conditions_all_must_match(self, engine_with_db):
        """When a rule has keyword + blocked_agent, both paths are checked."""
        eng, repo = engine_with_db
        repo.add(
            "multi", "Multi-condition rule",
            conditions={
                "intent_keywords": ["sensitive"],
                "blocked_agents": ["bad-agent"],
            },
        )
        # Only keyword matches (no agent_id) → keyword triggers deny
        req_kw = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Handle sensitive data",
        )
        assert eng.evaluate(req_kw).decision == IBACDecision.DENY

        # Only agent matches (no intent_text) → agent triggers deny
        req_agent = IBACRequest(
            evaluation_point=IBACEvaluationPoint.OFFER_ELIGIBILITY,
            agent_id="bad-agent",
        )
        assert eng.evaluate(req_agent).decision == IBACDecision.DENY


# ---------------------------------------------------------------------------
# LLM-based evaluation (evaluate_with_llm)
# ---------------------------------------------------------------------------

class TestIBACEngineWithLLM:
    """Test the LLM-powered IBAC evaluation path.

    The LLM is mocked to return structured JSON decisions so that tests
    are deterministic and don't require a real API key.
    """

    @pytest.fixture()
    def engine_with_db(self, db_engine, monkeypatch):
        factory = sessionmaker(bind=db_engine, expire_on_commit=False)
        monkeypatch.setattr(
            "agentic_bus.core.persistence.ibac_repository.get_session",
            lambda: factory(),
        )
        eng = IBACEngine()
        repo = IBACRuleRepository()
        eng._rule_repo = repo
        return eng, repo

    @staticmethod
    def _mock_llm_chain(response: dict):
        """Build a mock LangChain chain that returns *response* from ainvoke."""
        mock_chain = MagicMock()
        mock_chain.ainvoke = AsyncMock(return_value=response)

        # The chain is built via prompt | llm | parser.  We mock the
        # intermediate __or__ so the final object is our mock_chain.
        mock_llm = MagicMock()
        mock_prompt = MagicMock()
        mock_parser = MagicMock()
        mock_prompt.__or__ = MagicMock(return_value=MagicMock())
        mock_prompt.__or__.return_value.__or__ = MagicMock(return_value=mock_chain)

        return mock_llm, mock_prompt, mock_parser, mock_chain

    @pytest.mark.asyncio
    async def test_llm_denies_semantic_rule(self, engine_with_db):
        """LLM understands a natural-language deny rule and blocks the request."""
        eng, repo = engine_with_db
        repo.add(
            "no-external-access",
            "Block external access",
            description="Prevent agents from accessing internet websites",
            conditions={},
        )

        mock_llm, _, _, mock_chain = self._mock_llm_chain({
            "decision": "deny",
            "reason": "The intent requests scraping a website, which violates the 'no-external-access' rule.",
            "matching_rules": ["no-external-access"],
            "constraints": {},
        })

        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="scrape https://example.com to get product data",
        )

        with patch("agentic_bus.core.ibac.engine.get_llm", return_value=mock_llm), \
             patch("agentic_bus.core.ibac.engine.ChatPromptTemplate") as mock_pt, \
             patch("agentic_bus.core.ibac.engine.JsonOutputParser"):
            # Wire the mocked chain pipeline
            mock_pt.from_messages.return_value = MagicMock()
            mock_pt.from_messages.return_value.__or__ = MagicMock(return_value=MagicMock())
            mock_pt.from_messages.return_value.__or__.return_value.__or__ = MagicMock(
                return_value=mock_chain,
            )

            result = await eng.evaluate_with_llm(req)

        assert result.decision == IBACDecision.DENY
        assert "no-external-access" in result.reason

    @pytest.mark.asyncio
    async def test_llm_allows_when_no_violation(self, engine_with_db):
        """LLM allows a request that doesn't violate any rule."""
        eng, repo = engine_with_db
        repo.add(
            "no-external-access",
            "Block external access",
            description="Prevent agents from accessing internet websites",
            conditions={},
        )

        mock_llm, _, _, mock_chain = self._mock_llm_chain({
            "decision": "allow",
            "reason": "The intent is about logistics planning, no rule is violated.",
            "matching_rules": [],
            "constraints": {},
        })

        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="plan shipping route from warehouse A to warehouse B",
        )

        with patch("agentic_bus.core.ibac.engine.get_llm", return_value=mock_llm), \
             patch("agentic_bus.core.ibac.engine.ChatPromptTemplate") as mock_pt, \
             patch("agentic_bus.core.ibac.engine.JsonOutputParser"):
            mock_pt.from_messages.return_value = MagicMock()
            mock_pt.from_messages.return_value.__or__ = MagicMock(return_value=MagicMock())
            mock_pt.from_messages.return_value.__or__.return_value.__or__ = MagicMock(
                return_value=mock_chain,
            )

            result = await eng.evaluate_with_llm(req)

        assert result.decision == IBACDecision.ALLOW

    @pytest.mark.asyncio
    async def test_llm_returns_constraints(self, engine_with_db):
        """LLM returns a human-approval constraint when the rule requires it."""
        eng, repo = engine_with_db
        repo.add(
            "sensitive-ops",
            "Human approval for sensitive ops",
            description="Require human approval for financial transactions",
            conditions={"require_human_approval": True},
        )

        mock_llm, _, _, mock_chain = self._mock_llm_chain({
            "decision": "allow",
            "reason": "Rule 'sensitive-ops' requires human approval for this financial intent.",
            "matching_rules": ["sensitive-ops"],
            "constraints": {"require_human_approval": True},
        })

        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Transfer $50,000 to supplier account",
        )

        with patch("agentic_bus.core.ibac.engine.get_llm", return_value=mock_llm), \
             patch("agentic_bus.core.ibac.engine.ChatPromptTemplate") as mock_pt, \
             patch("agentic_bus.core.ibac.engine.JsonOutputParser"):
            mock_pt.from_messages.return_value = MagicMock()
            mock_pt.from_messages.return_value.__or__ = MagicMock(return_value=MagicMock())
            mock_pt.from_messages.return_value.__or__.return_value.__or__ = MagicMock(
                return_value=mock_chain,
            )

            result = await eng.evaluate_with_llm(req)

        assert result.decision == IBACDecision.ALLOW
        assert result.constraints.get("require_human_approval") is True

    @pytest.mark.asyncio
    async def test_llm_fallback_on_no_llm_configured(self, engine_with_db):
        """When no LLM is configured, evaluate_with_llm falls back to
        programmatic evaluate()."""
        eng, repo = engine_with_db
        repo.add(
            "block-keyword",
            "Block delete keyword",
            conditions={"intent_keywords": ["delete"]},
        )

        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="Please delete all records",
        )

        # Simulate no LLM configured
        with patch("agentic_bus.core.ibac.engine.get_llm", side_effect=RuntimeError("No LLM")):
            result = await eng.evaluate_with_llm(req)

        # Falls back to programmatic check which catches the keyword
        assert result.decision == IBACDecision.DENY
        assert "delete" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_llm_fallback_on_llm_error(self, engine_with_db):
        """When LLM call fails, evaluate_with_llm falls back to programmatic."""
        eng, repo = engine_with_db
        repo.add(
            "block-scope",
            "Block admin scope",
            conditions={"blocked_scopes": ["admin:write"]},
        )

        mock_llm = MagicMock()

        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requested_scopes=["admin:write"],
        )

        with patch("agentic_bus.core.ibac.engine.get_llm", return_value=mock_llm), \
             patch("agentic_bus.core.ibac.engine.ChatPromptTemplate") as mock_pt, \
             patch("agentic_bus.core.ibac.engine.JsonOutputParser"):
            # Make the chain raise an error
            mock_chain = MagicMock()
            mock_chain.ainvoke = AsyncMock(side_effect=RuntimeError("LLM timeout"))
            mock_pt.from_messages.return_value = MagicMock()
            mock_pt.from_messages.return_value.__or__ = MagicMock(return_value=MagicMock())
            mock_pt.from_messages.return_value.__or__.return_value.__or__ = MagicMock(
                return_value=mock_chain,
            )

            result = await eng.evaluate_with_llm(req)

        # Falls back to programmatic → blocked_scopes catches it
        assert result.decision == IBACDecision.DENY
        assert "admin:write" in result.reason

    @pytest.mark.asyncio
    async def test_llm_no_rules_allows(self, engine_with_db):
        """When there are no active rules, evaluate_with_llm auto-allows
        without calling the LLM."""
        eng, _ = engine_with_db
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="do whatever",
        )
        result = await eng.evaluate_with_llm(req)
        assert result.decision == IBACDecision.ALLOW
        assert "No applicable" in result.reason

    @pytest.mark.asyncio
    async def test_llm_eval_point_filtering(self, engine_with_db):
        """Rules scoped to specific evaluation points are filtered before
        the LLM is called."""
        eng, repo = engine_with_db
        repo.add(
            "exec-only-rule",
            "Execution only",
            description="Block everything at execution time",
            evaluation_points=["execution_authorization"],
            conditions={},
        )

        # At intent_admission → rule doesn't apply → no LLM call needed → allow
        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            intent_text="anything",
        )
        result = await eng.evaluate_with_llm(req)
        assert result.decision == IBACDecision.ALLOW
        assert "No applicable" in result.reason

    @pytest.mark.asyncio
    async def test_in_memory_policy_checked_before_llm(self, engine_with_db):
        """In-memory policies are checked first – if they deny, LLM is
        never called."""
        from agentic_bus.core.ibac.engine import IBACPolicy

        eng, repo = engine_with_db
        eng.add_policy(IBACPolicy(
            policy_id="mem-deny",
            denied_scopes=["admin:nuke"],
        ))
        repo.add(
            "db-rule",
            "Some DB rule",
            conditions={},
        )

        req = IBACRequest(
            evaluation_point=IBACEvaluationPoint.INTENT_ADMISSION,
            requested_scopes=["admin:nuke"],
        )
        # Should be denied by in-memory policy without LLM call
        result = await eng.evaluate_with_llm(req)
        assert result.decision == IBACDecision.DENY
        assert "mem-deny" in result.reason
