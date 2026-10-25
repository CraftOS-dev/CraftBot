import ast
from pathlib import Path

import install


def test_python_310_binary_installer_candidates_are_available():
    """Only use Python releases with official binary installers."""
    assert install.PYTHON_310_BINARY_INSTALLER_VERSIONS == ("3.10.11",)


def test_windows_and_macos_loops_use_supported_candidates():
    """Both platform-specific loops must use the validated version list."""
    source = Path(install.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    installer_function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_auto_install_python_310"
    )

    candidate_loops = [
        node
        for node in ast.walk(installer_function)
        if isinstance(node, ast.For)
        and isinstance(node.iter, ast.Name)
        and node.iter.id == "PYTHON_310_BINARY_INSTALLER_VERSIONS"
    ]

    assert len(candidate_loops) == 2
    assert not any(
        isinstance(node, ast.Name)
        and node.id == "PYTHON_VERSION_CANDIDATES"
        for node in ast.walk(installer_function)
    )
