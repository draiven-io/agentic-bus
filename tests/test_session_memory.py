"""Tests for session-scoped shared memory."""


from agentic_bus.core.session.memory import (
    InMemoryBackend,
    MemoryAccessPolicy,
    MemoryWriteRequest,
    SessionMemory,
)


# -----------------------------------------------------------------------
# InMemoryBackend
# -----------------------------------------------------------------------


class TestInMemoryBackend:
    """Verify the low-level dict-backed storage layer."""

    def test_put_and_get(self):
        backend = InMemoryBackend()
        entry = backend.put("shared.foo", "bar", "agent-a")
        assert entry.key == "shared.foo"
        assert entry.value == "bar"
        assert entry.written_by == "agent-a"
        assert entry.version == 1

        retrieved = backend.get("shared.foo")
        assert retrieved is not None
        assert retrieved.value == "bar"

    def test_put_increments_version(self):
        backend = InMemoryBackend()
        backend.put("k", "v1", "a")
        entry = backend.put("k", "v2", "b")
        assert entry.version == 2
        assert entry.value == "v2"
        assert entry.written_by == "b"

    def test_get_missing_key(self):
        backend = InMemoryBackend()
        assert backend.get("nonexistent") is None

    def test_get_by_pattern_star(self):
        backend = InMemoryBackend()
        backend.put("shared.alpha", 1, "a")
        backend.put("shared.beta", 2, "a")
        backend.put("private.gamma", 3, "b")

        matches = backend.get_by_pattern("shared.*")
        assert len(matches) == 2
        assert "shared.alpha" in matches
        assert "shared.beta" in matches

    def test_get_by_pattern_exact(self):
        backend = InMemoryBackend()
        backend.put("shared.alpha", 1, "a")
        backend.put("shared.beta", 2, "a")

        matches = backend.get_by_pattern("shared.alpha")
        assert len(matches) == 1
        assert "shared.alpha" in matches

    def test_delete(self):
        backend = InMemoryBackend()
        backend.put("k", "v", "a")
        assert backend.delete("k") is True
        assert backend.get("k") is None
        assert backend.delete("k") is False

    def test_keys(self):
        backend = InMemoryBackend()
        backend.put("a", 1, "x")
        backend.put("b", 2, "x")
        assert sorted(backend.keys()) == ["a", "b"]

    def test_clear(self):
        backend = InMemoryBackend()
        backend.put("a", 1, "x")
        backend.put("b", 2, "x")
        backend.clear()
        assert backend.keys() == []

    def test_snapshot(self):
        backend = InMemoryBackend()
        backend.put("a", 1, "x")
        backend.put("b", "hello", "y")
        snap = backend.snapshot()
        assert snap == {"a": 1, "b": "hello"}


# -----------------------------------------------------------------------
# SessionMemory – access control
# -----------------------------------------------------------------------


class TestSessionMemoryAccessControl:
    """Verify read/write policies are enforced."""

    def _make_memory_with_policies(self) -> SessionMemory:
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="researcher",
                read_patterns=["shared.*"],
                write_patterns=["shared.research_findings", "researcher.*"],
            )
        )
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="analyst",
                read_patterns=["shared.*", "researcher.*"],
                write_patterns=["shared.analysis", "analyst.*"],
            )
        )
        return mem

    def test_write_allowed(self):
        mem = self._make_memory_with_policies()
        assert mem.write("shared.research_findings", "data", "researcher") is True
        assert mem.coordinator_read("shared.research_findings") == "data"

    def test_write_denied(self):
        mem = self._make_memory_with_policies()
        # researcher cannot write to shared.analysis
        assert mem.write("shared.analysis", "hack", "researcher") is False
        assert mem.coordinator_read("shared.analysis") is None

    def test_write_own_namespace(self):
        mem = self._make_memory_with_policies()
        assert mem.write("researcher.notes", "some notes", "researcher") is True
        assert mem.coordinator_read("researcher.notes") == "some notes"

    def test_write_other_namespace_denied(self):
        mem = self._make_memory_with_policies()
        # researcher cannot write to analyst's namespace
        assert mem.write("analyst.secret", "bad", "researcher") is False

    def test_read_allowed(self):
        mem = self._make_memory_with_policies()
        mem.coordinator_write("shared.data", "hello")
        assert mem.read("shared.data", "researcher") == "hello"

    def test_read_denied(self):
        mem = self._make_memory_with_policies()
        mem.coordinator_write("analyst.private", "secret")
        # researcher can't read analyst's namespace
        assert mem.read("analyst.private", "researcher") is None

    def test_read_cross_namespace_allowed(self):
        mem = self._make_memory_with_policies()
        mem.coordinator_write("researcher.notes", "hello")
        # analyst CAN read researcher's namespace
        assert mem.read("researcher.notes", "analyst") == "hello"

    def test_no_policy_denies_all(self):
        mem = SessionMemory()
        mem.coordinator_write("shared.data", "hello")
        # Unknown agent has no policy → denied
        assert mem.read("shared.data", "unknown_agent") is None
        assert mem.write("shared.data", "overwrite", "unknown_agent") is False


# -----------------------------------------------------------------------
# SessionMemory – snapshots
# -----------------------------------------------------------------------


class TestSessionMemorySnapshots:
    """Verify filtered snapshot generation for WS envelope injection."""

    def test_snapshot_for_agent_filters_by_policy(self):
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="analyst",
                read_patterns=["shared.*", "researcher.*"],
                write_patterns=["analyst.*"],
            )
        )
        mem.coordinator_write("shared.intent_text", "Analyse X")
        mem.coordinator_write("researcher.findings", "Found Y")
        mem.coordinator_write("private.secret", "top-secret")

        snap = mem.snapshot_for_agent("analyst")
        assert "shared.intent_text" in snap
        assert "researcher.findings" in snap
        assert "private.secret" not in snap

    def test_snapshot_for_unknown_agent_is_empty(self):
        mem = SessionMemory()
        mem.coordinator_write("shared.data", "hello")
        assert mem.snapshot_for_agent("nonexistent") == {}

    def test_full_snapshot_is_unfiltered(self):
        mem = SessionMemory()
        mem.coordinator_write("a", 1)
        mem.coordinator_write("b", 2)
        assert mem.full_snapshot() == {"a": 1, "b": 2}


# -----------------------------------------------------------------------
# SessionMemory – coordinator access
# -----------------------------------------------------------------------


class TestSessionMemoryCoordinator:
    """Verify coordinator bypass and lifecycle operations."""

    def test_coordinator_write_bypasses_policy(self):
        mem = SessionMemory()
        # No policies set — coordinator can still write
        mem.coordinator_write("anything", "value")
        assert mem.coordinator_read("anything") == "value"

    def test_coordinator_read_missing_key(self):
        mem = SessionMemory()
        assert mem.coordinator_read("nonexistent") is None

    def test_clear_destroys_everything(self):
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="agent-a",
                read_patterns=["shared.*"],
                write_patterns=["shared.*"],
            )
        )
        mem.coordinator_write("shared.data", "hello")
        mem.write("shared.more", "world", "agent-a")

        mem.clear()
        assert mem.full_snapshot() == {}
        assert mem.get_policy("agent-a") is None


# -----------------------------------------------------------------------
# SessionMemory – batch writes
# -----------------------------------------------------------------------


class TestSessionMemoryBatchWrites:
    """Verify batch write operations from agent COMPLETE payloads."""

    def test_batch_write_mixed_results(self):
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="agent-a",
                read_patterns=["shared.*"],
                write_patterns=["shared.allowed", "agent-a.*"],
            )
        )

        writes = [
            MemoryWriteRequest(key="shared.allowed", value="ok"),
            MemoryWriteRequest(key="shared.forbidden", value="nope"),
            MemoryWriteRequest(key="agent-a.notes", value="my notes"),
        ]
        results = mem.write_batch(writes, "agent-a")
        assert results == [True, False, True]

        assert mem.coordinator_read("shared.allowed") == "ok"
        assert mem.coordinator_read("shared.forbidden") is None
        assert mem.coordinator_read("agent-a.notes") == "my notes"


# -----------------------------------------------------------------------
# SessionMemory – audit trail
# -----------------------------------------------------------------------


class TestSessionMemoryAudit:
    """Verify audit logging of memory operations."""

    def test_audit_records_writes_and_reads(self):
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="a",
                read_patterns=["shared.*"],
                write_patterns=["shared.*"],
            )
        )
        mem.write("shared.x", 1, "a")
        mem.read("shared.x", "a")

        trail = mem.audit_trail
        assert len(trail) == 2
        assert trail[0].operation == "write"
        assert trail[0].allowed is True
        assert trail[1].operation == "read"
        assert trail[1].allowed is True

    def test_audit_records_denials(self):
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="a",
                read_patterns=[],
                write_patterns=[],
            )
        )
        mem.write("shared.x", 1, "a")
        mem.read("shared.x", "a")

        trail = mem.audit_trail
        assert len(trail) == 2
        assert all(not e.allowed for e in trail)

    def test_audit_summary(self):
        mem = SessionMemory()
        mem.set_policy(
            MemoryAccessPolicy(
                agent_id="a",
                read_patterns=["shared.*"],
                write_patterns=["shared.ok"],
            )
        )
        mem.write("shared.ok", 1, "a")
        mem.write("shared.nope", 2, "a")  # denied
        mem.read("shared.ok", "a")

        summary = mem.audit_summary()
        assert summary["writes"] == 1
        assert summary["reads"] == 1
        assert summary["denied"] == 1
        assert summary["total_operations"] == 3


# -----------------------------------------------------------------------
# NegotiationEngine.infer_memory_policies
# -----------------------------------------------------------------------


class TestInferMemoryPolicies:
    """Verify auto-inference of memory policies from composition plans."""

    def test_infer_sequential_plan(self):
        from agentic_bus.coordinator.negotiation.engine import NegotiationEngine

        plan = {
            "steps": [
                {"agent_id": "researcher", "capability_id": "web_search"},
                {"agent_id": "analyst", "capability_id": "data_analysis"},
                {"agent_id": "writer", "capability_id": "report_writing"},
            ],
            "viable": True,
        }

        policies = NegotiationEngine.infer_memory_policies(plan)
        assert len(policies) == 3

        # Researcher (step 0): reads shared.*, writes shared.web_search & researcher.*
        p0 = policies[0]
        assert p0["agent_id"] == "researcher"
        assert "shared.*" in p0["read_patterns"]
        assert "shared.web_search" in p0["write_patterns"]
        assert "researcher.*" in p0["write_patterns"]
        # No prior steps → no extra read patterns beyond shared.*
        assert len(p0["read_patterns"]) == 1

        # Analyst (step 1): can also read researcher.*
        p1 = policies[1]
        assert "researcher.*" in p1["read_patterns"]
        assert "shared.data_analysis" in p1["write_patterns"]

        # Writer (step 2): can read researcher.* and analyst.*
        p2 = policies[2]
        assert "researcher.*" in p2["read_patterns"]
        assert "analyst.*" in p2["read_patterns"]

    def test_infer_explicit_overrides(self):
        from agentic_bus.coordinator.negotiation.engine import NegotiationEngine

        plan = {
            "steps": [
                {
                    "agent_id": "custom",
                    "capability_id": "x",
                    "memory_read": ["specific.key"],
                    "memory_write": ["specific.output"],
                },
            ],
            "viable": True,
        }

        policies = NegotiationEngine.infer_memory_policies(plan)
        assert len(policies) == 1
        assert policies[0]["read_patterns"] == ["specific.key"]
        assert policies[0]["write_patterns"] == ["specific.output"]

    def test_infer_empty_plan(self):
        from agentic_bus.coordinator.negotiation.engine import NegotiationEngine

        policies = NegotiationEngine.infer_memory_policies({"steps": []})
        assert policies == []

    def test_infer_same_agent_multiple_steps(self):
        from agentic_bus.coordinator.negotiation.engine import NegotiationEngine

        plan = {
            "steps": [
                {"agent_id": "multi", "capability_id": "cap_a"},
                {"agent_id": "multi", "capability_id": "cap_b"},
            ],
            "viable": True,
        }

        policies = NegotiationEngine.infer_memory_policies(plan)
        assert len(policies) == 2
        # Second invocation should NOT add multi.* to its own read patterns
        # (it's the same agent, no self-reference needed)
        p1 = policies[1]
        assert "multi.*" not in p1["read_patterns"]


# -----------------------------------------------------------------------
# Integration: SessionState has memory
# -----------------------------------------------------------------------


class TestSessionStateMemoryIntegration:
    """Verify that SessionState exposes a usable SessionMemory instance."""

    def test_session_state_has_memory(self):
        from agentic_bus.core.session.manager import SessionState

        session = SessionState()
        assert isinstance(session.memory, SessionMemory)

    def test_memory_survives_session_lifecycle(self):
        from agentic_bus.core.session.manager import SessionManager

        mgr = SessionManager()
        session = mgr.create("user-1")

        # Write to memory
        session.memory.coordinator_write("shared.test", "hello")
        assert session.memory.coordinator_read("shared.test") == "hello"

        # Memory persists while session is alive
        retrieved = mgr.get(session.session_id)
        assert retrieved.memory.coordinator_read("shared.test") == "hello"

    def test_memory_destroyed_on_dissolution(self):
        from agentic_bus.core.session.manager import SessionManager

        mgr = SessionManager()
        session = mgr.create("user-1")
        session.memory.coordinator_write("shared.data", "important")

        # Dissolve → session object is removed; memory was on it
        snapshot = mgr.dissolve(session.session_id)
        # The snapshot still has the data (for archival)
        assert snapshot.memory.coordinator_read("shared.data") == "important"

        # But the session is gone from the manager
        assert mgr.get(session.session_id) is None
