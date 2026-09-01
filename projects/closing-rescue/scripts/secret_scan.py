#!/usr/bin/env python3
"""Fail when tracked Closing Rescue files contain common live-secret shapes."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "Solari live key": re.compile(rb"slr_live_[A-Za-z0-9_-]{20,}"),
    "OpenAI-style key": re.compile(rb"sk-[A-Za-z0-9_-]{24,}"),
    "AWS access key": re.compile(rb"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    )
    return [PROJECT_ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def main() -> int:
    findings: list[str] = []
    for path in tracked_files():
        try:
            content = path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            continue
        if b"\0" in content[:8192]:
            continue
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(content):
                line = content.count(b"\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(PROJECT_ROOT)}:{line}: {label}")
    if findings:
        print("Potential secrets found in tracked files:")
        print("\n".join(findings))
        return 1
    print("Secret scan passed for tracked Closing Rescue files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
