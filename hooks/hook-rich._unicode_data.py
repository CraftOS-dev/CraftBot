"""PyInstaller hook: include rich._unicode_data/*.py as data files.

These files have hyphenated names (e.g. unicode17-0-0.py) which PyInstaller's
static analysis cannot discover. We include them as data files so they exist
on the filesystem at runtime, where our runtime hook can load them.
"""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("rich._unicode_data", include_py_files=True)
