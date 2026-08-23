"""Scope vocabulary: what a coordinator recognises, and what covers what.

A scope names a permission. Two things about it are easy to get wrong, and
both were wrong here before this module existed.

**Exact string equality does not survive a real deployment.** A grant of
``payments:*`` plainly ought to cover ``payments:write``, and comparing the
two with ``==`` says otherwise. So matching is hierarchical.

**A scope an agent invented is not a permission.** The vocabulary belongs to
the deployment, not to whoever wrote the agent — see RFC 0003. This module
holds the matching and the posture; the catalogue itself is persisted.

Nothing here decides whether an agent *has* a scope. It decides whether one
scope covers another, and whether an unrecognised name is tolerated.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Separator for the hierarchy. ``payments:write`` is below ``payments``.
SEPARATOR = ":"
#: Trailing segment meaning "everything below this point".
WILDCARD = "*"


def normalise(scope: str) -> str:
    """Canonical form: trimmed and lowercased.

    Case is not meaningful in a scope name, and treating ``Payments:Write`` as
    distinct from ``payments:write`` produces two entries that look identical
    in every interface an operator will ever read.
    """
    return scope.strip().lower()


def covers(granted: str, requested: str) -> bool:
    """Whether holding *granted* permits *requested*.

    ``payments:*`` covers ``payments:write`` and ``payments:refund:approve``.
    ``payments:write`` covers only itself — a grant is not widened by having
    children.

    A bare ``*`` covers everything, which exists so a development catalogue
    can be permissive deliberately rather than by accident.
    """
    granted = normalise(granted)
    requested = normalise(requested)

    if not granted or not requested:
        return False
    if granted == requested:
        return True
    if granted == WILDCARD:
        return True

    if granted.endswith(SEPARATOR + WILDCARD):
        prefix = granted[: -len(WILDCARD)]
        return requested.startswith(prefix)

    return False


def covered_by_any(granted: list[str], requested: str) -> bool:
    """Whether any grant in *granted* permits *requested*."""
    return any(covers(g, requested) for g in granted)


def parent_of(scope: str) -> str:
    """The scope one level up, or empty at the root.

    ``payments:refund:approve`` → ``payments:refund`` → ``payments`` → ``""``.
    """
    scope = normalise(scope)
    if SEPARATOR not in scope:
        return ""
    return scope.rsplit(SEPARATOR, 1)[0]


def is_well_formed(scope: str) -> bool:
    """Whether a name is usable as a scope.

    Deliberately strict about the shape and silent about the meaning: a
    coordinator has no opinion on whether ``carrier:quote`` is a sensible
    permission, only on whether it can be stored, matched and displayed
    without surprising someone.
    """
    scope = normalise(scope)
    if not scope or len(scope) > 128:
        return False
    if scope == WILDCARD:
        return True

    segments = scope.split(SEPARATOR)
    for index, segment in enumerate(segments):
        if not segment:
            return False  # empty segment: "a::b", ":a", "a:"
        if segment == WILDCARD:
            # A wildcard is only meaningful as the final segment. "a:*:b" is
            # almost certainly a mistake, and accepting it would mean deciding
            # what it means.
            if index != len(segments) - 1:
                return False
            continue
        if not all(c.isalnum() or c in "-_." for c in segment):
            return False
    return True


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


def scope_enforcement_enabled(default: bool = False) -> bool:
    """Whether a missing grant refuses execution, or only warns.

    Separate from the catalogue posture, and defaulting to it. A deployment
    that enforces its vocabulary has decided grants mean something — but
    binding every capability takes longer than deciding to, so the two are
    separable and this can be turned on afterwards.

    ``AGBUS_SCOPE_ENFORCED`` overrides in either direction.
    """
    raw = os.getenv("AGBUS_SCOPE_ENFORCED")
    if raw is None:
        return default
    return raw.strip().lower() in ("true", "1", "yes", "on")


@dataclass
class ScopeDecision:
    """How a registration's declared scopes were resolved."""

    #: Names present in the catalogue.
    recognised: list[str] = field(default_factory=list)
    #: Names the catalogue does not have. A request, not a grant.
    unrecognised: list[str] = field(default_factory=list)
    #: Names added to the catalogue by this registration (development only).
    catalogued: list[str] = field(default_factory=list)
    #: Names rejected outright because they are not usable as scope names.
    malformed: list[str] = field(default_factory=list)


class ScopePolicy:
    """What a coordinator does with vocabulary it does not recognise.

    **Development** (default) — an unrecognised scope is added to the
    catalogue, unbound, and warned about. A local bus should not require a
    catalogue authored before anything can run.

    **Enforcing** — the scope is refused and recorded as a request, and the
    catalogue is returned so the author learns the right name. Set
    ``AGBUS_SCOPE_CATALOGUE_ENFORCED=true``.

    A deployment that authored a catalogue has said what it recognises, and
    the coordinator must not quietly extend it.
    """

    def __init__(self, enforced: bool | None = None) -> None:
        self.enforced = (
            _env_flag("AGBUS_SCOPE_CATALOGUE_ENFORCED", False)
            if enforced is None
            else enforced
        )

    @property
    def auto_catalogues(self) -> bool:
        return not self.enforced

    def resolve(
        self, declared: list[str], catalogue: list[str]
    ) -> ScopeDecision:
        """Partition declared scopes against the catalogue.

        This does not grant anything. Under RFC 0003 a scope is granted by a
        binding an administrator authored, never by an agent having asked —
        so the most this can conclude is that a name is one the coordinator
        knows.
        """
        decision = ScopeDecision()
        seen: set[str] = set()

        for raw in declared:
            scope = normalise(raw)
            if scope in seen:
                continue
            seen.add(scope)

            if not is_well_formed(scope):
                decision.malformed.append(raw)
                logger.warning("Ignoring malformed scope %r", raw)
                continue

            if covered_by_any(catalogue, scope):
                decision.recognised.append(scope)
            elif self.auto_catalogues:
                decision.catalogued.append(scope)
                decision.recognised.append(scope)
            else:
                decision.unrecognised.append(scope)

        return decision
