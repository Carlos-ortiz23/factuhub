"""Durable probes for A11 and A12: the last-admin invariant, the lock that
protects it, and the caller's authority re-read under that lock.

The A11 tests did not come from the author. They are the regression probes an
independent verification pass wrote, and they exist because the race itself
cannot be reproduced inside this suite: `conftest.py` rolls every test back
inside one transaction, so there is no second connection to race with.

What the independent pass observed on real connections, with real commits,
against a scratch database: 20/20 concurrent self-demotions refused the loser
and left exactly one admin, 10/10 concurrent removals did the same, and a
negative control that skipped the lock reached **zero admins** — which is what
makes the result evidence rather than coincidence.

So the race is pinned by the mechanism it depends on. Removing the
`SELECT ... FOR UPDATE` makes these tests fail (2 of 3), which was verified by
deleting the call in a scratch copy.

The A12 block came from the correction the 4R review demanded: the route
dependency resolved the caller's role *before* the lock and never again after
it, so a demotion committed while a request waited did not revoke it, and
`add_member` took no lock at all. It is pinned the same way — the role is read
after the lock, and a role that no longer grants the permission is refused.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event

from app.models import MembershipRole, Organization, OrganizationMember, User
from app.services import organizations as organizations_service

pytestmark = pytest.mark.integration


def _company_with_admin(db_session, *, tax_id: str) -> tuple[Organization, User]:
    organization = Organization(id=uuid.uuid4(), name="Invariante", tax_id=tax_id)
    user = User(
        id=uuid.uuid4(),
        email=f"invariante-{uuid.uuid4().hex[:8]}@example.com",
        full_name="Invariante",
        password_hash="not-a-real-hash",
    )
    db_session.add_all([organization, user])
    db_session.flush()
    db_session.add(
        OrganizationMember(
            organization_id=organization.id, user_id=user.id, role=MembershipRole.ADMIN
        )
    )
    db_session.flush()
    return organization, user


def _capture_sql(db_session, action) -> list[str]:
    connection = db_session.connection()
    statements: list[str] = []

    def listener(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(connection, "before_cursor_execute", listener)
    try:
        action()
    finally:
        event.remove(connection, "before_cursor_execute", listener)
    return statements


@pytest.mark.parametrize(
    "call",
    [
        lambda db, org, uid: organizations_service.change_member_role(
            db, organization_id=org.id, actor_id=uid, user_id=uid, role=MembershipRole.VIEWER
        ),
        lambda db, org, uid: organizations_service.remove_member(
            db, organization_id=org.id, actor_id=uid, user_id=uid
        ),
    ],
    ids=["change_member_role", "remove_member"],
)
def test_membership_changes_lock_the_company_row_first(db_session, call) -> None:
    # The lock must be taken on `organizations`, not on the membership row: the
    # row being removed is the one that would have to be locked.
    organization, admin = _company_with_admin(db_session, tax_id=f"LOCK-{uuid.uuid4().hex[:8]}")

    def refusal():
        with pytest.raises(organizations_service.LastAdminError):
            call(db_session, organization, admin.id)

    statements = _capture_sql(db_session, refusal)

    locks = [s for s in statements if "FOR UPDATE" in s.upper()]
    assert locks, "no SELECT ... FOR UPDATE was issued before counting administrators"
    assert all("organizations" in s for s in locks), locks


def test_a_refused_demotion_leaves_the_membership_row_untouched(db_session) -> None:
    # A refused command must not have changed anything, and the value here is
    # (user_id, role) rather than the whole row: `created_at` is also unchanged,
    # which the independent pass confirmed byte for byte.
    organization, admin = _company_with_admin(db_session, tax_id=f"KEEP-{uuid.uuid4().hex[:8]}")
    before = (
        admin.id,
        MembershipRole.ADMIN,
    )

    with pytest.raises(organizations_service.LastAdminError):
        organizations_service.change_member_role(
            db_session,
            organization_id=organization.id,
            actor_id=admin.id,
            user_id=admin.id,
            role=MembershipRole.VIEWER,
        )

    stored = db_session.get(OrganizationMember, (organization.id, admin.id))
    assert (stored.user_id, stored.role) == before


# A12: the caller's authority is re-read under the lock. These tests run against
# the service on purpose: by the time the handler runs, the dependency has
# already answered, and the gap was exactly that the answer was never revisited.


def _company_with_two_members(db_session) -> tuple[Organization, User, User]:
    organization = Organization(
        id=uuid.uuid4(), name="Autoridad", tax_id=f"AUT-{uuid.uuid4().hex[:8]}"
    )
    db_session.add(organization)
    db_session.flush()
    people = []
    for label, role in (
        ("actor", MembershipRole.ADMIN),
        ("target", MembershipRole.ACCOUNTANT),
    ):
        user = User(
            id=uuid.uuid4(),
            email=f"{label}-{uuid.uuid4().hex[:8]}@example.com",
            full_name=label,
            password_hash="not-a-real-hash",
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(
            OrganizationMember(organization_id=organization.id, user_id=user.id, role=role)
        )
        people.append(user)
    db_session.flush()
    return organization, people[0], people[1]


def _set_role(db_session, organization: Organization, user: User, role: MembershipRole) -> None:
    membership = db_session.get(OrganizationMember, (organization.id, user.id))
    membership.role = role
    db_session.flush()


def _revoke(db_session, organization: Organization, user: User) -> None:
    db_session.delete(db_session.get(OrganizationMember, (organization.id, user.id)))
    db_session.flush()


CALLS = {
    "add_member": lambda db, org, actor, target: organizations_service.add_member(
        db,
        organization_id=org.id,
        actor_id=actor.id,
        email=target.email,
        role=MembershipRole.VIEWER,
    ),
    "change_member_role": lambda db, org, actor, target: organizations_service.change_member_role(
        db,
        organization_id=org.id,
        actor_id=actor.id,
        user_id=target.id,
        role=MembershipRole.VIEWER,
    ),
    "remove_member": lambda db, org, actor, target: organizations_service.remove_member(
        db, organization_id=org.id, actor_id=actor.id, user_id=target.id
    ),
}


@pytest.mark.parametrize("call", CALLS.values(), ids=list(CALLS))
def test_a_demoted_caller_cannot_manage_members(db_session, call) -> None:
    # The dependency saw an admin; by the time the lock is held the caller is a
    # viewer, and the write must not happen.
    organization, actor, target = _company_with_two_members(db_session)
    _set_role(db_session, organization, actor, MembershipRole.VIEWER)

    with pytest.raises(organizations_service.InsufficientPermissionError):
        call(db_session, organization, actor, target)


@pytest.mark.parametrize("call", CALLS.values(), ids=list(CALLS))
def test_a_removed_caller_cannot_manage_members(db_session, call) -> None:
    # A removed admin's in-flight request must not resurrect the membership, and
    # answers like a stranger: the company is not an existence oracle.
    organization, actor, target = _company_with_two_members(db_session)
    _revoke(db_session, organization, actor)

    with pytest.raises(organizations_service.MembershipRevokedError):
        call(db_session, organization, actor, target)


def test_the_caller_is_re_read_after_the_company_lock(db_session) -> None:
    # The order is the fix: a role read before the lock is the stale answer the
    # review found. The first membership statement after the lock selects only
    # the role, which is what identifies the caller's re-check.
    organization, actor, target = _company_with_two_members(db_session)
    _set_role(db_session, organization, actor, MembershipRole.VIEWER)

    def refusal():
        with pytest.raises(organizations_service.InsufficientPermissionError):
            organizations_service.change_member_role(
                db_session,
                organization_id=organization.id,
                actor_id=actor.id,
                user_id=target.id,
                role=MembershipRole.VIEWER,
            )

    statements = _capture_sql(db_session, refusal)
    lock_at = next(i for i, s in enumerate(statements) if "FOR UPDATE" in s.upper())
    role_at = next(i for i, s in enumerate(statements) if "organization_members.role" in s)
    assert lock_at < role_at, statements
