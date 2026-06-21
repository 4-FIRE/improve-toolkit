#!/usr/bin/env python3
"""
Run all unit tests under scripts/tests/.

Usage:
    python scripts/run_tests.py
"""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent / "tests"


def main():
    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    if not test_files:
        print("No test files found.")
        sys.exit(1)

    total_passed = 0
    total_failed = 0
    failures = []

    for tf in test_files:
        result = subprocess.run(
            [sys.executable, str(tf)],
            capture_output=True,
            text=True,
        )
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)

        if result.returncode != 0:
            total_failed += 1
            failures.append(tf.name)
        else:
            total_passed += 1

    print(f"\n{'=' * 40}")
    print(f"Files: {total_passed} passed, {total_failed} failed, {len(test_files)} total")
    if failures:
        print(f"Failed: {', '.join(failures)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
