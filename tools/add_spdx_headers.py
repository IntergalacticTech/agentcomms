#!/usr/bin/env python3
"""
add_spdx_headers.py
-------------------
Prepend FSL-1.1-Apache-2.0 SPDX headers to all source files under the
target directories.

Safe to re-run — idempotent (skips files that already have the header).

Target directories:
  core/
  adapters/    (including adapters/discord/ scaffold)
  cdk/lib/
  cdk/bin/

Skips:
  - Files that already have SPDX-License-Identifier: on the first 3 lines
  - Empty __init__.py files (size == 0)
  - Test files: *.test.ts, test_*.py
  - conftest.py files
  - */tests/* subdirectories
  - Fixture files (.json, .eml, .toml, .xml, .yaml, .yml, .csv)
  - sdks/  console/  docs/  (not in target directories)
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

TARGET_DIRS = [
    REPO_ROOT / "core",
    REPO_ROOT / "adapters",
    REPO_ROOT / "cdk" / "lib",
    REPO_ROOT / "cdk" / "bin",
]

SOURCE_EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx"}

FIXTURE_EXTENSIONS = {".json", ".eml", ".toml", ".xml", ".yaml", ".yml", ".csv", ".txt"}

PY_HEADER = """\
# SPDX-License-Identifier: FSL-1.1-Apache-2.0
# © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
# with Apache 2.0 Future License. See LICENSE for details.
"""

TS_HEADER = """\
// SPDX-License-Identifier: FSL-1.1-Apache-2.0
// © 2026 Victory (Intergalactic Tech). Licensed under the Functional Source License, Version 1.1,
// with Apache 2.0 Future License. See LICENSE for details.
"""


def get_header(ext: str) -> str:
    if ext == ".py":
        return PY_HEADER
    elif ext in (".ts", ".tsx", ".js", ".jsx"):
        return TS_HEADER
    return ""


def should_skip(path: Path) -> tuple[bool, str]:
    """Return (skip, reason)."""
    ext = path.suffix.lower()

    # Not a source extension
    if ext not in SOURCE_EXTENSIONS:
        return True, "not a source file"

    # Fixture extensions (shouldn't happen given SOURCE_EXTENSIONS check, but safety net)
    if ext in FIXTURE_EXTENSIONS:
        return True, "fixture file"

    name = path.name

    # conftest.py
    if name == "conftest.py":
        return True, "conftest.py"

    # Test files
    if name.endswith(".test.ts") or name.endswith(".test.tsx") or name.endswith(".test.js"):
        return True, "test file"
    if name.startswith("test_") and ext == ".py":
        return True, "test file"

    # */tests/* subdirectory
    parts = path.parts
    if "tests" in parts:
        return True, "in tests/ subdirectory"

    # Empty __init__.py
    if name == "__init__.py" and path.stat().st_size == 0:
        return True, "empty __init__.py"

    return False, ""


def already_has_header(path: Path) -> bool:
    """Check if the first 3 lines contain SPDX-License-Identifier."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= 3:
                    break
                if "SPDX-License-Identifier:" in line:
                    return True
    except OSError:
        pass
    return False


def prepend_header(path: Path, header: str) -> None:
    content = path.read_bytes()
    # Handle shebang lines: keep them at the top
    text = content.decode("utf-8", errors="replace")
    if text.startswith("#!"):
        first_newline = text.index("\n") + 1
        new_content = text[:first_newline] + header + "\n" + text[first_newline:]
    else:
        new_content = header + "\n" + text
    path.write_bytes(new_content.encode("utf-8"))


def main() -> None:
    modified = []
    skipped_already = []
    skipped_rule = []

    for target_dir in TARGET_DIRS:
        if not target_dir.exists():
            print(f"  [SKIP] Directory not found: {target_dir}", file=sys.stderr)
            continue

        for root, dirs, files in os.walk(target_dir):
            # Skip __pycache__ and .git
            dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", "node_modules", "dist", "cdk.out")]
            for fname in sorted(files):
                path = Path(root) / fname

                skip, reason = should_skip(path)
                if skip:
                    skipped_rule.append((path, reason))
                    continue

                if already_has_header(path):
                    skipped_already.append(path)
                    continue

                header = get_header(path.suffix.lower())
                if not header:
                    skipped_rule.append((path, "no header template for extension"))
                    continue

                prepend_header(path, header)
                modified.append(path)
                print(f"  [ADDED] {path.relative_to(REPO_ROOT)}")

    print()
    print(f"Summary:")
    print(f"  Modified (header added):          {len(modified)}")
    print(f"  Skipped (already had header):     {len(skipped_already)}")
    print(f"  Skipped (rule):                   {len(skipped_rule)}")

    if len(modified) > 200:
        print()
        print(f"WARNING: {len(modified)} files modified — exceeds 200 file threshold. "
              "Please spot-check before committing.")


if __name__ == "__main__":
    main()
