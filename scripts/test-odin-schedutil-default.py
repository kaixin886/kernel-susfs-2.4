#!/usr/bin/env python3
"""Mock-test the pinned-source schedutil ramp-down default patch."""
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
PATCHER = SCRIPT_DIR / "apply-odin-schedutil-default.py"
MARKER = "/* odin-daily-power: preserve ramp-up delay; allow immediate ramp-down */"
OLD_BLOCK = (
    "\ttunables->up_rate_limit_us = cpufreq_policy_transition_delay_us(policy);\n"
    "\ttunables->down_rate_limit_us = cpufreq_policy_transition_delay_us(policy);\n"
)
NEW_BLOCK = (
    "\ttunables->up_rate_limit_us = cpufreq_policy_transition_delay_us(policy);\n"
    f"\t{MARKER}\n"
    "\ttunables->down_rate_limit_us = 0;\n"
)
PREFIX = "/* unrelated schedutil code stays byte-for-byte unchanged */\n"
SUFFIX = "\n/* end unrelated code */\n"


def invoke(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(PATCHER), str(path)], text=True, capture_output=True)


def expect_failure(path: Path, message: str) -> None:
    result = invoke(path)
    if result.returncode == 0 or message not in result.stderr:
        raise AssertionError(
            f"expected failure containing {message!r}; rc={result.returncode}, stderr={result.stderr!r}"
        )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="odin-schedutil-default-test-") as tmp:
        root = Path(tmp)

        source_path = root / "cpufreq_schedutil.c"
        original = PREFIX + OLD_BLOCK + SUFFIX
        source_path.write_text(original)
        result = invoke(source_path)
        if result.returncode != 0:
            raise AssertionError(f"patch failed: {result.stderr}")
        expected = PREFIX + NEW_BLOCK + SUFFIX
        if source_path.read_text() != expected:
            raise AssertionError("patch changed unrelated source or failed to preserve up-rate initialization")
        if "applied odin daily-power schedutil default" not in result.stdout:
            raise AssertionError("patch confirmation did not identify the applied profile")
        print("PASS: exactly one default down-rate becomes 0 while original up-rate and unrelated bytes remain unchanged")

        expect_failure(source_path, "marker already exists")
        print("PASS: duplicate patch is rejected")

        missing_path = root / "missing.c"
        missing_path.write_text(PREFIX + "static void unchanged(void) {}\n" + SUFFIX)
        expect_failure(missing_path, "found 0")
        print("PASS: missing pinned initialization block is rejected")

        duplicate_path = root / "duplicate.c"
        duplicate_path.write_text(OLD_BLOCK + "\n" + OLD_BLOCK)
        expect_failure(duplicate_path, "found 2")
        print("PASS: ambiguous source with duplicate initialization blocks is rejected")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
