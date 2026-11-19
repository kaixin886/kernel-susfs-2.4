#!/usr/bin/env python3
"""Regression checks for the Xiaomi MIX 4 / odin MGLRU 5.4.302 backport."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATCH = ROOT / "port/mglru/odin-mglru.patch"
DEFAULT_PINS = ROOT / "port/mglru/source-pins.json"
THERMAL_CONFIGS = (
    "CONFIG_THERMAL",
    "CONFIG_CPU_THERMAL",
    "CONFIG_THERMAL_GOV_STEP_WISE",
    "CONFIG_QTI_THERMAL",
    "CONFIG_QTI_THERMAL_LIMITS_DCVS",
    "CONFIG_QTI_CPU_ISOLATE_COOLING_DEVICE",
    "CONFIG_QTI_CPU_HOTPLUG_COOLING_DEVICE",
    "CONFIG_QTI_CPU_VOLTAGE_COOLING_DEVICE",
    "CONFIG_QTI_BCL_SOC_DRIVER",
)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def load_pins(pins_path: Path, patch_path: Path, target_commit: str | None) -> tuple[dict, list[str]]:
    try:
        pins = json.loads(pins_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read MGLRU source pins: {exc}")
    digest = hashlib.sha256(patch_path.read_bytes()).hexdigest()
    expected = pins.get("adapter_patch", {}).get("sha256")
    if digest != expected:
        fail(f"MGLRU patch SHA-256 {digest} does not match pinned {expected}")
    if target_commit and pins.get("target", {}).get("commit") != target_commit:
        fail("MGLRU source pin does not match the build kernel commit")
    patch = patch_path.read_text()
    paths = []
    for block in patch.split("diff --git ")[1:]:
        header = block.splitlines()[0]
        match = re.fullmatch(r"a/(.+) b/(.+)", header)
        if not match or match.group(1) != match.group(2):
            fail(f"malformed or asymmetric patch path: {header}")
        paths.append(match.group(1))
    if len(paths) != len(set(paths)):
        fail("patch contains duplicate file sections")
    forbidden = [p for p in paths if p.startswith(("arch/x86/", "arch/arm64/configs/", "drivers/thermal/"))]
    if forbidden:
        fail(f"patch contains device-inapplicable or thermal paths: {forbidden}")
    if "fs/exec.c" not in paths or "mm/vmscan.c" not in paths or "mm/Kconfig" not in paths:
        fail("patch is missing required exec, vmscan, or Kconfig integration")
    if pins.get("adapter_patch", {}).get("files") != len(paths):
        fail("pinned file count does not match patch")
    print(f"PASS: source pins and {len(paths)}-file MGLRU patch SHA-256 verified")
    return pins, paths


def check_source(source: Path) -> None:
    exec_c = (source / "fs/exec.c").read_text()
    for hook in ("lru_gen_add_mm(mm);", "lru_gen_use_mm(mm);"):
        if exec_c.count(hook) != 1:
            fail(f"expected exactly one {hook} in target fs/exec.c")

    vmscan = (source / "mm/vmscan.c").read_text()
    if vmscan.count("static void lru_gen_shrink_lruvec(") != 2:
        fail("expected one CONFIG_LRU_GEN implementation and one disabled stub")
    if vmscan.count("static void shrink_node_memcg(") != 1:
        fail("target shrink_node_memcg definition is missing or duplicated")
    fn = vmscan.index("static void shrink_node_memcg(")
    dispatch = vmscan.find("if (lru_gen_enabled())", fn)
    fallback = vmscan.find("get_scan_count(lruvec, memcg, sc, nr, lru_pages);", fn)
    if dispatch < 0 or fallback < 0 or dispatch >= fallback:
        fail("MGLRU runtime-switch dispatch is missing or replaces the original reclaim fallback")
    if "lru_gen_shrink_lruvec(lruvec, sc);" not in vmscan[dispatch:fallback]:
        fail("MGLRU reclaim dispatch does not call lru_gen_shrink_lruvec")

    kconfig = (source / "mm/Kconfig").read_text()
    if not re.search(r"(?m)^config LRU_GEN\n", kconfig):
        fail("CONFIG_LRU_GEN Kconfig entry is missing")
    if not re.search(r"(?ms)^config LRU_GEN_ENABLED\n.*?depends on LRU_GEN", kconfig):
        fail("default-enable Kconfig dependency is missing")
    docs = (source / "Documentation/admin-guide/mm/multigen_lru.rst").read_text()
    if "/sys/kernel/mm/lru_gen/enabled" not in docs:
        fail("documented runtime enable switch is missing")
    print("PASS: MGLRU hooks, runtime-switch dispatch, original fallback, Kconfig and kill-switch docs verified")


def check_config(config_path: Path) -> None:
    config = config_path.read_text()
    for option in ("CONFIG_LRU_GEN", "CONFIG_LRU_GEN_ENABLED"):
        if not re.search(rf"(?m)^{option}=y$", config):
            fail(f"{option} must be enabled for the integrated default-on build")
    for option in ("CONFIG_LRU_GEN_STATS",):
        if not re.search(rf"(?m)^# {option} is not set$", config):
            fail(f"{option} must remain disabled for the integrated build")
    for option in THERMAL_CONFIGS:
        if not re.search(rf"(?m)^{option}=y$", config):
            fail(f"existing thermal protection {option} is not enabled")
    print("PASS: CONFIG_LRU_GEN=y and CONFIG_LRU_GEN_ENABLED=y; stats off; all thermal protection options remain y")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--patch", type=Path, default=DEFAULT_PATCH)
    parser.add_argument("--pins", type=Path, default=DEFAULT_PINS)
    parser.add_argument("--target-commit")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    load_pins(args.pins, args.patch, args.target_commit)
    if args.source:
        check_source(args.source)
    if args.config:
        check_config(args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
