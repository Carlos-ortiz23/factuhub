"""Integrity rules that the database must enforce on its own.

These are not incidental checks: each one guards a way financial data could be
silently corrupted. If a rule lives only in Python, one script, one migration or
one future service can bypass it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models import AuditLog, MembershipRole, Organization, OrganizationMember, User
from app.models.audit_log import METADATA_COLUMN_NAME

pytestmark = pytest.mark.integration


def create_organization(session: Session, tax_id: str = "900123456") -> Organization:
    organization = Organization(name="Empresa de prueba", tax_id=tax_id)
    session.add(organization)
    session.flush()
    return organization


def create_user(session: Session, email: str = "contador@example.com") -> User:
    user = User(email=email, full_name="Contador de prueba", password_hash="not-a-real-hash")
    session.add(user)
    session.flush()
    return user


def test_membership_role_is_persisted_as_its_lowercase_value(db_session: Session) -> None:
    organization = create_organization(db_session)
    user = create_user(db_session)
    db_session.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=MembershipRole.ADMIN,
        )
    )
    db_session.flush()

    stored = db_session.execute(text("SELECT role FROM organization_members")).scalar_one()

    # SQLAlchemy persists a PEP-435 enum by member NAME unless told otherwise,
    # which would store "ADMIN" here and silently disagree with every API
    # payload and role check.
    assert stored == "admin"


def test_user_email_must_be_lowercase(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        create_user(db_session, email="Contador@Example.com")


def test_organizations_reject_a_duplicate_tax_id(db_session: Session) -> None:
    create_organization(db_session, tax_id="900999888")

    with pytest.raises(IntegrityError):
        create_organization(db_session, tax_id="900999888")


def test_membership_requires_an_existing_user(db_session: Session) -> None:
    organization = create_organization(db_session)

    with pytest.raises(IntegrityError):
        db_session.add(
            OrganizationMember(
                organization_id=organization.id,
                user_id=uuid.uuid4(),
                role=MembershipRole.ACCOUNTANT,
            )
        )
        db_session.flush()


def test_audit_log_metadata_defaults_to_an_empty_object(db_session: Session) -> None:
    organization = create_organization(db_session)
    db_session.add(
        AuditLog(
            organization_id=organization.id,
            action="organization.created",
            entity_type="organization",
            entity_id=organization.id,
        )
    )
    db_session.flush()

    metadata_value = db_session.execute(
        text(f"SELECT {METADATA_COLUMN_NAME} FROM audit_logs")
    ).scalar_one()

    assert metadata_value == {}


def test_a_user_with_audit_history_cannot_be_deleted(db_session: Session) -> None:
    organization = create_organization(db_session)
    user = create_user(db_session)
    db_session.add(
        AuditLog(
            organization_id=organization.id,
            user_id=user.id,
            action="membership.granted",
            entity_type="organization_member",
            entity_id=organization.id,
        )
    )
    db_session.flush()

    # The alternative — `ON DELETE SET NULL` — would have quietly rewritten the
    # audit row to "no user did this", which is the silent modification of
    # history the specification forbids. Deactivating the account is the
    # supported way to remove someone's access.
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.execute(text("DELETE FROM users WHERE id = :user_id"), {"user_id": user.id})

    assert db_session.execute(text("SELECT count(*) FROM users")).scalar_one() == 1


def test_audit_log_rows_cannot_be_updated(db_session: Session) -> None:
    organization = create_organization(db_session)
    db_session.add(
        AuditLog(
            organization_id=organization.id,
            action="organization.created",
            entity_type="organization",
            entity_id=organization.id,
        )
    )
    db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
        db_session.execute(text("UPDATE audit_logs SET action = 'tampered'"))

    remaining = db_session.execute(text("SELECT action FROM audit_logs")).scalar_one()
    assert remaining == "organization.created"


def test_audit_log_rows_cannot_be_deleted(db_session: Session) -> None:
    organization = create_organization(db_session)
    db_session.add(
        AuditLog(
            organization_id=organization.id,
            action="organization.created",
            entity_type="organization",
            entity_id=organization.id,
        )
    )
    db_session.flush()

    with pytest.raises(DBAPIError, match="append-only"), db_session.begin_nested():
        db_session.execute(text("DELETE FROM audit_logs"))

    assert db_session.execute(text("SELECT count(*) FROM audit_logs")).scalar_one() == 1
