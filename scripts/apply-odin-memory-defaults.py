#!/usr/bin/env python3
"""Set safe MIX 4 zram-compressor and VM defaults in the pinned Linux 5.4 tree."""
from pathlib import Path
import sys

FILES = {
    "zram": Path("drivers/block/zram/zram_drv.c"),
    "allocator": Path("mm/page_alloc.c"),
    "vmscan": Path("mm/vmscan.c"),
}


def replace_unique(source: str, old: str, new: str, description: str) -> tuple[str, bool]:
    old_count = source.count(old)
    new_count = source.count(new)
    if old_count == 1 and new_count == 0:
        return source.replace(old, new, 1), True
    if old_count == 0 and new_count == 1:
        return source, False
    raise RuntimeError(
        f"expected exactly one original or already-patched {description}; "
        f"found original={old_count}, patched={new_count}"
    )


def regular_source(root: Path, relative: Path) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"expected a regular kernel source file: {path}")
    return path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} <kernel-source-root>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"ERROR: kernel source root is not a directory: {root}", file=sys.stderr)
        return 1

    try:
        zram_path = regular_source(root, FILES["zram"])
        allocator_path = regular_source(root, FILES["allocator"])
        vmscan_path = regular_source(root, FILES["vmscan"])

        zram, zram_changed = replace_unique(
            zram_path.read_text(),
            'static const char *default_compressor = "lzo-rle";',
            'static const char *default_compressor = "lz4k";',
            "zram default compressor declaration",
        )
        allocator = allocator_path.read_text()
        allocator, watermark_changed = replace_unique(
            allocator,
            "int watermark_scale_factor = 10;",
            "int watermark_scale_factor = 100;",
            "watermark_scale_factor default",
        )
        allocator, extra_changed = replace_unique(
            allocator,
            "int extra_free_kbytes = 0;",
            "int extra_free_kbytes = 99083;",
            "extra_free_kbytes default",
        )
        vmscan = vmscan_path.read_text()
        if vmscan.count("int vm_swappiness = 60;") != 1:
            raise RuntimeError("expected pinned baseline vm_swappiness default to be exactly 60")

        if zram_changed:
            zram_path.write_text(zram)
        if watermark_changed or extra_changed:
            allocator_path.write_text(allocator)
        print(
            "applied odin memory defaults: zram compressor=lz4k, "
            "vm.swappiness=60 (pinned baseline), vm.extra_free_kbytes=99083, "
            "vm.watermark_scale_factor=100"
        )
        if not (zram_changed or watermark_changed or extra_changed):
            print("all requested defaults were already present; source is unchanged")
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
