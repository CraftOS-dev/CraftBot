"""
Auth Routes — registration, login, user management endpoints.

Copy this file into your project's backend/ directory.
Then import and include the router in routes.py:

    from auth_routes import router as auth_router
    # ... at the bottom of routes.py:
    router.include_router(auth_router)
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth_models import User, Membership, Invite
from auth_middleware import get_current_user, require_admin
from auth_service import hash_password, verify_password, create_token
from database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: str
    username: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user. First user automatically becomes admin."""
    # Check for existing user
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    # First user is admin
    is_first_user = db.query(User).count() == 0
    role = "admin" if is_first_user else "member"

    user = User(
        email=data.email,
        username=data.username,
        password_hash=hash_password(data.password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    return {"user": user.to_dict(), "token": token}


@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """Login with email and password."""
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    token = create_token(user.id)
    return {"user": user.to_dict(), "token": token}


@router.get("/me")
def get_me(user: User = Depends(get_current_user)):
    """Get the current authenticated user."""
    return {"user": user.to_dict()}


@router.post("/logout")
def logout():
    """Logout — client should delete the stored token."""
    return {"message": "Logged out"}


@router.get("/users")
def list_users(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all users (admin only)."""
    users = db.query(User).order_by(User.created_at.desc()).all()
    return {"users": [u.to_dict() for u in users]}


# ============================================================================
# Profile — update own account
# ============================================================================


class UpdateProfileRequest(BaseModel):
    username: str = None
    email: str = None


@router.put("/me")
def update_profile(
    data: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update current user's profile."""
    if data.email and data.email != user.email:
        if db.query(User).filter(User.email == data.email, User.id != user.id).first():
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = data.email
    if data.username and data.username != user.username:
        if (
            db.query(User)
            .filter(User.username == data.username, User.id != user.id)
            .first()
        ):
            raise HTTPException(status_code=400, detail="Username already taken")
        user.username = data.username
    db.commit()
    db.refresh(user)
    return {"user": user.to_dict()}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.put("/me/password")
def change_password(
    data: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change current user's password."""
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(data.new_password) < 6:
        raise HTTPException(
            status_code=400, detail="Password must be at least 6 characters"
        )
    user.password_hash = hash_password(data.new_password)
    db.commit()
    return {"message": "Password updated"}


# ============================================================================
# Membership — link users to resources (projects, boards, teams, etc.)
# ============================================================================


def _check_membership(
    db: Session,
    user: User,
    resource_type: str,
    resource_id: int,
    required_roles: tuple = None,
) -> None:
    """Verify user has access to a resource. Raises 403 if not.

    Args:
        required_roles: If set, user must have one of these roles (e.g., ("owner", "admin")).
                       If None, any membership is sufficient.
    """
    if user.role == "admin":
        return  # Global admins bypass all checks
    membership = (
        db.query(Membership)
        .filter_by(
            user_id=user.id, resource_type=resource_type, resource_id=resource_id
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a member of this resource")
    if required_roles and membership.role not in required_roles:
        raise HTTPException(
            status_code=403, detail=f"Requires role: {' or '.join(required_roles)}"
        )


@router.get("/members/{resource_type}/{resource_id}")
def get_members(
    resource_type: str,
    resource_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get all members of a resource. Caller must be a member."""
    _check_membership(db, user, resource_type, resource_id)
    members = (
        db.query(Membership)
        .filter_by(resource_type=resource_type, resource_id=resource_id)
        .all()
    )
    return {"members": [m.to_dict() for m in members]}


class AddMemberRequest(BaseModel):
    user_id: int
    role: str = "member"


@router.post("/members/{resource_type}/{resource_id}")
def add_member(
    resource_type: str,
    resource_id: int,
    data: AddMemberRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Add a user to a resource. Caller must be owner/admin of the resource."""
    _check_membership(db, user, resource_type, resource_id, ("owner", "admin"))

    existing = (
        db.query(Membership)
        .filter_by(
            user_id=data.user_id, resource_type=resource_type, resource_id=resource_id
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="User is already a member")

    membership = Membership(
        user_id=data.user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        role=data.role,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return {"membership": membership.to_dict()}


@router.delete("/members/{resource_type}/{resource_id}/{user_id}")
def remove_member(
    resource_type: str,
    resource_id: int,
    user_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove a user from a resource. Caller must be owner/admin or removing themselves."""
    if user.id != user_id:
        _check_membership(db, user, resource_type, resource_id, ("owner", "admin"))

    membership = (
        db.query(Membership)
        .filter_by(
            user_id=user_id, resource_type=resource_type, resource_id=resource_id
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=404, detail="Membership not found")

    db.delete(membership)
    db.commit()
    return {"message": "Member removed"}


# ============================================================================
# Invites — shareable links to join a resource
# ============================================================================


class CreateInviteRequest(BaseModel):
    resource_type: str
    resource_id: int
    default_role: str = "member"
    max_uses: int = None


@router.post("/invites")
def create_invite(
    data: CreateInviteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create an invite link for a resource. Caller must be owner/admin."""
    _check_membership(
        db, user, data.resource_type, data.resource_id, ("owner", "admin")
    )

    invite = Invite.create(
        resource_type=data.resource_type,
        resource_id=data.resource_id,
        created_by=user.id,
        default_role=data.default_role,
        max_uses=data.max_uses,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return {"invite": invite.to_dict()}


@router.post("/invites/{code}/accept")
def accept_invite(
    code: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept an invite and join the resource."""
    invite = db.query(Invite).filter_by(code=code, is_active=True).first()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite not found or expired")

    if invite.max_uses and invite.use_count >= invite.max_uses:
        raise HTTPException(status_code=410, detail="Invite has reached maximum uses")

    # Check if already a member
    existing = (
        db.query(Membership)
        .filter_by(
            user_id=user.id,
            resource_type=invite.resource_type,
            resource_id=invite.resource_id,
        )
        .first()
    )
    if existing:
        return {"membership": existing.to_dict(), "message": "Already a member"}

    membership = Membership(
        user_id=user.id,
        resource_type=invite.resource_type,
        resource_id=invite.resource_id,
        role=invite.default_role,
    )
    invite.use_count += 1
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return {"membership": membership.to_dict()}
