"""grep_files runs ripgrep: line results, root-relative paths, .gitignore, limit.

These drive the real bundled rg binary; they skip only on a platform CraftBot
bundles no ripgrep for.
"""

import tracemalloc

import pytest

from app import ripgrep_runtime
from app.data.action.grep_files import grep_files


@pytest.fixture(scope="module", autouse=True)
def _ripgrep():
    try:
        ripgrep_runtime.binary_path()
    except RuntimeError as e:  # pragma: no cover - platform dependent
        pytest.skip(str(e))


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_returns_matching_lines_with_paths_relative_to_the_folder(tmp_path):
    _write(tmp_path / "src" / "a.py", "import os\ndef hello():\n    pass\n")
    _write(tmp_path / "src" / "b.py", "def world():\n")

    res = grep_files({"pattern": r"def \w+\(", "path": str(tmp_path)})

    assert res["status"] == "success"
    lines = sorted(res["content"].splitlines())
    assert lines == ["src/a.py:2: def hello():", "src/b.py:1: def world():"]
    assert res["num_matches"] == 2
    assert res["num_files"] == 2
    assert res["truncated"] is False
    assert str(tmp_path) in res["message"]


def test_folder_search_honours_gitignore_outside_a_git_checkout(tmp_path):
    _write(tmp_path / ".gitignore", "generated/\n")
    _write(tmp_path / "generated" / "big.json", '{"needle": 1}\n')
    _write(tmp_path / "src" / "keep.ts", "const needle = 1\n")

    res = grep_files({"pattern": "needle", "path": str(tmp_path)})

    assert res["content"] == "src/keep.ts:1: const needle = 1"


def test_an_ignored_file_is_still_searched_when_named_directly(tmp_path):
    _write(tmp_path / ".gitignore", "generated/\n")
    target = tmp_path / "generated" / "big.json"
    _write(target, '{"needle": 1}\n')

    res = grep_files({"pattern": "needle", "path": str(target)})

    assert res["content"] == 'big.json:1: {"needle": 1}'
    assert res["num_files"] == 1


def test_stops_at_limit_and_says_so(tmp_path):
    _write(tmp_path / "log.txt", "".join(f"hit {i}\n" for i in range(500)))

    res = grep_files({"pattern": "hit", "path": str(tmp_path), "limit": 10})

    assert res["status"] == "success"
    assert res["num_matches"] == 10
    assert len(res["content"].splitlines()) == 10
    assert res["truncated"] is True
    assert "limit of 10" in res["message"]


def test_context_lines_and_group_separators(tmp_path):
    body = "\n".join(["a", "b", "MATCH one", "c", "d", "e", "f", "g", "MATCH two", "h"])
    _write(tmp_path / "f.txt", body + "\n")

    res = grep_files({"pattern": "MATCH", "path": str(tmp_path), "context": 1})

    assert res["content"].splitlines() == [
        "f.txt-2- b",
        "f.txt:3: MATCH one",
        "f.txt-4- c",
        "--",
        "f.txt-8- g",
        "f.txt:9: MATCH two",
        "f.txt-10- h",
    ]
    assert res["num_matches"] == 2


def test_limit_with_context_keeps_trailing_context_but_not_the_next_lead_in(tmp_path):
    body = "\n".join(["MATCH one", "after one", "x", "before two", "MATCH two"])
    _write(tmp_path / "f.txt", body + "\n")

    res = grep_files(
        {"pattern": "MATCH", "path": str(tmp_path), "context": 1, "limit": 1}
    )

    assert res["content"].splitlines() == ["f.txt:1: MATCH one", "f.txt-2- after one"]
    assert res["truncated"] is True


def test_glob_filters_files(tmp_path):
    _write(tmp_path / "a.py", "needle\n")
    _write(tmp_path / "a.md", "needle\n")

    res = grep_files({"pattern": "needle", "path": str(tmp_path), "glob": "*.py"})

    assert res["content"] == "a.py:1: needle"


def test_ignore_case(tmp_path):
    _write(tmp_path / "a.txt", "Needle\n")

    assert grep_files({"pattern": "needle", "path": str(tmp_path)})["num_matches"] == 0
    res = grep_files({"pattern": "needle", "path": str(tmp_path), "ignore_case": True})
    assert res["content"] == "a.txt:1: Needle"


def test_long_lines_are_cut(tmp_path):
    _write(tmp_path / "bundle.js", "needle" + "x" * 5000 + "\n")

    res = grep_files({"pattern": "needle", "path": str(tmp_path)})

    line = res["content"]
    assert line.startswith("bundle.js:1: needle")
    assert line.endswith("[line cut]")
    assert len(line) < 600
    assert "cut to 500 characters" in res["message"]


def _peak_bytes(call):
    tracemalloc.start()
    try:
        result = call()
        return result, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


def test_a_minified_line_with_many_occurrences_stays_small(tmp_path):
    # 250,000 occurrences on one line: rg's --json described each of them and
    # took over 100 MB to parse.
    _write(tmp_path / "bundle.min.js", "a=1;" * 250_000 + "\n")

    res, peak = _peak_bytes(
        lambda: grep_files({"pattern": "a", "path": str(tmp_path), "limit": 1})
    )

    assert res["content"].startswith("bundle.min.js:1: a=1;")
    assert res["content"].endswith("[line cut]")
    assert peak < 2_000_000


def test_content_budget_applies_while_reading(tmp_path):
    _write(tmp_path / "log.txt", "hit\n" * 300_000)

    res, peak = _peak_bytes(
        lambda: grep_files(
            {"pattern": "hit", "path": str(tmp_path), "limit": 1_000_000}
        )
    )

    assert res["truncated"] is True
    assert "Output capped at 40000 characters" in res["message"]
    assert len(res["content"]) <= 40000
    assert peak < 2_000_000


def test_a_line_of_exactly_500_wide_characters_is_not_cut(tmp_path):
    # 2,000 bytes plus a CRLF ending: rg counts the ending against its byte
    # cap, so the cap leaves room for it.
    line = "\U0001f600" * 500
    target = tmp_path / "wide.txt"
    target.write_bytes((line + "\r\n").encode("utf-8"))

    res = grep_files({"pattern": ".", "path": str(target)})

    assert res["content"] == f"wide.txt:1: {line}"
    assert "cut to 500 characters" not in res["message"]


def test_a_binary_file_named_directly_is_still_searched(tmp_path):
    target = tmp_path / "data.bin"
    target.write_bytes(b"needle one\n\x00\nneedle two\n")

    res = grep_files({"pattern": "needle", "path": str(target)})

    assert res["content"].splitlines() == [
        "data.bin:1: needle one",
        "data.bin:3: needle two",
    ]


def test_no_match_explains_what_a_folder_search_skips(tmp_path):
    _write(tmp_path / "a.txt", "nothing here\n")

    res = grep_files({"pattern": "needle", "path": str(tmp_path)})

    assert res["status"] == "success"
    assert res["content"] == ""
    assert res["num_matches"] == 0
    assert ".gitignore" in res["message"]


def test_invalid_regex_is_an_error(tmp_path):
    _write(tmp_path / "a.txt", "x\n")

    res = grep_files({"pattern": "foo(", "path": str(tmp_path)})

    assert res["status"] == "error"
    assert "regex parse error" in res["message"]


def test_missing_path_is_an_error(tmp_path):
    res = grep_files({"pattern": "x", "path": str(tmp_path / "nope")})

    assert res["status"] == "error"
    assert "does not exist" in res["message"]


def test_pattern_is_required(tmp_path):
    assert grep_files({"path": str(tmp_path)})["status"] == "error"
