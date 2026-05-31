#!/usr/bin/env python3
"""Validate markdown heading continuity for numbered sections."""

from __future__ import annotations

import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^(#{2,4})\s+(\d+)(?:\.(\d+))?(?:\.(\d+))?\b")


def parse_headings(lines: list[str]):
    items = []
    for idx, line in enumerate(lines, start=1):
        m = HEADING_RE.match(line.strip())
        if not m:
            continue
        hashes, major, minor, patch = m.groups()
        level = len(hashes)
        nums = [int(major)]
        if minor is not None:
            nums.append(int(minor))
        if patch is not None:
            nums.append(int(patch))
        items.append((idx, level, nums, line.rstrip("\n")))
    return items


def check_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    headings = parse_headings(lines)

    errors = 0
    current_h2 = None

    prev_by_level = {}
    for line_no, level, nums, raw in headings:
        prev = prev_by_level.get(level)
        if prev and nums < prev:
            print(f"ERROR {path}:{line_no}: out-of-order heading {nums} after {prev} :: {raw}")
            errors += 1
        prev_by_level[level] = nums

        if level == 2:
            current_h2 = nums[0]
        elif level == 3 and len(nums) >= 2:
            if current_h2 is None or nums[0] != current_h2:
                print(
                    f"ERROR {path}:{line_no}: parent mismatch for H3 {nums}, "
                    f"expected under H2 {nums[0]} but current H2 is {current_h2} :: {raw}"
                )
                errors += 1

    if errors == 0:
        print(f"OK {path}: heading continuity check passed")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: check_markdown_continuity.py <markdown-file> [<markdown-file> ...]")
        return 2

    total_errors = 0
    for arg in argv[1:]:
        path = Path(arg)
        if not path.exists():
            print(f"ERROR {path}: file not found")
            total_errors += 1
            continue
        total_errors += check_file(path)

    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
