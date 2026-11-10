"""Report console visibility from a real three-generation Windows process tree."""

import ctypes
import json
import subprocess
import sys
from pathlib import Path


def main():
    depth, output = int(sys.argv[1]), sys.argv[2]
    kernel, user = ctypes.windll.kernel32, ctypes.windll.user32
    kernel.GetConsoleWindow.restype = ctypes.c_void_p
    user.IsWindowVisible.argtypes = [ctypes.c_void_p]
    console = kernel.GetConsoleWindow()
    record = json.dumps(
        {"console": console, "visible": bool(user.IsWindowVisible(console))}
    )
    if output == "-":
        print(record, flush=True)
    else:
        with Path(output).open("a", encoding="utf-8") as stream:
            stream.write(record + "\n")
    if depth:
        # No hiding flags here: the child must inherit the launcher's hidden
        # console, as ordinary Python/git/npm child commands would.
        subprocess.run(
            [sys.executable, __file__, str(depth - 1), output], check=True, timeout=10
        )


if __name__ == "__main__":
    main()
