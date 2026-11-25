"""Block banned terms in file contents, file paths, commit messages and branch names.

Terms are stored base64-encoded so this file does not contain them.

Usage:
  term_guard.py files [PATH ...]   check contents and paths of the given files (default: all tracked files)
  term_guard.py msg FILE           check a commit message file (commit-msg hook)
  term_guard.py history            check every commit message, author and path in the full history
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
from pathlib import Path

_ENCODED = ("Y2xhdWRl", "YW50aHJvcGlj", "b3B1cw==")
_PATTERN = re.compile("|".join(base64.b64decode(t).decode() for t in _ENCODED), re.IGNORECASE)


def find(text: str) -> list[str]:
    return [m.group(0) for m in _PATTERN.finditer(text)]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def check_files(paths: list[str]) -> list[str]:
    problems: list[str] = []
    if not paths:
        paths = [p for p in _git("ls-files", "-z").split("\0") if p]
    for p in paths:
        if find(p):
            problems.append(f"path: {p}")
        path = Path(p)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if find(line):
                problems.append(f"content: {p}:{n}")
    return problems


def check_message(text: str, label: str) -> list[str]:
    return [f"{label}: {line.strip()[:80]}" for line in text.splitlines() if find(line)]


def check_history() -> list[str]:
    problems: list[str] = []
    log = _git("log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e")
    for entry in filter(str.strip, log.split("\x1e")):
        sha, *fields = entry.strip().split("\0")
        problems += check_message("\n".join(fields), f"commit {sha[:10]}")
    paths = _git("log", "--all", "--name-only", "--format=")
    problems += [f"history path: {p}" for p in sorted(set(paths.split())) if find(p)]
    for ref in _git("for-each-ref", "--format=%(refname)").split():
        if find(ref):
            problems.append(f"ref: {ref}")
    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "files":
        problems = check_files(rest)
    elif cmd == "msg":
        problems = check_message(Path(rest[0]).read_text(encoding="utf-8"), "commit message")
    elif cmd == "history":
        problems = check_history()
    else:
        print(__doc__)
        return 2
    for p in problems:
        print(f"banned term found -> {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
