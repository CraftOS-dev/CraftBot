"""PyInstaller runtime hook: custom finder for rich._unicode_data.unicodeX-X-X.

rich._unicode_data.__init__ uses importlib.import_module() to load modules
with hyphenated names (e.g. 'unicode17-0-0'). PyInstaller's FrozenImporter
cannot handle these, so we install a meta-path finder that loads them from
the filesystem (they are included via our companion hook as data files).
"""

import sys
import os
import importlib
import importlib.abc
import importlib.util


class _RichUnicodeDataFinder(importlib.abc.MetaPathFinder):
    def find_module(self, fullname, path=None):
        if not fullname.startswith("rich._unicode_data.unicode"):
            return None
        base = getattr(sys, "_MEIPASS", None)
        if base is None:
            return None
        filepath = os.path.join(
            base, "rich", "_unicode_data", fullname.rsplit(".", 1)[-1] + ".py"
        )
        if os.path.isfile(filepath):
            return self
        return None

    def load_module(self, fullname):
        if fullname in sys.modules:
            return sys.modules[fullname]
        base = sys._MEIPASS
        filepath = os.path.join(
            base, "rich", "_unicode_data", fullname.rsplit(".", 1)[-1] + ".py"
        )
        spec = importlib.util.spec_from_file_location(fullname, filepath)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[fullname] = mod
        spec.loader.exec_module(mod)
        return mod


if getattr(sys, "frozen", False):
    sys.meta_path.insert(0, _RichUnicodeDataFinder())
