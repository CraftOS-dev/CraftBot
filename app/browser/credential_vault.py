"""
Encrypted credential vault for the Web Agent (auto-unlock mode).

Stores website logins the user saves, so the agent can sign in on their behalf.
Security model (chosen by the user = "auto-unlock"):
  * Passwords are encrypted at rest with Fernet (AES-128-CBC + HMAC).
  * The symmetric key lives in a local key file next to the vault, so the agent
    can decrypt without a master password (convenient, autonomous). This is the
    same practical trade-off as a browser's built-in password store: safe from
    casual file reading, but a determined attacker with access to these files on
    this PC could decrypt. No master password = no protection against that.
  * `list_entries()` NEVER returns passwords — only site + username. Passwords
    leave the vault only via `get_for_domain()`, which is used solely by the
    autofill code path that types them into the page (never into the LLM prompt
    or logs).

Files (in app/config/, git-ignored):
  * .web_agent_vault.key  — the Fernet key
  * .web_agent_vault.enc  — the encrypted JSON vault
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.logger import logger


def _config_dir() -> str:
    try:
        from app.config import APP_CONFIG_PATH

        return str(APP_CONFIG_PATH)
    except Exception:
        from app.config import AGENT_WORKSPACE_ROOT

        return str(AGENT_WORKSPACE_ROOT)


def normalize_domain(site: str) -> str:
    """Reduce a URL or host to a bare domain, e.g. https://www.amazon.com/... -> amazon.com."""
    s = (site or "").strip().lower()
    if "://" in s:
        s = urlparse(s).netloc or s
    else:
        s = s.split("/")[0]
    if s.startswith("www."):
        s = s[4:]
    return s.strip()


class CredentialVault:
    """Auto-unlock encrypted store of website credentials."""

    def _key_path(self) -> str:
        return os.path.join(_config_dir(), ".web_agent_vault.key")

    def _vault_path(self) -> str:
        return os.path.join(_config_dir(), ".web_agent_vault.enc")

    def _fernet(self):
        from cryptography.fernet import Fernet

        kp = self._key_path()
        if not os.path.exists(kp):
            key = Fernet.generate_key()
            with open(kp, "wb") as f:
                f.write(key)
            try:
                os.chmod(kp, 0o600)
            except Exception:
                pass
        else:
            with open(kp, "rb") as f:
                key = f.read()
        return Fernet(key)

    def _load(self) -> List[Dict[str, Any]]:
        p = self._vault_path()
        if not os.path.exists(p):
            return []
        try:
            with open(p, "rb") as f:
                data = f.read()
            if not data:
                return []
            dec = self._fernet().decrypt(data)
            entries = json.loads(dec.decode("utf-8"))
            return entries if isinstance(entries, list) else []
        except Exception as e:
            logger.error("[Vault] failed to load vault: %s", e)
            return []

    def _save(self, entries: List[Dict[str, Any]]) -> None:
        p = self._vault_path()
        enc = self._fernet().encrypt(json.dumps(entries).encode("utf-8"))
        with open(p, "wb") as f:
            f.write(enc)
        try:
            os.chmod(p, 0o600)
        except Exception:
            pass

    # ── public API (passwords never returned here) ───────────────────────────

    def list_entries(self) -> List[Dict[str, Any]]:
        """Entries for display — site + username + label only, NO passwords."""
        return [
            {
                "id": e.get("id"),
                "site": e.get("site", ""),
                "username": e.get("username", ""),
                "label": e.get("label", ""),
            }
            for e in self._load()
        ]

    def add_entry(
        self, site: str, username: str, password: str, label: str = ""
    ) -> Dict[str, Any]:
        entries = self._load()
        entry = {
            "id": uuid.uuid4().hex[:12],
            "site": normalize_domain(site),
            "username": username or "",
            "password": password or "",
            "label": label or "",
        }
        entries.append(entry)
        self._save(entries)
        logger.info("[Vault] added credential for %s", entry["site"])
        return {k: entry[k] for k in ("id", "site", "username", "label")}

    def update_entry(
        self,
        entry_id: str,
        site: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        label: Optional[str] = None,
    ) -> bool:
        entries = self._load()
        for e in entries:
            if e.get("id") == entry_id:
                if site is not None:
                    e["site"] = normalize_domain(site)
                if username is not None:
                    e["username"] = username
                if password:  # blank/omitted => keep existing password
                    e["password"] = password
                if label is not None:
                    e["label"] = label
                self._save(entries)
                return True
        return False

    def delete_entry(self, entry_id: str) -> bool:
        entries = self._load()
        kept = [e for e in entries if e.get("id") != entry_id]
        if len(kept) != len(entries):
            self._save(kept)
            logger.info("[Vault] deleted credential %s", entry_id)
            return True
        return False

    # ── internal (autofill only) ─────────────────────────────────────────────

    def get_for_domain(self, domain_or_url: str) -> Optional[Dict[str, Any]]:
        """Return the full credential (incl. password) best matching a domain.

        For autofill use ONLY — the caller must type it into the page, never
        return it to the model or logs.
        """
        d = normalize_domain(domain_or_url)
        if not d:
            return None
        entries = self._load()
        fallback = None
        for e in entries:
            s = normalize_domain(e.get("site", ""))
            if not s:
                continue
            if s == d:
                return e
            if d.endswith(s) or s.endswith(d):
                fallback = fallback or e
        return fallback


_vault: Optional[CredentialVault] = None


def get_vault() -> CredentialVault:
    global _vault
    if _vault is None:
        _vault = CredentialVault()
    return _vault
