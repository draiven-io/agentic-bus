"""Check whether an agent implementation conforms to the Liquid Interfaces Protocol.

A specification only becomes a standard when a second implementation can be
built from it and shown to interoperate. Until then "LIP-compliant" is an
assertion nobody can check.

This suite drives a candidate agent over a real WebSocket and reports, per
requirement, whether it behaved as the specification says it must. It speaks
only the protocol, so the agent under test can be written in any language:

    agbus conformance --port 9100

then point the agent at the printed URI. A Python agent can also be driven
in-process, which is how this codebase tests its own SDK.

Requirements are graded. A **MUST** failure means the implementation is not
conformant. A **SHOULD** failure is reported but does not fail the run — the
specification permits deviation where an implementer has reason.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from agentic_bus.core.protocol.envelope import (
    LIP_PROTOCOL_VERSION,
    PAYLOAD_TYPES,
    MessageType,
)
from agentic_bus.testing import LocalBus

__all__ = [
    "Level",
    "Requirement",
    "CheckResult",
    "ConformanceReport",
    "REQUIREMENTS",
    "run_agent_conformance",
]


class Level:
    MUST = "MUST"
    SHOULD = "SHOULD"


@dataclass(frozen=True)
class Requirement:
    """One checkable statement from the specification."""

    id: str
    level: str
    summary: str
    reference: str = ""


REQUIREMENTS: tuple[Requirement, ...] = (
    Requirement(
        "LIP-REG-001", Level.MUST,
        "Sends `register` as the first message on a connection",
        "LIP §10 Agent Admission",
    ),
    Requirement(
        "LIP-REG-002", Level.MUST,
        "The register payload carries an agent_id and validates",
        "LIP §10",
    ),
    Requirement(
        "LIP-REG-003", Level.SHOULD,
        "Declares at least one capability when registering",
        "LIP §8 Capability Discovery",
    ),
    Requirement(
        "LIP-VER-001", Level.MUST,
        "Every message carries a protocol_version",
        "LIP §13 Protocol Versioning",
    ),
    Requirement(
        "LIP-MSG-001", Level.MUST,
        "Every message is a valid envelope",
        "LIP §10 Message Envelope",
    ),
    Requirement(
        "LIP-MSG-002", Level.MUST,
        "Each payload matches the schema for its message type",
        "LIP §10",
    ),
    Requirement(
        "LIP-MSG-003", Level.MUST,
        "Uses only performatives defined by the protocol",
        "LIP §10",
    ),
    Requirement(
        "LIP-INT-001", Level.SHOULD,
        "Responds to a matching `intent` with an `offer`",
        "LIP §7 Semantic Matching",
    ),
    Requirement(
        "LIP-EXE-001", Level.MUST,
        "Does not execute before receiving `execute`",
        "LIP §10, agent responsibilities",
    ),
    Requirement(
        "LIP-EXE-002", Level.MUST,
        "Emits `complete` when execution ends",
        "LIP §10",
    ),
    Requirement(
        "LIP-DIS-001", Level.MUST,
        "Stops work for a session on `dissolve`",
        "LIP §9 Contract Lifecycle",
    ),
    Requirement(
        "LIP-ACK-001", Level.SHOULD,
        "Keeps serving when `registered` never arrives",
        "RFC 0001",
    ),
)

_BY_ID = {r.id: r for r in REQUIREMENTS}


@dataclass
class CheckResult:
    requirement: Requirement
    passed: bool
    detail: str = ""
    skipped: bool = False

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.passed else "FAIL"


@dataclass
class ConformanceReport:
    results: list[CheckResult] = field(default_factory=list)
    protocol_version: str = LIP_PROTOCOL_VERSION
    agent_id: str = ""

    def record(self, requirement_id: str, passed: bool, detail: str = "") -> None:
        self.results.append(CheckResult(_BY_ID[requirement_id], passed, detail))

    def skip(self, requirement_id: str, detail: str) -> None:
        self.results.append(
            CheckResult(_BY_ID[requirement_id], passed=False, detail=detail, skipped=True)
        )

    @property
    def failures(self) -> list[CheckResult]:
        """MUST-level failures. These are what make an implementation non-conformant."""
        return [
            r for r in self.results
            if not r.passed and not r.skipped and r.requirement.level == Level.MUST
        ]

    @property
    def warnings(self) -> list[CheckResult]:
        return [
            r for r in self.results
            if not r.passed and not r.skipped and r.requirement.level == Level.SHOULD
        ]

    @property
    def is_conformant(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "agent_id": self.agent_id,
            "conformant": self.is_conformant,
            "results": [
                {
                    "id": r.requirement.id,
                    "level": r.requirement.level,
                    "summary": r.requirement.summary,
                    "reference": r.requirement.reference,
                    "status": r.status,
                    "detail": r.detail,
                }
                for r in self.results
            ],
        }

    def render(self) -> str:
        lines = [
            f"LIP {self.protocol_version} conformance — agent {self.agent_id or '<unknown>'}",
            "",
        ]
        for r in self.results:
            lines.append(
                f"  [{r.status:4s}] {r.requirement.id}  {r.requirement.summary}"
            )
            if r.detail and r.status != "PASS":
                lines.append(f"         {r.detail}")
        lines.append("")
        if self.is_conformant:
            lines.append(f"CONFORMANT ({len(self.warnings)} advisory warning(s))")
        else:
            lines.append(f"NOT CONFORMANT — {len(self.failures)} MUST requirement(s) failed")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _check_messages(bus: LocalBus, report: ConformanceReport) -> None:
    """Structural checks over everything the agent has sent so far."""
    raw_messages = bus.messages

    # LIP-MSG-001 — anything the bus could not parse as an envelope. These
    # never reach `messages`, so the transcript alone would show a malformed
    # sender as simply quiet.
    report.record(
        "LIP-MSG-001",
        not bus.malformed,
        f"{len(bus.malformed)} frame(s) were not valid envelopes: "
        f"{bus.malformed[0][:120]}" if bus.malformed else "",
    )

    # LIP-MSG-003 — the message set is closed.
    known = {m.value for m in MessageType}
    unknown = sorted(
        {e.message_type for e in raw_messages if e.message_type not in known}
    )
    report.record(
        "LIP-MSG-003",
        not unknown,
        f"undefined performatives: {unknown}" if unknown else "",
    )

    # LIP-VER-001 — a version on every message. An envelope that arrived
    # without one is read as 0.1.0, so an agent claiming 0.2.0 support must
    # actually send the field.
    missing_version = [
        e.message_id for e in raw_messages if not e.protocol_version
    ]
    report.record(
        "LIP-VER-001",
        not missing_version,
        f"{len(missing_version)} message(s) carried no protocol_version"
        if missing_version else "",
    )

    # LIP-MSG-002 — payloads match their declared type.
    payload_errors: list[str] = []
    for envelope in raw_messages:
        model = PAYLOAD_TYPES.get(envelope.message_type)
        if model is None:
            continue
        try:
            model.model_validate(envelope.payload)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            payload_errors.append(f"{envelope.message_type}: {exc}")
    report.record(
        "LIP-MSG-002",
        not payload_errors,
        "; ".join(payload_errors[:3]) if payload_errors else "",
    )


async def _check_registration(bus: LocalBus, report: ConformanceReport) -> bool:
    """Registration checks. Returns False when nothing registered at all."""
    registers = bus.messages_of_type(MessageType.REGISTER)

    if not bus.messages:
        report.record("LIP-REG-001", False, "the agent sent no messages")
        return False

    # LIP-REG-001 — register must come first, before anything else.
    first = bus.messages[0]
    report.record(
        "LIP-REG-001",
        first.message_type == MessageType.REGISTER,
        f"first message was {first.message_type!r}, expected 'register'",
    )

    if not registers:
        report.record("LIP-REG-002", False, "no register message was sent")
        report.skip("LIP-REG-003", "no registration to inspect")
        return False

    payload = registers[0].payload
    agent_id = payload.get("agent_id", "")
    report.agent_id = agent_id
    report.record(
        "LIP-REG-002",
        bool(agent_id),
        "register payload carried no agent_id" if not agent_id else "",
    )

    capabilities = payload.get("capabilities") or []
    report.record(
        "LIP-REG-003",
        bool(capabilities),
        "registered with no capabilities, so nothing can ever be routed to it"
        if not capabilities else "",
    )
    return True


async def _check_lifecycle(
    bus: LocalBus, report: ConformanceReport, *, timeout: float
) -> None:
    """Drive intent → execute → complete → dissolve and observe."""
    agent_id = report.agent_id
    session = "conformance-lifecycle"

    # LIP-INT-001 — an intent should draw an offer.
    offers = await bus.send_intent(
        "conformance probe: describe what you can do",
        session_id=session,
        timeout=timeout,
    )
    report.record(
        "LIP-INT-001",
        bool(offers),
        "no offer was made for an intent (acceptable if no capability matched)"
        if not offers else "",
    )

    # LIP-EXE-001 — nothing may complete before an execute is sent.
    premature = [
        e for e in bus.messages_of_type(MessageType.COMPLETE)
        if e.session_id == session
    ]
    report.record(
        "LIP-EXE-001",
        not premature,
        "emitted 'complete' before receiving 'execute'" if premature else "",
    )

    # LIP-EXE-002 — execution must end in a complete.
    exec_session = "conformance-execute"
    try:
        await bus.execute(agent_id, {"probe": True}, session_id=exec_session,
                          timeout=timeout)
        report.record("LIP-EXE-002", True)
    except TimeoutError:
        report.record(
            "LIP-EXE-002", False,
            f"no 'complete' within {timeout}s of 'execute'",
        )
    except KeyError as exc:
        report.skip("LIP-EXE-002", f"agent unreachable: {exc}")


async def _check_dissolution(
    bus: LocalBus, report: ConformanceReport, *, timeout: float
) -> None:
    """LIP-DIS-001 — dissolve ends work for its session."""
    session = "conformance-dissolve"
    agent_id = report.agent_id

    try:
        await bus.send(
            MessageType.EXECUTE,
            session,
            {"execution_plan": {"probe": "long", "context": {}}, "authorized_scopes": []},
            agent_id=agent_id,
        )
    except KeyError as exc:
        report.skip("LIP-DIS-001", f"agent unreachable: {exc}")
        return

    await asyncio.sleep(0.2)

    def _count_for_session() -> int:
        return len([e for e in bus.messages if e.session_id == session])

    before = _count_for_session()
    await bus.dissolve(session, reason="conformance check")
    await asyncio.sleep(min(timeout, 2.0))
    after = _count_for_session()

    # Work that keeps producing messages after dissolution has not torn the
    # interaction down. A message already in flight when the dissolve was
    # sent is not a violation, so only sustained activity is reported — this
    # distinguishes "finished just in time" from "ignored the dissolve".
    continued = after - before
    report.record(
        "LIP-DIS-001",
        continued <= 1,
        f"{continued} message(s) arrived for the session after `dissolve`"
        if continued > 1 else "",
    )


async def run_agent_conformance(
    *,
    bus: LocalBus,
    timeout: float = 10.0,
) -> ConformanceReport:
    """Run every check against whatever agent has registered on *bus*.

    The bus is supplied rather than created here so the caller decides how
    the agent got there — started in-process, or connected from another
    process in another language.
    """
    report = ConformanceReport()

    registered = await _check_registration(bus, report)
    if registered:
        await _check_lifecycle(bus, report, timeout=timeout)
        await _check_dissolution(bus, report, timeout=timeout)
    else:
        for requirement in REQUIREMENTS:
            if requirement.id not in {r.requirement.id for r in report.results}:
                report.skip(requirement.id, "the agent never registered")

    # Structural checks run last, over everything the agent sent while the
    # lifecycle checks were driving it.
    _check_messages(bus, report)

    # LIP-ACK-001 is about behaviour on a bus that never acknowledges, which
    # needs its own connection; the caller runs it separately.
    if "LIP-ACK-001" not in {r.requirement.id for r in report.results}:
        report.skip("LIP-ACK-001", "not exercised in this run")

    return report


async def check_survives_missing_acknowledgement(
    agent_factory: Any,
    *,
    timeout: float = 5.0,
) -> CheckResult:
    """LIP-ACK-001, which needs a coordinator that never answers `register`.

    A coordinator implementing LIP 0.1.0 does not send `registered` at all, so
    an agent that refuses to run without one cannot talk to it.
    """
    async with LocalBus(answer_registrations=False) as bus:
        agent = agent_factory()
        agent.coordinator_uri = bus.uri
        task = asyncio.create_task(agent.run_forever())
        try:
            deadline = asyncio.get_running_loop().time() + timeout
            while asyncio.get_running_loop().time() < deadline:
                if bus.messages_of_type(MessageType.REGISTER):
                    break
                await asyncio.sleep(0.05)

            registered = bool(bus.messages_of_type(MessageType.REGISTER))
            return CheckResult(
                _BY_ID["LIP-ACK-001"],
                passed=registered,
                detail="" if registered
                else "the agent did not register against an unacknowledging bus",
            )
        finally:
            await agent.stop()
            task.cancel()


def report_to_json(report: ConformanceReport) -> str:
    return json.dumps(report.to_dict(), indent=2)
