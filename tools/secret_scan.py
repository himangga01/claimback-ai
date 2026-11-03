"""Secret scan for ClaimBack-AI.

Scans repository files (tracked plus untracked-but-not-ignored, or staged
files with --staged) for key-like strings and .env files present in the
worktree (tracked or untracked-but-not-ignored; .env and .env.* except
.env.example).

Prints file and line number only, never the matched value.
Exit code 1 when any finding exists, 0 when clean.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

RULES = [
    ("llm-key", re.compile(r"LLM_[A-Za-z0-9_-]{20,}")),
    ("sk-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
]

SKIP_SUFFIXES = {
    ".ttf", ".otf", ".woff", ".woff2", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".ico", ".pyc",
}


def _git_ls(args: list[str]) -> list[str]:
    proc = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise RuntimeError("git is required for secret_scan.py")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def repo_files(staged_only: bool) -> list[str]:
    if staged_only:
        return _git_ls(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    tracked = _git_ls(["ls-files"])
    untracked = _git_ls(["ls-files", "--others", "--exclude-standard"])
    return sorted(set(tracked) | set(untracked))


def is_dotenv_path(rel: str) -> bool:
    if rel == ".env":
        return True
    if rel.startswith(".env."):
        return rel != ".env.example"
    return False


def tracked_dotenv_files() -> list[str]:
    names = _git_ls(["ls-files", ".env*"])
    return sorted(n for n in names if is_dotenv_path(n))


def present_dotenv_files() -> list[str]:
    """Tracked plus untracked-but-not-ignored .env files (C9)."""
    names = repo_files(False)
    return sorted(n for n in names if is_dotenv_path(n))


def scan_file(rel: str) -> list[tuple[int, str]]:
    path = ROOT / rel
    if not path.is_file():
        return []
    if path.suffix.lower() in SKIP_SUFFIXES:
        return []
    try:
        data = path.read_bytes()
    except OSError:
        return []
    if b"\x00" in data[:8192]:
        return []
    findings = []
    text = data.decode("utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        for name, rx in RULES:
            if rx.search(line):
                findings.append((lineno, name))
                break
    return findings


def main(argv: list[str]) -> int:
    staged_only = "--staged" in argv or "--cached" in argv
    try:
        files = repo_files(staged_only)
    except RuntimeError as exc:
        print(f"secret_scan: {exc}", file=sys.stderr)
        return 2
    findings = 0
    if staged_only:
        for rel in sorted(f for f in files if is_dotenv_path(f)):
            print(f"{rel}: staged .env file must not be committed (rule: dotenv-tracked)")
            findings += 1
    else:
        for rel in present_dotenv_files():
            print(f"{rel}: tracked .env file must not be committed (rule: dotenv-tracked)")
            findings += 1
    for rel in files:
        if is_dotenv_path(rel):
            continue
        for lineno, rule in scan_file(rel):
            print(f"{rel}:{lineno}: possible secret (rule: {rule})")
            findings += 1
    if findings:
        print(f"secret_scan: {findings} finding(s)", file=sys.stderr)
        return 1
    print("secret_scan: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
