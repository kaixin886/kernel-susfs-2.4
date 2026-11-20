#!/usr/bin/env python3
"""Test the odin Linux 5.4 memory-default source adapter."""
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
PATCHER = SCRIPT_DIR / "apply-odin-memory-defaults.py"
EXPECTED = {
    Path("drivers/block/zram/zram_drv.c"): (
        'static const char *default_compressor = "lzo-rle";',
        'static const char *default_compressor = "lz4k";',
    ),
    Path("mm/page_alloc.c"): (
        "int watermark_scale_factor = 10;",
        "int watermark_scale_factor = 100;",
        "int extra_free_kbytes = 0;",
        "int extra_free_kbytes = 99083;",
    ),
    Path("mm/vmscan.c"): ("int vm_swappiness = 60;",),
}


def invoke(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PATCHER), str(root)], text=True, capture_output=True
    )


def make_tree(root: Path) -> None:
    for relative, items in EXPECTED.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == Path("drivers/block/zram/zram_drv.c"):
            content = "/* unrelated zram code */\n" + items[0] + "\n"
        elif relative == Path("mm/page_alloc.c"):
            content = "/* unrelated allocator code */\n" + items[0] + "\n" + items[2] + "\n"
        else:
            content = "/* unrelated reclaim code */\n" + items[0] + "\n"
        path.write_text(content)


def expect_failure(root: Path, message: str) -> None:
    result = invoke(root)
    if result.returncode == 0 or message not in result.stderr:
        raise AssertionError(
            f"expected failure containing {message!r}; rc={result.returncode}, stderr={result.stderr!r}"
        )


def test_mock_tree() -> None:
    with tempfile.TemporaryDirectory(prefix="odin-memory-default-test-") as tmp:
        root = Path(tmp)
        make_tree(root)
        result = invoke(root)
        if result.returncode != 0:
            raise AssertionError(f"patch failed: {result.stderr}")

        zram = (root / EXPECTED.keys().__iter__().__next__()).read_text()
        if zram.count('static const char *default_compressor = "lz4k";') != 1:
            raise AssertionError("LZ4K was not made the sole default compressor")
        allocator = (root / "mm/page_alloc.c").read_text()
        if "int watermark_scale_factor = 100;" not in allocator:
            raise AssertionError("watermark_scale_factor default was not updated")
        if "int extra_free_kbytes = 99083;" not in allocator:
            raise AssertionError("extra_free_kbytes default was not updated")
        if (root / "mm/vmscan.c").read_text().count("int vm_swappiness = 60;") != 1:
            raise AssertionError("baseline swappiness=60 was not preserved")
        if "applied odin memory defaults" not in result.stdout:
            raise AssertionError("patch confirmation did not report the intended values")
        print("PASS: LZ4K and requested VM defaults are patched; swappiness remains 60")

        snapshots = {path: (root / path).read_bytes() for path in EXPECTED}
        repeat = invoke(root)
        if repeat.returncode != 0:
            raise AssertionError(f"idempotent second run failed: {repeat.stderr}")
        if any((root / path).read_bytes() != data for path, data in snapshots.items()):
            raise AssertionError("idempotent second run changed source bytes")
        print("PASS: repeated application is idempotent")

        duplicate = root / "drivers/block/zram/zram_drv.c"
        duplicate.write_text(duplicate.read_text() + 'static const char *default_compressor = "lzo-rle";\n')
        expect_failure(root, "expected exactly one original or already-patched zram default")
        print("PASS: ambiguous source is rejected")


def test_live_source(root: Path) -> None:
    result = invoke(root)
    if result.returncode != 0:
        raise AssertionError(f"live-source adapter failed: {result.stderr}")
    zram = (root / "drivers/block/zram/zram_drv.c").read_text()
    allocator = (root / "mm/page_alloc.c").read_text()
    vmscan = (root / "mm/vmscan.c").read_text()
    checks = {
        "zram default compressor": zram.count('static const char *default_compressor = "lz4k";') == 1,
        "watermark_scale_factor default": allocator.count("int watermark_scale_factor = 100;") == 1,
        "extra_free_kbytes default": allocator.count("int extra_free_kbytes = 99083;") == 1,
        "swappiness baseline": vmscan.count("int vm_swappiness = 60;") == 1,
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise AssertionError("live source verification failed: " + ", ".join(failures))
    print("PASS: pinned source contains zram=lz4k, swappiness=60, extra_free_kbytes=99083, watermark_scale_factor=100")


def main() -> int:
    args = sys.argv[1:]
    source = None
    if args:
        if len(args) != 2 or args[0] != "--source":
            print(f"usage: {Path(sys.argv[0]).name} [--source <kernel-source-root>]", file=sys.stderr)
            return 2
        source = Path(args[1]).resolve()
    try:
        test_mock_tree()
        if source is not None:
            test_live_source(source)
    except (AssertionError, OSError, subprocess.CalledProcessError) as exc:
        print(f"odin memory-default regression failed: {exc}", file=sys.stderr)
        return 1
    print("All odin memory-default regression tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
