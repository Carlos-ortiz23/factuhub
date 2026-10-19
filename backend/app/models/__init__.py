"""SQLAlchemy models describing the persistence shape.

Importing this package registers every model on `Base.metadata`, which is what
Alembic autogenerate compares against the live database.
"""

from app.models.audit_log import AuditLog
from app.models.login_throttle import LoginThrottle
from app.models.organization import Organization
from app.models.organization_member import MembershipRole, OrganizationMember
from app.models.provider_credential import ProviderConnectionStatus, ProviderCredential
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "AuditLog",
    "LoginThrottle",
    "MembershipRole",
    "Organization",
    "OrganizationMember",
    "ProviderConnectionStatus",
    "ProviderCredential",
    "User",
    "UserSession",
]
