"""Tests for per-agent performance statistics (record_execution, running averages)."""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from agentic_bus.core.persistence.models import (
    Base,
    ManagedAgent,
    PersistentAgent,
    AgentStatus,
)
from agentic_bus.core.persistence.managed_agent_repository import ManagedAgentRepository
from agentic_bus.core.persistence.repository import AgentRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_engine():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture()
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, expire_on_commit=False)


# -- managed agent fixtures ------------------------------------------------


@pytest.fixture()
def _patch_managed_session(session_factory):
    with patch(
        "agentic_bus.core.persistence.managed_agent_repository.get_session",
        side_effect=lambda: session_factory(),
    ):
        yield


@pytest.fixture()
def managed_repo(_patch_managed_session):
    return ManagedAgentRepository()


@pytest.fixture()
def managed_agent(managed_repo) -> ManagedAgent:
    """Create a simple managed agent for testing."""
    return managed_repo.create(
        agent_id="stats-managed-01",
        name="Stats Agent",
        role="Analyst",
        goal="Analyse data",
        backstory="A tireless data analyst.",
    )


# -- persistent agent fixtures ---------------------------------------------


@pytest.fixture()
def _patch_persistent_session(session_factory):
    with patch(
        "agentic_bus.core.persistence.repository.get_session",
        side_effect=lambda: session_factory(),
    ):
        yield


@pytest.fixture()
def persistent_repo(_patch_persistent_session):
    return AgentRepository()


@pytest.fixture()
def persistent_agent(persistent_repo, session_factory) -> PersistentAgent:
    """Create a persistent agent directly via the session."""
    session = session_factory()
    agent = PersistentAgent(
        agent_id="stats-persistent-01",
        public_key_pem="fake-pem",
        status=AgentStatus.APPROVED,
        semantic_description="Test persistent agent",
        version="1.0",
    )
    session.add(agent)
    session.commit()
    return agent


# ---------------------------------------------------------------------------
# Managed Agent: record_execution
# ---------------------------------------------------------------------------


class TestManagedAgentStats:
    """Test record_execution on ManagedAgentRepository."""

    def test_first_execution_sets_stats(self, managed_repo, managed_agent):
        managed_repo.record_execution("stats-managed-01", quality_score=8.0, latency_ms=120.0)

        agent = managed_repo.get("stats-managed-01")
        assert agent.total_executions == 1
        assert math.isclose(agent.current_score, 8.0)
        assert math.isclose(agent.mean_latency_ms, 120.0)
        assert agent.last_execution_at is not None

    def test_running_average_two_executions(self, managed_repo, managed_agent):
        managed_repo.record_execution("stats-managed-01", quality_score=6.0, latency_ms=100.0)
        managed_repo.record_execution("stats-managed-01", quality_score=10.0, latency_ms=200.0)

        agent = managed_repo.get("stats-managed-01")
        assert agent.total_executions == 2
        # mean of 6 and 10 = 8
        assert math.isclose(agent.current_score, 8.0, abs_tol=0.01)
        # mean of 100 and 200 = 150
        assert math.isclose(agent.mean_latency_ms, 150.0, abs_tol=0.01)

    def test_running_average_three_executions(self, managed_repo, managed_agent):
        scores = [7.0, 9.0, 5.0]
        latencies = [80.0, 120.0, 200.0]
        for s, lat in zip(scores, latencies):
            managed_repo.record_execution("stats-managed-01", quality_score=s, latency_ms=lat)

        agent = managed_repo.get("stats-managed-01")
        assert agent.total_executions == 3
        assert math.isclose(agent.current_score, sum(scores) / 3, abs_tol=0.01)
        assert math.isclose(agent.mean_latency_ms, sum(latencies) / 3, abs_tol=0.01)

    def test_record_execution_nonexistent_agent_is_noop(self, managed_repo, managed_agent):
        """Calling record_execution for a non-existent agent should not raise."""
        managed_repo.record_execution("no-such-agent", quality_score=5.0, latency_ms=50.0)

    def test_stats_default_to_zero(self, managed_agent, session_factory):
        """Freshly created agent has zero stats."""
        session = session_factory()
        agent = session.get(ManagedAgent, managed_agent.id)
        assert agent.total_executions == 0
        assert agent.current_score == 0.0
        assert agent.mean_latency_ms == 0.0
        assert agent.last_execution_at is None


# ---------------------------------------------------------------------------
# Persistent Agent: record_execution
# ---------------------------------------------------------------------------


class TestPersistentAgentStats:
    """Test record_execution on AgentRepository."""

    def test_first_execution_sets_stats(self, persistent_repo, persistent_agent):
        persistent_repo.record_execution("stats-persistent-01", quality_score=7.5, latency_ms=200.0)

        # Read back through a fresh session
        agent = persistent_repo.get("stats-persistent-01")
        assert agent.total_executions == 1
        assert math.isclose(agent.current_score, 7.5)
        assert math.isclose(agent.mean_latency_ms, 200.0)
        assert agent.last_execution_at is not None

    def test_running_average_two_executions(self, persistent_repo, persistent_agent):
        persistent_repo.record_execution("stats-persistent-01", quality_score=4.0, latency_ms=300.0)
        persistent_repo.record_execution("stats-persistent-01", quality_score=8.0, latency_ms=100.0)

        agent = persistent_repo.get("stats-persistent-01")
        assert agent.total_executions == 2
        assert math.isclose(agent.current_score, 6.0, abs_tol=0.01)
        assert math.isclose(agent.mean_latency_ms, 200.0, abs_tol=0.01)

    def test_running_average_five_executions(self, persistent_repo, persistent_agent):
        scores = [3.0, 5.0, 7.0, 9.0, 6.0]
        latencies = [100.0, 200.0, 150.0, 80.0, 170.0]
        for s, lat in zip(scores, latencies):
            persistent_repo.record_execution("stats-persistent-01", quality_score=s, latency_ms=lat)

        agent = persistent_repo.get("stats-persistent-01")
        assert agent.total_executions == 5
        assert math.isclose(agent.current_score, sum(scores) / 5, abs_tol=0.01)
        assert math.isclose(agent.mean_latency_ms, sum(latencies) / 5, abs_tol=0.01)

    def test_record_execution_nonexistent_agent_is_noop(self, persistent_repo, persistent_agent):
        persistent_repo.record_execution("ghost-agent", quality_score=5.0, latency_ms=50.0)

    def test_stats_default_to_zero(self, persistent_agent, session_factory):
        """Freshly created agent has zero stats."""
        session = session_factory()
        agent = session.get(PersistentAgent, "stats-persistent-01")
        assert agent.total_executions == 0
        assert agent.current_score == 0.0
        assert agent.mean_latency_ms == 0.0
        assert agent.last_execution_at is None


# ---------------------------------------------------------------------------
# DTO serialisation
# ---------------------------------------------------------------------------


class TestStatsSerialization:
    """Verify serializers include stats fields in DTOs."""

    def test_managed_agent_dto_includes_stats(self, managed_repo, managed_agent):
        from agentic_bus.coordinator.admin.serializers import managed_agent_to_dto

        managed_repo.record_execution("stats-managed-01", quality_score=9.0, latency_ms=50.0)
        agent = managed_repo.get("stats-managed-01")
        dto = managed_agent_to_dto(agent)

        assert dto.total_executions == 1
        assert math.isclose(dto.current_score, 9.0)
        assert math.isclose(dto.mean_latency_ms, 50.0)
        assert dto.last_execution_at is not None

    def test_persistent_agent_dto_includes_stats(self, persistent_repo, persistent_agent):
        from agentic_bus.coordinator.admin.serializers import persistent_agent_to_dto

        persistent_repo.record_execution("stats-persistent-01", quality_score=6.0, latency_ms=300.0)
        agent = persistent_repo.get("stats-persistent-01")
        dto = persistent_agent_to_dto(agent)

        assert dto.total_executions == 1
        assert math.isclose(dto.current_score, 6.0)
        assert math.isclose(dto.mean_latency_ms, 300.0)
        assert dto.last_execution_at is not None

    def test_dto_defaults_for_fresh_agent(self, managed_repo, managed_agent):
        from agentic_bus.coordinator.admin.serializers import managed_agent_to_dto

        dto = managed_agent_to_dto(managed_agent)
        assert dto.total_executions == 0
        assert dto.current_score == 0.0
        assert dto.mean_latency_ms == 0.0
        assert dto.last_execution_at is None
