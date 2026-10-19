"""The permission matrix must be exhaustive, not a set of good intentions.

Spec §11.2 names the permissions that have to be checked in the backend (read,
import, reconcile, approve, integration configuration) and says authorization
must be enforced per operation, with Row-Level Security as an additional layer
rather than a substitute. The matrix below is the application layer.
"""

from __future__ import annotations

import pytest

from app.core.permissions import PERMISSIONS_BY_ROLE, Permission, role_has_permission
from app.models.organization_member import MembershipRole

pytestmark = pytest.mark.unit


def test_every_role_appears_in_the_matrix() -> None:
    # A role added to the enum but forgotten here would silently receive no
    # permissions at all — or, worse, whatever a `.get()` default handed back.
    assert set(PERMISSIONS_BY_ROLE) == set(MembershipRole)


def test_every_role_can_at_least_read() -> None:
    # A member who cannot read their own company's data is not a member.
    assert all(role_has_permission(role, Permission.READ) for role in MembershipRole)


def test_only_an_admin_manages_members() -> None:
    allowed = {
        role for role in MembershipRole if role_has_permission(role, Permission.MANAGE_MEMBERS)
    }

    assert allowed == {MembershipRole.ADMIN}


def test_a_viewer_can_only_read() -> None:
    assert PERMISSIONS_BY_ROLE[MembershipRole.VIEWER] == frozenset({Permission.READ})


def test_a_reviewer_approves_but_does_not_reconcile() -> None:
    # Separation of duties: whoever reconciles should not be the only person who
    # approves the result.
    assert role_has_permission(MembershipRole.REVIEWER, Permission.APPROVE)
    assert not role_has_permission(MembershipRole.REVIEWER, Permission.RECONCILE)
    assert not role_has_permission(MembershipRole.REVIEWER, Permission.IMPORT)


def test_an_unknown_permission_is_denied_rather_than_crashing() -> None:
    assert role_has_permission(MembershipRole.ADMIN, "delete_everything") is False


def test_no_role_can_grant_permissions_it_does_not_hold() -> None:
    # Cheap invariant, real consequence: the admin set must contain every
    # permission any other role holds, so adding a permission to a weaker role
    # cannot produce a role more powerful than admin.
    union = frozenset().union(*PERMISSIONS_BY_ROLE.values())

    assert union <= PERMISSIONS_BY_ROLE[MembershipRole.ADMIN]
