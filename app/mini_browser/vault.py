"""Compatibility import for the shared credential vault.

Both import paths resolve to the same module, singleton and per-directory locks.
Existing credential files, key wrapping and the public vault API are unchanged.
"""

import sys

from app.credentials import vault as _vault

sys.modules[__name__] = _vault
