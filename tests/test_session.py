"""Tests for the session manager."""

from agentic_bus.core.session.manager import (
    SessionManager,
    SessionPhase,
)


class TestSessionManager:
    """Verify session lifecycle and dissolution semantics."""

    def test_create_session(self):
        mgr = SessionManager()
        session = mgr.create("user-1", "oidc-sub-1")
        assert session.session_id
        assert session.requester_id == "user-1"
        assert session.phase == SessionPhase.CREATED
        assert mgr.count == 1

    def test_transition(self):
        mgr = SessionManager()
        session = mgr.create("user-1")
        mgr.transition(session.session_id, SessionPhase.NEGOTIATION)
        assert mgr.get(session.session_id).phase == SessionPhase.NEGOTIATION

    def test_transition_to_awaiting_approval(self):
        """Verify the AWAITING_APPROVAL phase exists and can be transitioned to."""
        mgr = SessionManager()
        session = mgr.create("user-1")
        mgr.transition(session.session_id, SessionPhase.NEGOTIATION)
        mgr.transition(session.session_id, SessionPhase.AWAITING_APPROVAL)
        assert mgr.get(session.session_id).phase == SessionPhase.AWAITING_APPROVAL

    def test_dissolve_removes_session(self):
        """Per Agentic Bus Invariant II (§5.1.2) – dissolution destroys all state."""
        mgr = SessionManager()
        session = mgr.create("user-1")
        sid = session.session_id

        snapshot = mgr.dissolve(sid)
        assert snapshot is not None
        assert snapshot.phase == SessionPhase.DISSOLVED
        assert snapshot.dissolved_at is not None

        # Session must not be retrievable after dissolution (R_c = 0)
        assert mgr.get(sid) is None
        assert mgr.count == 0

    def test_dissolve_unknown_session(self):
        mgr = SessionManager()
        assert mgr.dissolve("nonexistent") is None

    def test_active_sessions(self):
        mgr = SessionManager()
        s1 = mgr.create("user-1")
        _s2 = mgr.create("user-2")
        mgr.dissolve(s1.session_id)
        active = mgr.active_sessions()
        assert len(active) == 1
        assert active[0].requester_id == "user-2"
