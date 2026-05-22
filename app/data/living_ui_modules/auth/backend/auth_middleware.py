"""
Auth Middleware — FastAPI dependencies for protecting routes.

Copy this file into your project's backend/ directory.

Usage in routes:
    from auth_middleware import get_current_user, require_admin

    @router.get("/my-items")
    def get_my_items(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        return db.query(Item).filter(Item.user_id == user.id).all()

    @router.get("/admin/users")
    def list_users(user: User = Depends(require_admin), db: Session = Depends(get_db)):
        return [u.to_dict() for u in db.query(User).all()]
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from auth_models import User, Membership
from auth_service import verify_token
from database import get_db


def get_current_user(
    authorization: str = Header(None),
    db: Session = Depends(get_db),
) -> User:
    """FastAPI dependency that extracts and validates the Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.split(" ", 1)[1]
    try:
        payload = verify_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = int(payload.get("sub", 0))
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """FastAPI dependency that requires the current user to be an admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_membership(resource_type: str):
    """
    Factory that returns a FastAPI dependency requiring membership in a resource.

    The route must have a path parameter matching the resource_id.

    Usage:
        @router.get("/projects/{project_id}/tasks")
        def get_tasks(
            project_id: int,
            user: User = Depends(get_current_user),
            member: Membership = Depends(require_membership("project")),
            db: Session = Depends(get_db),
        ):
            return db.query(Task).filter_by(project_id=project_id).all()
    """
    from fastapi import Request

    def dependency(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> Membership:
        # Extract resource_id from path params — try common patterns
        resource_id = (
            request.path_params.get(f"{resource_type}_id")
            or request.path_params.get("resource_id")
            or request.path_params.get("id")
        )
        if not resource_id:
            raise HTTPException(
                status_code=400, detail=f"Missing {resource_type}_id in path"
            )

        # Global admins bypass membership check
        if user.role == "admin":
            membership = (
                db.query(Membership)
                .filter_by(
                    user_id=user.id,
                    resource_type=resource_type,
                    resource_id=int(resource_id),
                )
                .first()
            )
            if membership:
                return membership
            # Admin without membership — create a synthetic one for compatibility
            return Membership(
                user_id=user.id,
                resource_type=resource_type,
                resource_id=int(resource_id),
                role="admin",
            )

        membership = (
            db.query(Membership)
            .filter_by(
                user_id=user.id,
                resource_type=resource_type,
                resource_id=int(resource_id),
            )
            .first()
        )
        if not membership:
            raise HTTPException(
                status_code=403, detail=f"Not a member of this {resource_type}"
            )
        return membership

    return dependency
