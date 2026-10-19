"""What each role is allowed to do.

Spec §11.2 lists the permissions the backend has to verify per operation —
reading, importing, reconciling, approving and configuring integrations — and
§7.2 names four roles. The matrix that joins them is not spelled out in the
specification, so this mapping is an **assumption** recorded in
`odd/tasks/auth-and-organizations.md`, chosen to keep the separation of duties
the specification asks for elsewhere (§7.7: whoever reconciles is not
necessarily whoever approves).

Two design notes worth keeping:

* The matrix is exhaustive over `MembershipRole`. `PERMISSIONS_BY_ROLE` is typed
  as `dict[MembershipRole, frozenset[Permission]]`, and a test asserts every role
  is present, so adding a role to the enum without deciding its permissions
  fails the suite instead of creating a role that can do nothing.
* `MANAGE_MEMBERS` is not in §11.2's list. It is required for the membership
  endpoints, and it is recorded as an assumption rather than smuggled in.
"""

from __future__ import annotations

from enum import StrEnum

from app.models.organization_member import MembershipRole


class Permission(StrEnum):
    """One thing a member may be allowed to do inside a company."""

    READ = "read"
    IMPORT = "import"
    RECONCILE = "reconcile"
    APPROVE = "approve"
    MANAGE_INTEGRATIONS = "manage_integrations"
    MANAGE_MEMBERS = "manage_members"


PERMISSIONS_BY_ROLE: dict[MembershipRole, frozenset[Permission]] = {
    MembershipRole.ADMIN: frozenset(Permission),
    # The accountant runs the day-to-day work: imports, reconciles, and connects
    # the company's accounting system.
    MembershipRole.ACCOUNTANT: frozenset(
        {
            Permission.READ,
            Permission.IMPORT,
            Permission.RECONCILE,
            Permission.MANAGE_INTEGRATIONS,
        }
    ),
    # Reviewer sees the result and approves or reopens it, and cannot alter it.
    MembershipRole.REVIEWER: frozenset({Permission.READ, Permission.APPROVE}),
    MembershipRole.VIEWER: frozenset({Permission.READ}),
}


def role_has_permission(role: MembershipRole, permission: Permission | str) -> bool:
    """Whether `role` holds `permission`.

    Accepts a plain string so an unknown permission is denied instead of raising:
    an authorization check that can crash is one that might be caught somewhere
    and treated as allowed.
    """
    return permission in PERMISSIONS_BY_ROLE.get(role, frozenset())
