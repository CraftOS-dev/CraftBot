import os
import ssl
import sys
from pathlib import Path

# Windows SSL-store shim: importing aiohttp in this env can hit a broken
# certificate in the Windows cert store (ssl.SSLError [ASN1: NOT_ENOUGH_DATA]).
# Swallow the error so collection/imports succeed (mirrors app/main.py shim).
_orig_load_windows_store_certs = ssl.SSLContext._load_windows_store_certs


def _safe_load_windows_store_certs(self, storename, purpose):
    try:
        _orig_load_windows_store_certs(self, storename, purpose)
    except ssl.SSLError:
        pass


ssl.SSLContext._load_windows_store_certs = _safe_load_windows_store_certs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
