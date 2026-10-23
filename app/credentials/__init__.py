"""Shared login credential storage used by the Mini Browser and app consumers."""

from .vault import CredentialVault, Secret, VaultError, get_vault

__all__ = ["CredentialVault", "Secret", "VaultError", "get_vault"]
