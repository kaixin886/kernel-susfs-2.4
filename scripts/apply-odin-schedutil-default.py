#!/usr/bin/env python3
"""Set MIX 4 schedutil's default down-rate delay to zero, preserving ramp-up."""
from pathlib import Path
import sys

MARKER = "/* odin-daily-power: preserve ramp-up delay; allow immediate ramp-down */"
OLD = (
    "\ttunables->up_rate_limit_us = cpufreq_policy_transition_delay_us(policy);\n"
    "\ttunables->down_rate_limit_us = cpufreq_policy_transition_delay_us(policy);\n"
)
NEW = (
    "\ttunables->up_rate_limit_us = cpufreq_policy_transition_delay_us(policy);\n"
    f"\t{MARKER}\n"
    "\ttunables->down_rate_limit_us = 0;\n"
)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} <kernel/sched/cpufreq_schedutil.c>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    if not path.is_file() or path.is_symlink():
        print(f"ERROR: expected a regular schedutil source file: {path}", file=sys.stderr)
        return 1

    source = path.read_text()
    if MARKER in source:
        print("ERROR: daily-power marker already exists; refusing to patch twice", file=sys.stderr)
        return 1
    count = source.count(OLD)
    if count != 1:
        print(f"ERROR: expected exactly one pinned schedutil initialization block, found {count}", file=sys.stderr)
        return 1

    patched = source.replace(OLD, NEW, 1)
    if patched.count("tunables->up_rate_limit_us = cpufreq_policy_transition_delay_us(policy);") != 1:
        print("ERROR: original ramp-up initialization was not preserved exactly", file=sys.stderr)
        return 1
    if patched.count("tunables->down_rate_limit_us = 0;") != 1:
        print("ERROR: expected exactly one immediate ramp-down default", file=sys.stderr)
        return 1

    path.write_text(patched)
    print(f"applied odin daily-power schedutil default to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
