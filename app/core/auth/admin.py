"""Admin authorization for administrative operations.

An identity is considered an admin if **any** of these are true:

1. Its OIDC ``sub`` claim is listed in ``AGBUS_ADMIN_SUBJECTS``
   (comma-separated env var).
2. Its OIDC token carries a custom claim that matches the configured
   admin role (``AGBUS_ADMIN_ROLE``, default ``agbus:admin``) inside the
   claim key ``AGBUS_ADMIN_ROLE_CLAIM`` (default ``roles``).

Both mechanisms can be active simultaneously – the first match wins.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from app.core.auth.oidc import OIDCIdentity

logger = logging.getLogger(__name__)


@dataclass
class AdminPolicy:
    """Describes who is considered an admin.

    Parameters
    ----------
    subjects : set[str]
        OIDC ``sub`` values that are always admins.
    role : str
        The value to look for inside the token's role claim.
    role_claim : str
        The token claim key that carries the list of roles.
    """

    subjects: set[str] = field(default_factory=set)
    role: str = "agbus:admin"
    role_claim: str = "roles"

    # ------------------------------------------------------------------
    # Factory – build from env vars
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "AdminPolicy":
        raw = os.getenv("AGBUS_ADMIN_SUBJECTS", "")
        subjects = {s.strip() for s in raw.split(",") if s.strip()}
        role = os.getenv("AGBUS_ADMIN_ROLE", "agbus:admin")
        role_claim = os.getenv("AGBUS_ADMIN_ROLE_CLAIM", "roles")
        return cls(subjects=subjects, role=role, role_claim=role_claim)

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def is_admin(self, identity: OIDCIdentity) -> bool:
        """Return ``True`` if *identity* satisfies admin requirements."""
        # 1. Subject allow-list
        if identity.subject in self.subjects:
            return True

        # 2. Role claim
        roles = identity.custom_claims.get(self.role_claim)
        if isinstance(roles, list) and self.role in roles:
            return True
        if isinstance(roles, str) and roles == self.role:
            return True

        return False


def require_admin(identity: OIDCIdentity, policy: AdminPolicy | None = None) -> None:
    """Raise ``PermissionError`` if *identity* is not an admin.

    A convenience wrapper around ``AdminPolicy.is_admin`` for guard clauses.
    """
    if policy is None:
        policy = AdminPolicy.from_env()
    if not policy.is_admin(identity):
        raise PermissionError(
            f"Admin privileges required. Subject {identity.subject!r} is not an admin."
        )
