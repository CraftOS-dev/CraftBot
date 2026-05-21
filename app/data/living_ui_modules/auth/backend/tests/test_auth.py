"""
Auth Module Tests — validates registration, login, token auth, and admin access.

Copy this file into your project's backend/tests/ directory.
Run: cd backend && python -m pytest tests/test_auth.py -v
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from models import Base
from main import app
from database import get_db


# Test database — in-memory SQLite
test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables for each test."""
    # Import auth models so they're registered with Base
    import auth_models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestRegistration:
    def test_register_first_user_is_admin(self, client):
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "admin@example.com",
                "username": "admin",
                "password": "secure123",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user"]["role"] == "admin"
        assert "token" in data

    def test_register_second_user_is_member(self, client):
        client.post(
            "/api/auth/register",
            json={
                "email": "admin@example.com",
                "username": "admin",
                "password": "secure123",
            },
        )
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "user@example.com",
                "username": "user1",
                "password": "secure123",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "member"

    def test_register_duplicate_email(self, client):
        client.post(
            "/api/auth/register",
            json={
                "email": "test@example.com",
                "username": "user1",
                "password": "pass123",
            },
        )
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "test@example.com",
                "username": "user2",
                "password": "pass123",
            },
        )
        assert resp.status_code == 400
        assert "already registered" in resp.json()["detail"]

    def test_register_duplicate_username(self, client):
        client.post(
            "/api/auth/register",
            json={
                "email": "a@example.com",
                "username": "sameuser",
                "password": "pass123",
            },
        )
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "b@example.com",
                "username": "sameuser",
                "password": "pass123",
            },
        )
        assert resp.status_code == 400
        assert "already taken" in resp.json()["detail"]


class TestLogin:
    def test_login_success(self, client):
        client.post(
            "/api/auth/register",
            json={
                "email": "test@example.com",
                "username": "testuser",
                "password": "mypassword",
            },
        )
        resp = client.post(
            "/api/auth/login",
            json={
                "email": "test@example.com",
                "password": "mypassword",
            },
        )
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_login_wrong_password(self, client):
        client.post(
            "/api/auth/register",
            json={
                "email": "test@example.com",
                "username": "testuser",
                "password": "correct",
            },
        )
        resp = client.post(
            "/api/auth/login",
            json={
                "email": "test@example.com",
                "password": "wrong",
            },
        )
        assert resp.status_code == 401

    def test_login_nonexistent_user(self, client):
        resp = client.post(
            "/api/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "pass",
            },
        )
        assert resp.status_code == 401


class TestAuthenticatedAccess:
    def _register_and_get_token(self, client, email="test@example.com"):
        resp = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "username": email.split("@")[0],
                "password": "pass123",
            },
        )
        return resp.json()["token"]

    def test_get_me(self, client):
        token = self._register_and_get_token(client)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "test@example.com"

    def test_get_me_no_token(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_get_me_invalid_token(self, client):
        resp = client.get("/api/auth/me", headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401


class TestAdminAccess:
    def test_admin_can_list_users(self, client):
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "admin@example.com",
                "username": "admin",
                "password": "pass123",
            },
        )
        token = resp.json()["token"]
        resp = client.get(
            "/api/auth/users", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert len(resp.json()["users"]) == 1

    def test_member_cannot_list_users(self, client):
        # First user is admin
        client.post(
            "/api/auth/register",
            json={
                "email": "admin@example.com",
                "username": "admin",
                "password": "pass123",
            },
        )
        # Second user is member
        resp = client.post(
            "/api/auth/register",
            json={
                "email": "member@example.com",
                "username": "member",
                "password": "pass123",
            },
        )
        token = resp.json()["token"]
        resp = client.get(
            "/api/auth/users", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403
