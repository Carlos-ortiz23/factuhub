"""Transport contracts for the authentication endpoints.

Password length is deliberately *not* constrained here: the policy lives in
`app.core.security` so there is exactly one definition of what a valid password
is, and the service raises a domain error the endpoint translates. Duplicating
the numbers in a Pydantic field would let the two drift apart silently.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    """Everything needed to create an account, and nothing else."""

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1)


class LoginRequest(BaseModel):
    """Credentials for an existing account."""

    email: EmailStr
    password: str = Field(min_length=1)


class UserResponse(BaseModel):
    """What the API reveals about a user.

    Never the password hash, never the session token, never internal flags the
    client cannot act on.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    created_at: datetime
