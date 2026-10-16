"""Exercise the actual export predicate without importing live app settings."""

import ast
from pathlib import Path
import tempfile
import unittest


class ExportExclusionTests(unittest.TestCase):
    def test_saved_sources_and_generated_account_documents_are_not_exported(self):
        source = (
            Path(__file__).resolve().parents[2]
            / "app/ui_layer/settings/profile_bundle.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        selected = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_should_skip_path"
            or isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name)
                and t.id in ("SKIP_DIR_NAMES", "SKIP_FILE_SUFFIXES")
                for t in node.targets
            )
        ]
        namespace = {"Path": Path}
        exec(
            compile(ast.Module(body=selected, type_ignores=[]), str(source), "exec"),
            namespace,
        )
        predicate = namespace["_should_skip_path"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in (
                ".env",
                ".env.local",
                ".env.production",
                "figma.accounts.json",
                "mini_browser_vault.enc",
                "mini_browser_vault.key",
            ):
                file = root / name
                file.write_text("synthetic", encoding="utf-8")
                with self.subTest(name=name):
                    self.assertTrue(predicate(file))
            ordinary = root / "SKILL.md"
            ordinary.write_text("ordinary skill", encoding="utf-8")
            self.assertFalse(predicate(ordinary))
