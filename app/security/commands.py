"""Commands the agent may never run. Always on.

Hermes Agent's "hardline floor": a few commands do damage no approval can
undo, so they are refused outright, whatever the level or Auto mode says,
and no setting turns this off. The floor is judged on the parsed command,
not on its text: the line is tokenized the way a POSIX shell reads it
(quotes, escapes, comments, line continuations, newlines between commands
and here-document bodies), wrappers such as ``sudo`` and leading
``VAR=value`` assignments are set aside, and each command is judged by its
program and arguments. Where it matters, the target is looked up on disk (a
disk device is recognized by its file type).

Refused:

- deleting, or recursively changing the owner or permissions of, a
  top-level location: ``/``, a folder directly under it, or the home folder
  (``rm -rf ~``, ``chmod -R 777 /``), and any ``--no-preserve-root``;
- writing to a disk device (``dd of=/dev/sda``, ``> /dev/nvme0n1``) or
  formatting one (``mkfs``, ``wipefs``);
- a fork bomb (a shell function that starts itself twice in the background);
- on Windows: formatting a drive, and recursively removing a drive root or
  the user's profile folder.

A command whose quotes do not balance is left to the shell, which refuses
to run it. Like Hermes' floor, this is a backstop for the worst mistakes,
not a sandbox: approving commands (Auto mode off) is what reviews everything
else.
"""

from __future__ import annotations

import os
import shlex
import stat
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Sequence, Tuple

_SEPARATORS = {";", "&", "&&", "||", "|", "|&", "(", ")", ";;", "\n"}
# Longest first, so "&&" wins over "&".
_OPERATORS = (
    "<<-", "<<<", "&&", "||", ";;", "|&", ">>", ">|", "<<", "<&", ">&", "&>", "<>",
    ";", "&", "|", "(", ")", "<", ">",
)
_HEREDOC = {"<<", "<<-"}
_REDIRECTS = {">", ">>", ">|", "&>", "<", "<&", ">&", "<>", "<<<"}
_WRITE_REDIRECTS = {">", ">>", ">|", "&>", "<>"}
_WRAPPERS = {"sudo", "doas", "env", "nice", "nohup", "time", "command", "exec", "stdbuf", "ionice", "timeout"}
# Options of the wrappers that take a value (so the value is not the program).
_WRAPPER_OPTIONS_WITH_VALUE = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"},
    "doas": {"-u", "-C"},
    "nice": {"-n"},
    "ionice": {"-c", "-n"},
    "stdbuf": {"-i", "-o", "-e"},
    "timeout": {"-s", "-k"},
}
_FORMATTERS_PREFIX = ("mkfs",)
_FORMATTERS = {"mke2fs", "mkswap", "wipefs", "sfdisk", "sgdisk"}


class _Unparseable(ValueError):
    pass


def _tokens(command: str) -> List[str]:
    """Words and operators of a POSIX shell command line; a newline between
    commands is a "\\n" token. Here-document bodies are data and skipped."""
    tokens: List[str] = []
    word: Optional[List[str]] = None
    heredocs: List[Tuple[str, bool]] = []
    expect_delimiter: Optional[bool] = None  # set after << / <<-: strip tabs?
    i, n = 0, len(command)

    def end_word() -> None:
        nonlocal word, expect_delimiter
        if word is None:
            return
        text = "".join(word)
        word = None
        if expect_delimiter is not None:
            heredocs.append((text, expect_delimiter))
            expect_delimiter = None
        tokens.append(text)

    while i < n:
        ch = command[i]
        if ch == "\\":
            if command.startswith("\\\n", i):
                i += 2  # line continuation
                continue
            word = word if word is not None else []
            word.append(command[i + 1] if i + 1 < n else "\\")
            i += 2
            continue
        if ch == "'":
            end = command.find("'", i + 1)
            if end < 0:
                raise _Unparseable("unbalanced quotes")
            word = word if word is not None else []
            word.extend(command[i + 1 : end])
            i = end + 1
            continue
        if ch == '"':
            j, text = i + 1, []
            while j < n and command[j] != '"':
                if command[j] == "\\" and j + 1 < n and command[j + 1] in '"\\$`\n':
                    if command[j + 1] != "\n":
                        text.append(command[j + 1])
                    j += 2
                    continue
                text.append(command[j])
                j += 1
            if j >= n:
                raise _Unparseable("unbalanced quotes")
            word = word if word is not None else []
            word.extend(text)
            i = j + 1
            continue
        if ch == "#" and word is None:
            end = command.find("\n", i)
            i = n if end < 0 else end  # a comment runs to the end of the line
            continue
        if ch == "\n":
            end_word()
            tokens.append("\n")
            i += 1
            for delimiter, strip_tabs in heredocs:
                while i < n:
                    end = command.find("\n", i)
                    line = command[i : n if end < 0 else end]
                    i = n if end < 0 else end + 1
                    if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                        break
            heredocs = []
            continue
        if ch in " \t\r":
            end_word()
            i += 1
            continue
        operator = next((op for op in _OPERATORS if command.startswith(op, i)), None)
        if operator:
            end_word()
            tokens.append(operator)
            i += len(operator)
            if operator in _HEREDOC:
                expect_delimiter = operator == "<<-"
            continue
        word = word if word is not None else []
        word.append(ch)
        i += 1
    end_word()
    return tokens


def _split(tokens: Sequence[str]) -> List[List[str]]:
    """Simple commands."""
    commands: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            commands.append(current)
            current = []
        else:
            current.append(token)
    commands.append(current)
    return [argv for argv in commands if argv]


def _without_redirections(argv: Sequence[str]) -> Tuple[List[str], List[str]]:
    """The command's words, and the files it redirects output into."""
    words: List[str] = []
    written: List[str] = []
    i = 0
    while i < len(argv):
        token = argv[i]
        if token in _REDIRECTS or token in _HEREDOC:
            if words and words[-1].isdigit():
                words.pop()  # the file descriptor of "2>"
            if token in _WRITE_REDIRECTS and i + 1 < len(argv):
                written.append(argv[i + 1])
            i += 2
            continue
        words.append(token)
        i += 1
    return words, written


def _is_assignment(word: str) -> bool:
    name, equals, _ = word.partition("=")
    return bool(equals) and bool(name) and (name[0].isalpha() or name[0] == "_") and name.replace("_", "").isalnum()


def _unwrap(argv: List[str]) -> List[str]:
    """The command under any wrappers and VAR=value prefixes."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if _is_assignment(word):
            i += 1
            continue
        name = os.path.basename(word)
        if name not in _WRAPPERS:
            break
        i += 1
        takes_value = _WRAPPER_OPTIONS_WITH_VALUE.get(name, set())
        while i < len(argv) and argv[i].startswith("-"):
            option = argv[i]
            i += 1
            if option == "--":
                break
            if option in takes_value and i < len(argv):
                i += 1
        if name == "timeout" and i < len(argv):
            i += 1  # the duration
    return argv[i:]


def _home() -> Path:
    return Path(os.path.expanduser("~")).resolve()


def _resolve(target: str) -> Path:
    target = target.replace("${HOME}", "~").replace("$HOME", "~")
    if target.endswith("/*"):
        target = target[:-2] or "/"
    return Path(os.path.abspath(os.path.expanduser(target)))


def _top_level(target: str) -> bool:
    path = _resolve(target)
    root = Path(path.anchor or "/")
    return path == root or path.parent == root or path == _home()


def _is_block_device(target: str) -> bool:
    try:
        return stat.S_ISBLK(os.stat(os.path.realpath(target)).st_mode)
    except OSError:
        return False


def _flags(args: Sequence[str]) -> Tuple[set, List[str]]:
    short, operands = set(), []
    for arg in args:
        if arg.startswith("--"):
            short.add(arg)
        elif arg.startswith("-") and len(arg) > 1:
            short.update(arg[1:])
        else:
            operands.append(arg)
    return short, operands


def _posix_refusal(argv: List[str], written: List[str]) -> Optional[str]:
    if any(_is_block_device(target) for target in written):
        return "it writes directly to a disk device"
    if not argv:
        return None
    program = os.path.basename(argv[0])
    args = argv[1:]
    flags, operands = _flags(args)
    if program == "rm":
        recursive = bool({"r", "R", "--recursive"} & flags)
        if "--no-preserve-root" in flags:
            return "it deletes with --no-preserve-root"
        if recursive and any(_top_level(t) for t in operands):
            return "it deletes a top-level folder or your home folder"
    if program in ("chmod", "chown", "chgrp"):
        if {"R", "--recursive"} & flags and any(_top_level(t) for t in operands[1:] or operands):
            return f"it recursively changes {program[2:]} of a top-level folder"
        if "--no-preserve-root" in flags:
            return f"it runs {program} with --no-preserve-root"
    if program.startswith(_FORMATTERS_PREFIX) or program in _FORMATTERS:
        if any(_is_block_device(t) for t in operands) or not operands:
            return "it formats or wipes a disk"
    if program == "dd":
        for arg in args:
            if arg.startswith("of=") and _is_block_device(arg[3:]):
                return "it writes directly to a disk device"
    return None


def _fork_bomb(tokens: Sequence[str]) -> bool:
    """name() { … name | name & … } — a function that starts itself twice
    in the background."""
    for i in range(len(tokens) - 3):
        name = tokens[i]
        if tokens[i + 1 : i + 3] != ["(", ")"] or not tokens[i + 3].startswith("{"):
            continue
        depth, body = 0, []
        for token in tokens[i + 3 :]:
            depth += token.count("{") - token.count("}")
            body.append(token)
            if depth <= 0:
                break
        calls = sum(1 for t in body if t.strip("{}") == name)
        if calls >= 2 and "&" in body:
            return True
    return False


def posix_refusal(command: str) -> Optional[str]:
    tokens = _tokens(command)
    if _fork_bomb(tokens):
        return "it is a fork bomb"
    for argv in _split(tokens):
        words, written = _without_redirections(argv)
        why = _posix_refusal(_unwrap(words), written)
        if why:
            return why
    return None


# ── Windows (cmd.exe and PowerShell) ──

_PS_REMOVE = {"remove-item", "rm", "ri", "del", "erase", "rd", "rmdir"}
_PS_DISK = {"format-volume", "clear-disk", "initialize-disk", "remove-partition"}


def _windows_root(target: str) -> bool:
    target = target.strip("'\"")
    expanded = os.path.expandvars(target.replace("$env:USERPROFILE", "%USERPROFILE%").replace("$HOME", "~"))
    expanded = os.path.expanduser(expanded)
    path = PureWindowsPath(expanded)
    if path.anchor and str(path).rstrip("\\/") in (path.drive, path.anchor.rstrip("\\/")):
        return True
    profile = os.environ.get("USERPROFILE")
    return bool(profile) and PureWindowsPath(profile) == path


def windows_refusal(command: str) -> Optional[str]:
    lexer = shlex.shlex(command, posix=False, punctuation_chars="&|;()\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        raise _Unparseable("unbalanced quotes") from None
    for argv in _split(tokens):
        program = argv[0].lower().rsplit("\\", 1)[-1].removesuffix(".exe")
        args = list(argv[1:])
        lowered = [a.lower() for a in args]
        operands = [a for a in args if not a.startswith(("-", "/"))]
        if program == "format" and operands:
            return "it formats a drive"
        if program in _PS_DISK:
            return "it formats or clears a disk"
        if program in ("rd", "rmdir") and "/s" in lowered and any(_windows_root(t) for t in operands):
            return "it removes a drive root or your profile folder"
        if program in _PS_REMOVE and "-recurse" in lowered and any(_windows_root(t) for t in operands):
            return "it removes a drive root or your profile folder"
        if program == "del" and "/s" in lowered and any(_windows_root(t) for t in operands):
            return "it deletes everything on a drive"
    return None


def refusal(command: str, *, windows: bool = False) -> Optional[str]:
    """None when the command may run; otherwise the reason, for the agent."""
    if not command.strip():
        return None
    try:
        why = windows_refusal(command) if windows else posix_refusal(command)
    except _Unparseable:
        return None  # the shell itself refuses a command whose quotes don't balance
    if not why:
        return None
    from app.security import audit

    audit.record("command_blocked", reason=why)
    return (
        f"Not run: {why}. CraftBot never runs commands that do damage no "
        f"approval can undo. If this really is needed, ask the user to run it."
    )
