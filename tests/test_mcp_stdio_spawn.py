"""Argument handling when launching a stdio MCP server.

An MCP server's command and args come from configuration, and configuration
is editable in the UI, importable from a profile bundle and writable by the
agent itself. So the args are not trusted input, and the spawn must not let
one of them turn into a second command.

The old code built a shell string --  f'"{command}" ' + " ".join(f'"{a}"') --
and handed it to create_subprocess_shell, so a single embedded quote closed
the quoting and everything after it ran. Two things replace it: the argument
list goes to the OS as a list, and the one case a list cannot make safe
(a Windows .cmd/.bat wrapper, which cmd.exe re-parses no matter how it is
spawned) is refused up front.
"""

import sys

import pytest

from agent_core.core.impl.mcp.server import _reject_unsafe_batch_args

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32", reason="cmd.exe argument re-parsing is Windows-only"
)

# Each of these ran a second command through the old shell-string build.
INJECTIONS = [
    'x" & echo pwned & rem ',
    "y & echo pwned",
    "z | echo pwned",
    "w > pwned.txt",
    "a < pwned.txt",
    'q" && echo pwned',
    "line1\nline2",
    "line1\r\nline2",
]

# Ordinary MCP arguments. None may be refused.
LEGITIMATE = [
    "-y",
    "@modelcontextprotocol/server-filesystem",
    "https://example.com/a%20b",
    "%APPDATA%",
    "C:\\Users\\someone\\My Documents",
    "--port=3000",
    "a-file_name.v2.json",
    "",
]


@WINDOWS_ONLY
@pytest.mark.parametrize("arg", INJECTIONS)
def test_batch_wrapper_refuses_an_injecting_argument(arg):
    with pytest.raises(ValueError) as excinfo:
        _reject_unsafe_batch_args("C:\\tools\\npx.cmd", [arg])
    # The message has to tell the user what to do, not just that it failed.
    assert "npx.cmd" in str(excinfo.value)


@WINDOWS_ONLY
@pytest.mark.parametrize("arg", LEGITIMATE)
def test_batch_wrapper_accepts_ordinary_arguments(arg):
    _reject_unsafe_batch_args("C:\\tools\\npx.cmd", [arg])


@WINDOWS_ONLY
def test_a_url_with_a_query_string_is_refused_on_a_batch_wrapper():
    """This one deserves stating plainly, because it looks like a false
    positive and is not: cmd.exe splits on '&' while running the wrapper, so
    `https://h/p?a=1&b=2` does not survive the trip whatever we do. Refusing
    it with an explanation beats delivering a silently truncated URL. Against
    a real executable the same argument is fine -- see the test below."""
    with pytest.raises(ValueError):
        _reject_unsafe_batch_args("C:\\tools\\npx.cmd", ["https://h/p?a=1&b=2"])

    _reject_unsafe_batch_args("C:\\tools\\node.exe", ["https://h/p?a=1&b=2"])


@WINDOWS_ONLY
def test_percent_is_allowed_so_encoded_urls_still_work():
    """'%' can expand an environment variable, but only into a value the same
    config already controls -- and refusing it would reject every
    percent-encoded URL, which is an ordinary argument."""
    _reject_unsafe_batch_args("C:\\tools\\npx.cmd", ["https://example.com/a%20b"])
    _reject_unsafe_batch_args("C:\\tools\\npx.cmd", ["%APPDATA%"])


@WINDOWS_ONLY
def test_caret_is_allowed_because_it_cannot_start_a_command():
    _reject_unsafe_batch_args("C:\\tools\\npx.cmd", ["a^b"])


@WINDOWS_ONLY
@pytest.mark.parametrize("arg", INJECTIONS)
@pytest.mark.parametrize("exe", ["C:\\tools\\node.exe", "C:\\tools\\server"])
def test_real_executables_accept_anything(exe, arg):
    """A list argument reaches a real executable untouched, so there is
    nothing to refuse -- narrowing the check to batch wrappers keeps it from
    rejecting arguments that were never dangerous."""
    _reject_unsafe_batch_args(exe, [arg])


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX has no batch wrappers")
@pytest.mark.parametrize("arg", INJECTIONS)
def test_posix_never_refuses(arg):
    _reject_unsafe_batch_args("/usr/bin/npx", [arg])
    _reject_unsafe_batch_args("/usr/local/bin/some.cmd", [arg])


@WINDOWS_ONLY
def test_extension_match_is_case_insensitive():
    with pytest.raises(ValueError):
        _reject_unsafe_batch_args("C:\\tools\\NPX.CMD", ["a & b"])
    with pytest.raises(ValueError):
        _reject_unsafe_batch_args("C:\\tools\\run.BAT", ["a | b"])


@WINDOWS_ONLY
def test_every_argument_is_checked_not_just_the_first():
    with pytest.raises(ValueError):
        _reject_unsafe_batch_args("C:\\tools\\npx.cmd", ["-y", "ok", "bad & echo x"])
