"""Guards for the install paths every user takes, whatever their machine.

Each test pins down a failure users actually hit: an interpreter the
installer should never have touched, an archive extraction that crashed on
an older Python, a network that only works through a mirror or a proxy, a
platform with no dependency lock.

Run: python -m unittest discover -s tests/install_bootstrap -v
No application dependencies or credentials are needed.
"""

import ast
import io
import os
import re
import sys
import tarfile
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from app import downloads, embedding_model, node_runtime, python_runtime
from app.provision import default_context, default_stages
from app.provision.runtimes import PythonStage, TARGET_PYTHON
from app.provision.types import Context, Status

REPO = Path(__file__).resolve().parents[2]


def _tar_with(members):
    """An in-memory tar.gz holding (name, kind, payload_or_linkname) entries."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, kind, data in members:
            info = tarfile.TarInfo(name)
            if kind == "file":
                payload = data.encode()
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))
            elif kind == "symlink":
                info.type = tarfile.SYMTYPE
                info.linkname = data
                tf.addfile(info)
            elif kind == "hardlink":
                info.type = tarfile.LNKTYPE
                info.linkname = data
                tf.addfile(info)
    buf.seek(0)
    return buf


class SafeExtractTests(unittest.TestCase):
    """macOS's built-in 3.9.6 and python.org's 3.10.11 lack filter="data"."""

    @staticmethod
    @contextmanager
    def _python_without_tar_filter():
        """Make this interpreter look like 3.9.6 / 3.10.11 to the helper."""
        saved = getattr(tarfile, "data_filter", None)
        if saved is not None:
            del tarfile.data_filter
        try:
            yield
        finally:
            if saved is not None:
                tarfile.data_filter = saved

    def _extract(self, members, without_filter):
        with tempfile.TemporaryDirectory() as dest:
            archive = _tar_with(members)
            with tarfile.open(fileobj=archive, mode="r:gz") as tf:
                if without_filter:
                    with self._python_without_tar_filter():
                        downloads.safe_extract_tar(tf, dest)
                else:
                    downloads.safe_extract_tar(tf, dest)
            return sorted(
                str(p.relative_to(dest)).replace("\\", "/")
                for p in Path(dest).rglob("*")
                if p.is_file()
            )

    def test_normal_archive_extracts_on_every_python(self):
        members = [
            ("python/bin/python3", "file", "x"),
            ("python/lib/os.py", "file", "y"),
        ]
        for without_filter in (False, True):
            self.assertEqual(
                self._extract(members, without_filter),
                ["python/bin/python3", "python/lib/os.py"],
            )

    def test_traversal_is_refused_without_the_filter(self):
        for evil in ("../escape.txt", "/abs/escape.txt"):
            with self.assertRaises(Exception):
                self._extract([(evil, "file", "x")], without_filter=True)

    def test_hard_links_resolve_from_the_archive_root(self):
        # python-build-standalone's terminfo layout. Ubuntu 22.04's 3.10.12
        # data filter rejected exactly this as "outside the destination".
        members = [
            ("python/share/terminfo/a/adm1178", "file", "entry"),
            (
                "python/share/terminfo/1/1178",
                "hardlink",
                "python/share/terminfo/a/adm1178",
            ),
        ]
        for without_filter in (False, True):
            self.assertEqual(
                self._extract(members, without_filter),
                ["python/share/terminfo/1/1178", "python/share/terminfo/a/adm1178"],
            )

    def test_symlink_out_of_tree_is_refused_without_the_filter(self):
        with self.assertRaises(ValueError):
            self._extract(
                [("python/evil", "symlink", "../../outside")], without_filter=True
            )

    def test_no_runtime_extraction_calls_extractall_with_filter_directly(self):
        for rel in ("app/provision/runtimes.py", "app/node_runtime.py"):
            source = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn('filter="data"', source, rel)


class MirrorTests(unittest.TestCase):
    def test_no_settings_leaves_url_alone(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                downloads.mirror_url("https://nodejs.org/dist/x"),
                "https://nodejs.org/dist/x",
            )

    def test_hf_endpoint_and_explicit_rules(self):
        env = {
            "HF_ENDPOINT": "https://hf-mirror.com/",
            "CRAFTBOT_MIRRORS": "https://nodejs.org/dist/=https://npmmirror.com/mirrors/node/;bad;"
            "https://github.com/=https://gh.example/https://github.com/",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                downloads.mirror_url(
                    "https://huggingface.co/BAAI/m/resolve/r/model.onnx"
                ),
                "https://hf-mirror.com/BAAI/m/resolve/r/model.onnx",
            )
            self.assertEqual(
                downloads.mirror_url("https://nodejs.org/dist/v24/n.zip"),
                "https://npmmirror.com/mirrors/node/v24/n.zip",
            )
            self.assertEqual(
                downloads.mirror_url("https://github.com/a/b"),
                "https://gh.example/https://github.com/a/b",
            )

    def test_first_listed_rule_wins_like_the_launcher(self):
        env = {
            "CRAFTBOT_MIRRORS": "https://github.com/=https://a.example/; https://github.com/=https://b.example/"
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                downloads.mirror_url("https://github.com/x"), "https://a.example/x"
            )

    def test_os_proxy_reaches_env_only_children(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "urllib.request.getproxies", return_value={"https": "http://corp:8080"}
            ),
        ):
            self.assertEqual(
                downloads.system_proxy_env()["HTTPS_PROXY"], "http://corp:8080"
            )
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://mine:1"}, clear=True):
            self.assertEqual(downloads.system_proxy_env(), {})

    def test_explicit_rule_beats_hf_endpoint(self):
        env = {
            "HF_ENDPOINT": "https://hf-mirror.com",
            "CRAFTBOT_MIRRORS": "https://huggingface.co/=https://corp.example/hf/",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                downloads.mirror_url("https://huggingface.co/x"),
                "https://corp.example/hf/x",
            )


class InterpreterPolicyTests(unittest.TestCase):
    """Only the private Python, or one the caller pinned, is ever installed into."""

    def _ctx(self, state_root, service_python=None):
        return Context(
            code_root=str(REPO), state_root=state_root, service_python=service_python
        )

    def test_default_context_pins_nothing(self):
        self.assertIsNone(default_context().service_python)

    def test_current_and_path_interpreters_are_never_accepted(self):
        with tempfile.TemporaryDirectory() as state:
            with patch.object(
                sys, "version_info", (TARGET_PYTHON[0], TARGET_PYTHON[1], 0)
            ):
                result = PythonStage().check(self._ctx(state))
        self.assertEqual(result.status, Status.MISSING)

    def test_pinned_interpreter_of_the_right_line_is_accepted(self):
        with tempfile.TemporaryDirectory() as state:
            with patch(
                "app.provision.runtimes._probe_python", return_value=TARGET_PYTHON
            ):
                ctx = self._ctx(state, ["/opt/python3.10"])
                result = PythonStage().check(ctx)
        self.assertEqual(result.status, Status.SATISFIED)
        self.assertEqual(ctx.service_python, ["/opt/python3.10"])

    def test_pinned_interpreter_of_the_wrong_line_fails_and_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as state:
            with patch("app.provision.runtimes._probe_python", return_value=(3, 13)):
                ctx = self._ctx(state, ["/usr/bin/python3.13"])
                self.assertEqual(PythonStage().check(ctx).status, Status.FAILED)
                self.assertEqual(
                    PythonStage().apply(ctx, lambda _m: None).status, Status.FAILED
                )

    def test_existing_private_python_is_used(self):
        with tempfile.TemporaryDirectory() as state:
            stage = PythonStage()
            exe = stage._sidecar_exe(self._ctx(state))
            exe.parent.mkdir(parents=True)
            exe.write_text("")
            with patch(
                "app.provision.runtimes._probe_python", return_value=TARGET_PYTHON
            ):
                ctx = self._ctx(state)
                result = stage.check(ctx)
        self.assertEqual(result.status, Status.SATISFIED)
        self.assertEqual(ctx.service_python, [str(exe)])

    def test_resolve_never_hops_to_a_stray_system_python(self):
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("CRAFTBOT_PYTHON", "CONDA_PREFIX")
        }
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(python_runtime, "recorded", return_value=None),
            patch.object(python_runtime, "private_python", return_value=None),
        ):
            self.assertIsNone(python_runtime.resolve(refresh=True))
        python_runtime.resolve(refresh=True)

    def test_isolated_env_strips_foreign_python_and_pip_settings(self):
        base = {
            "PATH": "/bin",
            "PYTHONHOME": "C:/ArcGIS/Pro/bin/Python",
            "PYTHONPATH": "/somewhere",
            "PIP_REQUIRE_VIRTUALENV": "true",
            "PIP_USER": "1",
            "PIP_INDEX_URL": "https://mirror.example/simple",
            "PIP_CERT": "/corp.pem",
            "VIRTUAL_ENV": "/venv",
        }
        env = python_runtime.isolated_env(base)
        for gone in (
            "PYTHONHOME",
            "PYTHONPATH",
            "PIP_REQUIRE_VIRTUALENV",
            "PIP_USER",
            "VIRTUAL_ENV",
        ):
            self.assertNotIn(gone, env)
        self.assertEqual(env["PIP_INDEX_URL"], "https://mirror.example/simple")
        self.assertEqual(env["PIP_CERT"], "/corp.pem")
        self.assertEqual(env["PYTHONNOUSERSITE"], "1")
        self.assertEqual(env["PYTHONUTF8"], "1")


class NodeNetworkTests(unittest.TestCase):
    def test_child_env_honours_proxy_and_system_ca_once(self):
        env = {
            "PATH": os.environ.get("PATH", ""),
            "NODE_OPTIONS": "--max-old-space-size=4096",
            "NO_PROXY": "corp.local",
        }
        node24 = node_runtime.NodeRuntime("node", None, ".", "v24.19.0", "path")
        with (
            patch.dict(os.environ, env, clear=True),
            patch.object(node_runtime, "path_env", return_value={}),
            patch.object(node_runtime, "resolve", return_value=node24),
        ):
            child = node_runtime.child_env()
            again = node_runtime.child_env({"NODE_OPTIONS": child["NODE_OPTIONS"]})
        self.assertEqual(child["NODE_USE_ENV_PROXY"], "1")
        self.assertEqual(child["NODE_OPTIONS"].count("--use-system-ca"), 1)
        self.assertIn("--max-old-space-size=4096", child["NODE_OPTIONS"])
        self.assertEqual(again["NODE_OPTIONS"].count("--use-system-ca"), 1)
        for host in ("corp.local", "localhost", "127.0.0.1", "::1"):
            self.assertIn(host, child["NO_PROXY"])

    def test_old_or_unknown_node_never_gets_the_system_ca_flag(self):
        for version in ("v20.11.0", None):
            old = node_runtime.NodeRuntime("node", None, ".", version, "path")
            with (
                patch.dict(os.environ, {"PATH": ""}, clear=True),
                patch.object(node_runtime, "path_env", return_value={}),
                patch.object(node_runtime, "resolve", return_value=old),
            ):
                child = node_runtime.child_env()
            self.assertNotIn("--use-system-ca", child.get("NODE_OPTIONS", ""))


class LockCoverageTests(unittest.TestCase):
    """Every platform an installer ships for has a lock, and no lock drags in
    torch, CUDA or docling again."""

    def _generate_lock(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_genlock", REPO / "scripts" / "generate_lock.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_every_shipped_platform_has_a_lock(self):
        genlock = self._generate_lock()
        for key in genlock.SHIPPED_PLATFORMS:
            path = Path(genlock.lock_path(key))
            self.assertTrue(path.is_file(), f"missing {path.name}")

    def test_lock_names_match_what_the_installer_reads(self):
        from app.provision import locktag

        genlock = self._generate_lock()
        expected = {
            "win_amd64": locktag.build("win-amd64", "AMD64", *TARGET_PYTHON),
            "linux_x86_64": locktag.build("linux-x86_64", "x86_64", *TARGET_PYTHON),
            "linux_aarch64": locktag.build("linux-aarch64", "aarch64", *TARGET_PYTHON),
            "macosx_arm64": locktag.build("macosx-14.0-arm64", "arm64", *TARGET_PYTHON),
            "macosx_x86_64": locktag.build(
                "macosx-10.13-universal2", "x86_64", *TARGET_PYTHON
            ),
        }
        for key, tag in expected.items():
            self.assertEqual(genlock.lock_tag(key), tag)

    def test_no_lock_pins_torch_cuda_or_docling(self):
        banned = re.compile(
            r"^(torch|torchvision|triton|nvidia-[\w-]+|docling[\w-]*|sentence-transformers|transformers)==",
            re.M | re.I,
        )
        for path in (REPO / "requirements").glob("lock-*.txt"):
            hits = banned.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{path.name} pins {hits}")

    def test_every_pin_is_hashed(self):
        for path in (REPO / "requirements").glob("lock-*.txt"):
            text = path.read_text(encoding="utf-8")
            blocks = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text)
            for block in blocks:
                if re.match(r"[A-Za-z0-9_.-]+==", block):
                    self.assertIn(
                        "--hash=sha256:", block, f"{path.name}: {block.splitlines()[0]}"
                    )


class EmbeddingModelManifestTests(unittest.TestCase):
    def test_model_files_are_pinned_https_and_hashed(self):
        files = embedding_model.pins()["files"]
        self.assertEqual(set(files), {"model.onnx", "tokenizer.json"})
        for item in files.values():
            self.assertTrue(item["url"].startswith("https://huggingface.co/"))
            self.assertNotIn(
                "/resolve/main/", item["url"]
            )  # a revision, never a branch
            self.assertEqual(len(item["sha256"]), 64)

    def test_embedding_model_is_provisioned_at_install(self):
        names = [stage.name for stage in default_stages()]
        self.assertIn("embedding-model", names)
        stage = next(s for s in default_stages() if s.name == "embedding-model")
        self.assertFalse(stage.optional)


class LauncherPythonCompatTests(unittest.TestCase):
    """The scripts a user runs with WHATEVER Python they have must parse and
    import on 3.8: install.py crashed on `list[str]` before it could even say
    which version it wanted."""

    FILES = [
        "install.py",
        "craftbot.py",
        "app/python_runtime.py",
        "app/paths.py",
        "app/downloads.py",
        "app/node_runtime.py",
        "app/embedding_model.py",
        *[str(p.relative_to(REPO)) for p in (REPO / "app" / "provision").glob("*.py")],
        *[str(p.relative_to(REPO)) for p in (REPO / "installer").glob("*.py")],
    ]

    PEP585 = re.compile(r"(?::|->)\s*(?:list|dict|tuple|set|type)\[")

    def test_parses_with_python_38_grammar(self):
        for rel in self.FILES:
            source = (REPO / rel).read_text(encoding="utf-8")
            ast.parse(source, filename=rel, feature_version=(3, 8))

    def test_builtin_generic_annotations_are_postponed(self):
        for rel in self.FILES:
            source = (REPO / rel).read_text(encoding="utf-8")
            if self.PEP585.search(source):
                self.assertIn("from __future__ import annotations", source, rel)


if __name__ == "__main__":
    unittest.main()
