"""Redacting holders shared with the legacy browser vault.

Internal host code only: this is not an agent API or an isolation mechanism.
Managed Python memory cannot provide guaranteed zeroization.
"""

from typing import Any


class Secret:
    """Wrap immediately at secure entry; never print or pickle the value."""

    __slots__ = ("_value",)

    def __init__(self, value: Any) -> None:
        self._value = value

    @classmethod
    def wrap(cls, value: Any) -> "Secret":
        return value if isinstance(value, Secret) else cls(value)

    def reveal(self) -> Any:
        """Private-boundary plumbing; never expose through a consumer route."""
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('[redacted]')"

    def __str__(self) -> str:
        return "[redacted]"

    def __reduce__(self):
        raise TypeError("Secret values cannot be pickled")
