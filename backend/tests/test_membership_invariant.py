"""Durable probes for A11: the last-admin invariant and the lock that protects it.

These tests did not come from the author. They are the regression probes an
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
            db, organization_id=org.id, user_id=uid, role=MembershipRole.VIEWER
        ),
        lambda db, org, uid: organizations_service.remove_member(
            db, organization_id=org.id, user_id=uid
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
            user_id=admin.id,
            role=MembershipRole.VIEWER,
        )

    stored = db_session.get(OrganizationMember, (organization.id, admin.id))
    assert (stored.user_id, stored.role) == before
