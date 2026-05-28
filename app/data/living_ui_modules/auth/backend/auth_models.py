"""
Auth Models — User accounts and resource membership for multi-user Living UI apps.

Copy this file into your project's backend/ directory.
Import in your models.py:
    from auth_models import User, Membership  # noqa: F401
"""

import secrets
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from models import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="member")  # "admin" or "member"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    memberships = relationship(
        "Membership", back_populates="user", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "username": self.username,
            "role": self.role,
            "isActive": self.is_active,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }


class Membership(Base):
    """
    Generic membership — links a user to any app resource (project, board, team, etc.).

    Usage:
        # Add user to a project as editor
        m = Membership(user_id=1, resource_type="project", resource_id=5, role="editor")
        db.add(m)

        # Get all members of a project
        members = db.query(Membership).filter_by(resource_type="project", resource_id=5).all()

        # Get all projects a user belongs to
        project_ids = db.query(Membership.resource_id).filter_by(
            user_id=1, resource_type="project"
        ).all()

        # Check if user is a member
        is_member = db.query(Membership).filter_by(
            user_id=1, resource_type="project", resource_id=5
        ).first() is not None
    """

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "resource_type", "resource_id", name="uq_membership"
        ),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    resource_type = Column(
        String(50), nullable=False
    )  # "project", "board", "team", etc.
    resource_id = Column(Integer, nullable=False, index=True)
    role = Column(
        String(50), default="member"
    )  # "owner", "admin", "editor", "viewer", "member"
    invite_code = Column(String(64), nullable=True)  # For pending invites
    joined_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="memberships")

    def to_dict(self):
        return {
            "id": self.id,
            "userId": self.user_id,
            "resourceType": self.resource_type,
            "resourceId": self.resource_id,
            "role": self.role,
            "joinedAt": self.joined_at.isoformat() if self.joined_at else None,
            "user": self.user.to_dict() if self.user else None,
        }


class Invite(Base):
    """
    Invite links — generate a code that anyone can use to join a resource.

    Usage:
        # Create invite link for a project
        invite = Invite.create(resource_type="project", resource_id=5, created_by=1)
        db.add(invite)
        # Share the code: invite.code

        # Accept invite
        invite = db.query(Invite).filter_by(code="abc123", is_active=True).first()
        membership = Membership(user_id=2, resource_type=invite.resource_type,
                                resource_id=invite.resource_id, role=invite.default_role)
    """

    __tablename__ = "invites"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)
    resource_id = Column(Integer, nullable=False)
    default_role = Column(String(50), default="member")
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_active = Column(Boolean, default=True)
    max_uses = Column(Integer, nullable=True)  # None = unlimited
    use_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    @classmethod
    def create(
        cls,
        resource_type: str,
        resource_id: int,
        created_by: int,
        default_role: str = "member",
        max_uses: int = None,
    ):
        return cls(
            code=secrets.token_urlsafe(16),
            resource_type=resource_type,
            resource_id=resource_id,
            created_by=created_by,
            default_role=default_role,
            max_uses=max_uses,
        )

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "resourceType": self.resource_type,
            "resourceId": self.resource_id,
            "defaultRole": self.default_role,
            "isActive": self.is_active,
            "maxUses": self.max_uses,
            "useCount": self.use_count,
            "createdAt": self.created_at.isoformat() if self.created_at else None,
        }
