"""Commands the agent may never run (Settings > Security, Enhanced and Strict).

Hermes Agent's "hardline floor": a few commands do damage no approval can
undo, so they are refused outright, whatever Auto mode says. The floor is
judged on the parsed command, not on its text: the line is split into
commands the way a shell splits it (``shlex``), wrappers such as ``sudo``
and leading ``VAR=value`` assignments are set aside, and each command is
judged by its program and arguments. Where it matters, the target is
looked up on disk (a disk device is recognized by its file type).

Refused:

- deleting, or recursively changing the owner or permissions of, a
  top-level location: ``/``, a folder directly under it, or the home folder
  (``rm -rf ~``, ``chmod -R 777 /``), and any ``--no-preserve-root``;
- writing to a disk device (``dd of=/dev/sda``, ``> /dev/nvme0n1``) or
  formatting one (``mkfs``, ``wipefs``);
- piping a download into a shell running as root (``curl … | sudo sh``);
- a fork bomb (a shell function that starts itself twice in the background);
- on Windows: formatting a drive, and recursively removing a drive root or
  the user's profile folder.

A command that cannot be parsed (unbalanced quotes) is refused while the
floor is on, so an obfuscated command is not waved through.

Like Hermes' floor, this is a backstop for the worst mistakes, not a
sandbox: approving commands (Auto mode off) is what reviews everything else.
"""

from __future__ import annotations

import os
import shlex
import stat
from pathlib import Path, PureWindowsPath
from typing import List, Optional, Sequence, Tuple

from app.security.policy import get_policy

_SEPARATORS = {";", "&", "&&", "||", "|", "|&", "(", ")", ";;", "\n"}
_PIPE = {"|", "|&"}
_WRAPPERS = {"sudo", "doas", "env", "nice", "nohup", "time", "command", "exec", "stdbuf", "ionice", "timeout"}
_ROOT_WRAPPERS = {"sudo", "doas"}
# Options of the wrappers that take a value (so the value is not the program).
_WRAPPER_OPTIONS_WITH_VALUE = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"},
    "doas": {"-u", "-C"},
    "nice": {"-n"},
    "ionice": {"-c", "-n"},
    "stdbuf": {"-i", "-o", "-e"},
    "timeout": {"-s", "-k"},
}
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "ash"}
_DOWNLOADERS = {"curl", "wget", "fetch", "aria2c"}
_FORMATTERS_PREFIX = ("mkfs",)
_FORMATTERS = {"mke2fs", "mkswap", "wipefs", "sfdisk", "sgdisk"}


class _Unparseable(ValueError):
    pass


def _tokens(command: str) -> List[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:  # unbalanced quotes
        raise _Unparseable(str(exc)) from None


def _split(tokens: Sequence[str]) -> List[Tuple[List[str], str]]:
    """Simple commands, each with the operator that ends it."""
    commands: List[Tuple[List[str], str]] = []
    current: List[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            commands.append((current, token))
            current = []
        else:
            current.append(token)
    commands.append((current, ""))
    return [(argv, op) for argv, op in commands if argv]


def _is_assignment(word: str) -> bool:
    name, equals, _ = word.partition("=")
    return bool(equals) and bool(name) and (name[0].isalpha() or name[0] == "_") and name.replace("_", "").isalnum()


def _unwrap(argv: List[str]) -> Tuple[List[str], bool]:
    """The command under any wrappers and VAR=value prefixes; True when it
    runs as root through sudo or doas."""
    as_root = False
    i = 0
    while i < len(argv):
        word = argv[i]
        if _is_assignment(word):
            i += 1
            continue
        name = os.path.basename(word)
        if name not in _WRAPPERS:
            break
        as_root = as_root or name in _ROOT_WRAPPERS
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
    return argv[i:], as_root


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


def _posix_refusal(argv: List[str]) -> Optional[str]:
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
    for i, token in enumerate(argv[:-1]):
        if token in (">", ">>", ">|") and _is_block_device(argv[i + 1]):
            return "it writes directly to a disk device"
    return None


def _fork_bomb(tokens: Sequence[str]) -> bool:
    """name() { … name | name & … } — a function that starts itself twice
    in the background."""
    for i in range(len(tokens) - 2):
        name = tokens[i]
        # The tokenizer gives "()" as one token, or "(" and ")" when spaced.
        if tokens[i + 1] == "()":
            start = i + 2
        elif tokens[i + 1 : i + 3] == ["(", ")"]:
            start = i + 3
        else:
            continue
        if start >= len(tokens) or not tokens[start].startswith("{"):
            continue
        depth, body = 0, []
        for token in tokens[start:]:
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
    pipeline_has_download = False
    for argv, operator in _split(tokens):
        inner, as_root = _unwrap(argv)
        if not inner:
            continue
        why = _posix_refusal(inner)
        if why:
            return why
        program = os.path.basename(inner[0])
        if pipeline_has_download and as_root and program in _SHELLS:
            return "it pipes a download into a shell running as root"
        if program in _DOWNLOADERS and operator in _PIPE:
            pipeline_has_download = True
        elif operator not in _PIPE:
            pipeline_has_download = False
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
    lexer = shlex.shlex(command, posix=False, punctuation_chars="&|;()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        raise _Unparseable("unbalanced quotes") from None
    for argv, _ in _split(tokens):
        program = argv[0].lower().rsplit("\\", 1)[-1].removesuffix(".exe")
        args = [a for a in argv[1:]]
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
    if not get_policy().block_destructive_commands or not command.strip():
        return None
    try:
        why = windows_refusal(command) if windows else posix_refusal(command)
    except _Unparseable:
        why = "it could not be read safely (unbalanced quotes)"
    if not why:
        return None
    from app.security import audit

    audit.record_if_enabled("command_blocked", reason=why)
    return (
        f"Not run: {why}. Settings > Security blocks commands that do damage no "
        f"approval can undo. If this really is needed, ask the user to run it."
    )
