# -*- coding: utf-8 -*-
"""Runtime dependency checks that can run before dependency-heavy imports."""

import json
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


_MISSING_SENTINEL = "__CRAFTBOT_MISSING_RUNTIME_IMPORTS__"

RUNTIME_IMPORT_CHECKS = {
    # Packages imported during backend startup. Provider SDKs stay deferred so
    # DeepSeek/OpenRouter users are not forced to install unrelated SDKs.
    "requests": "requests",
    "pyyaml": "yaml",
    "loguru": "loguru",
    "nest-asyncio": "nest_asyncio",
    "pymongo": "pymongo",
    "tzlocal": "tzlocal",
    "aiohttp": "aiohttp",
    "chromadb": "chromadb",
    "tiktoken": "tiktoken",
    "mss": "mss",
    "httpx": "httpx",
    "websockets": "websockets",
    "tenacity": "tenacity",
    "gradio_client": "gradio_client",
    "python-dotenv": "dotenv",
    "scikit-learn": "sklearn",
    "watchdog": "watchdog",
    "croniter": "croniter",
}


def _runtime_import_script(checks: Dict[str, str]) -> str:
    return (
        "import importlib\n"
        "import json\n"
        f"checks = {list(checks.items())!r}\n"
        "missing = []\n"
        "for package_name, import_name in checks:\n"
        "    try:\n"
        "        importlib.import_module(import_name)\n"
        "    except Exception:\n"
        "        missing.append(package_name)\n"
        f"print({_MISSING_SENTINEL!r} + json.dumps(missing))\n"
    )


def _runtime_import_command(
    use_conda: bool,
    env_name: Optional[str],
    checks: Dict[str, str],
    conda_command: str,
) -> Tuple[List[str], str]:
    script = _runtime_import_script(checks)
    if use_conda and env_name:
        return (
            [
                conda_command,
                "run",
                "-n",
                env_name,
                "python",
                "-c",
                script,
            ],
            f"conda environment '{env_name}'",
        )
    return ([sys.executable, "-c", script], sys.executable)


def find_missing_runtime_dependencies(
    *,
    use_conda: bool,
    env_name: Optional[str],
    checks: Optional[Dict[str, str]] = None,
    conda_command: str = "conda",
) -> Tuple[List[str], str]:
    """Return missing core imports for the Python runtime that will run the agent."""
    if checks is None:
        checks = RUNTIME_IMPORT_CHECKS
    cmd, runtime_label = _runtime_import_command(
        use_conda, env_name, checks, conda_command
    )

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception:
        return list(checks), runtime_label
    if result.returncode != 0:
        return list(checks), runtime_label

    for line in reversed(result.stdout.splitlines()):
        if line.startswith(_MISSING_SENTINEL):
            return json.loads(line[len(_MISSING_SENTINEL) :]), runtime_label
    return list(checks), runtime_label


def print_missing_runtime_dependencies(
    *,
    missing: List[str],
    runtime_label: str,
    use_conda: bool,
    env_name: Optional[str],
) -> None:
    print("\nError: CraftBot Python dependencies are missing.")
    print(f"Runtime checked: {runtime_label}")
    print("\nMissing imports:")
    for package_name in missing:
        print(f"  - {package_name}")

    print(
        "\nThis usually means CraftBot is running with a different Python "
        "than the one used during install."
    )
    print("\nFix:")
    if use_conda and env_name:
        print("  python install.py --conda")
        print(f"  conda run -n {env_name} python run.py")
    else:
        print(f"  {sys.executable} install.py")
        print(f"  {sys.executable} run.py")
    print("\nIf you installed CraftBot with another Python, start it with that Python.")


def ensure_runtime_dependencies(
    *,
    use_conda: bool,
    env_name: Optional[str],
    conda_command: str = "conda",
) -> None:
    if getattr(sys, "frozen", False):
        return

    missing, runtime_label = find_missing_runtime_dependencies(
        use_conda=use_conda,
        env_name=env_name,
        conda_command=conda_command,
    )
    if missing:
        print_missing_runtime_dependencies(
            missing=missing,
            runtime_label=runtime_label,
            use_conda=use_conda,
            env_name=env_name,
        )
        sys.exit(1)


def ensure_current_runtime_dependencies() -> None:
    """Check imports for direct app.main usage with the current interpreter."""
    ensure_runtime_dependencies(use_conda=False, env_name=None)
