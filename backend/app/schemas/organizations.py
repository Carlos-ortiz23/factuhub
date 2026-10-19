"""Transport contracts for the organization endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import MembershipRole


class OrganizationCreateRequest(BaseModel):
    """The data a company is created with.

    No NIT validation beyond shape: the specification does not define a checksum
    rule, and inventing one would reject valid clients. Whether the same company
    written as `900123456-7` and `900123456` should collapse into one record is
    an open decision recorded in the feature document, not something to guess.
    """

    name: str = Field(min_length=1, max_length=200)
    tax_id: str = Field(min_length=1, max_length=32)


class OrganizationResponse(BaseModel):
    """A company as seen by one member.

    `role` is the caller's role, not a property of the company: the same company
    is a different object to its admin and to its viewer.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    tax_id: str
    role: MembershipRole
    created_at: datetime


class OrganizationListResponse(BaseModel):
    """The companies the caller belongs to."""

    organizations: list[OrganizationResponse]


class AddMemberRequest(BaseModel):
    """Give an existing account a role in a company."""

    email: EmailStr
    role: MembershipRole


class ChangeMemberRoleRequest(BaseModel):
    """The role a member should hold from now on."""

    role: MembershipRole


class MemberResponse(BaseModel):
    """A membership as the interface shows it.

    Carries the person's name and address so the members table does not need an
    extra request per row.
    """

    user_id: UUID
    email: str
    full_name: str
    role: MembershipRole
    created_at: datetime
