from __future__ import annotations

from pathlib import Path
import mkdocs_gen_files

ROOT = Path(__file__).resolve().parents[2]

# Top-level packages in your repo
PACKAGE_DIRS = ["app", "agents"]

def is_package_dir(d: Path) -> bool:
    return d.is_dir() and (d / "__init__.py").exists()

def iter_python_modules(pkg_dir: Path):
    for path in sorted(pkg_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        yield path

nav_lines: list[str] = []
nav_lines.append("* [Home](index.md)")
nav_lines.append("* [Getting started](getting-started.md)")
nav_lines.append("* API Reference")

for pkg_name in PACKAGE_DIRS:
    pkg_path = ROOT / pkg_name
    if not is_package_dir(pkg_path):
        continue

    nav_lines.append(f"    * [{pkg_name}](reference/{pkg_name}/index.md)")

    index_md = Path("reference") / pkg_name / "index.md"
    with mkdocs_gen_files.open(index_md, "w") as f:
        f.write(f"# {pkg_name}\n\n")
        f.write(f"::: {pkg_name}\n")

    for py_file in iter_python_modules(pkg_path):
        rel = py_file.relative_to(ROOT)
        module_parts = rel.with_suffix("").parts
        module_path = ".".join(module_parts)

        doc_path = Path("reference") / Path(*module_parts).with_suffix(".md")

        with mkdocs_gen_files.open(doc_path, "w") as f:
            title = " / ".join(module_parts)
            f.write(f"# {title}\n\n")
            f.write(f"::: {module_path}\n")

        nav_lines.append(f"        * [{module_parts[-1]}]({doc_path.as_posix()})")

with mkdocs_gen_files.open("SUMMARY.md", "w") as nav_file:
    nav_file.write("\n".join(nav_lines) + "\n")
