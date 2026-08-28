"""Shared fixtures for the integrations core tests.

Everything runs against a FileCredentialStore rooted in tmp_path — no
ConfigStore monkeypatching, no global state.
"""

from __future__ import annotations

import itertools

import pytest

from craftos_integrations.core.accounts import AccountManager
from craftos_integrations.core.storage import FileCredentialStore

GOOGLE_FAMILY = ("gmail", "google_calendar")


def _family(pid: str):
    return GOOGLE_FAMILY if pid in GOOGLE_FAMILY else (pid,)


@pytest.fixture
def store(tmp_path):
    return FileCredentialStore(root=tmp_path)


@pytest.fixture
def clock():
    """Deterministic, strictly increasing timestamps."""
    counter = itertools.count(1)
    return lambda: f"2026-08-10T00:00:{next(counter):02d}+00:00"


@pytest.fixture
def mgr(store, clock):
    return AccountManager(store, family_members=_family, clock=clock)


def cred(identity: str, **extra):
    """A synthetic credential blob."""
    return {"email": identity, "access_token": f"tok-{identity}", **extra}


@pytest.fixture
def two_accounts(mgr):
    """gmail with a@x.com (primary, alias 'work') and b@y.com (alias 'school')."""
    mgr.upsert_account("gmail", "a@x.com", cred("a@x.com"))
    mgr.upsert_account("gmail", "b@y.com", cred("b@y.com"))
    mgr.set_alias("gmail", "a@x.com", "work")
    mgr.set_alias("gmail", "b@y.com", "school")
    return mgr
