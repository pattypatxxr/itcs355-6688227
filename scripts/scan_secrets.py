"""Scan the full git history for committed secrets. Refuses to run on a shallow clone."""
from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "aws access key id": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key block": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "azure storage key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}"),
    "azure sas signature": re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{30,}"),
    "hardcoded credential": re.compile(
        r"""(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*["'][^"'\s]{12,}["']"""
    ),
}
IGNORE_FILES = {"scripts/scan_secrets.py", "cloud.env.example"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          errors="replace", check=True).stdout


def main() -> int:
    if git("rev-parse", "--is-shallow-repository").strip() == "true":
        print("REFUSING: shallow clone. History beyond the checkout depth would go "
              "unscanned, so a clean result would mean nothing.\n"
              "In CI use actions/checkout with fetch-depth: 0.", file=sys.stderr)
        return 2

    tracked = [f for f in git("ls-files").splitlines() if f.endswith("cloud.env")]
    hits: set[tuple[str, str, str]] = {("-", f, "cloud.env is tracked by git") for f in tracked}

    commit = file = ""
    for line in git("log", "-p", "--all", "--no-color", "-U0").splitlines():
        if line.startswith("commit "):
            commit = line.split()[1][:10]
        elif line.startswith("+++ b/"):
            file = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and file not in IGNORE_FILES:
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    hits.add((commit, file, name))

    for commit, file, name in sorted(hits):
        print(f"FOUND  {name:<30} commit {commit}  {file}")
    if hits:
        print("\nA secret in history is already disclosed. Rotate it; reverting is not enough.")
        return 1
    print("scan-secrets: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
