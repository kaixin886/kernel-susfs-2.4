#!/usr/bin/env python3
"""Apply the pinned openEuler LZ4K implementation with Linux 5.4 adapters."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

UPSTREAM_SHA256 = "51f0fe4e7e2b9bdc782a59f7f977c37bd710140fb0613fd27f84b2743c7d997b"
SECOND_COMMIT = "From 3a5b156ae89e09f6444cad973df000f4e58a40a4 Mon Sep 17 00:00:00 2001"


def fail(message: str) -> None:
    raise RuntimeError(message)


def add_crypto_acomp2_dependency(text: str) -> str:
    """Make CRYPTO_LZ4K depend on the 5.4 acomp compatibility layer."""
    marker = "config CRYPTO_LZ4K\n"
    if text.count(marker) != 1:
        fail("expected exactly one CRYPTO_LZ4K Kconfig block")
    start = text.index(marker)
    end = text.find("\n\n", start)
    if end < 0:
        fail("CRYPTO_LZ4K Kconfig block has no terminating blank line")
    block = text[start:end]
    if "\tselect CRYPTO_ACOMP2\n" in block:
        return text
    needle = "\tselect CRYPTO_ALGAPI\n"
    if block.count(needle) != 1:
        fail("CRYPTO_LZ4K block does not have one CRYPTO_ALGAPI selection")
    updated = block.replace(needle, needle + "\tselect CRYPTO_ACOMP2\n", 1)
    return text[:start] + updated + text[end:]


def add_zcomp_backend(text: str) -> str:
    """Register LZ4K without displacing the existing zcomp NULL sentinel."""
    marker = "static const char * const backends[] = {"
    if text.count(marker) != 1:
        fail("expected exactly one zcomp backend array")
    start = text.index(marker)
    end = text.find("\n};", start)
    if end < 0:
        fail("could not find end of zcomp backend array")
    block = text[start:end]
    entry = '#if IS_ENABLED(CONFIG_CRYPTO_LZ4K)\n\t"lz4k",\n#endif\n'
    if entry in block:
        return text
    if '"lz4k"' in block:
        fail("zcomp backend array has an unexpected existing lz4k entry")
    sentinel = "\tNULL"
    if block.count(sentinel) != 1:
        fail("expected exactly one NULL sentinel in zcomp backend array")
    block = block.replace(sentinel, entry + sentinel, 1)
    return text[:start] + block + text[end:]


def apply_to_kernel(kernel: Path, patch_path: Path) -> None:
    kernel = kernel.resolve()
    if not (kernel / "crypto/Kconfig").is_file():
        fail(f"not a kernel source tree: {kernel}")
    patch_bytes = patch_path.read_bytes()
    actual_hash = hashlib.sha256(patch_bytes).hexdigest()
    if actual_hash != UPSTREAM_SHA256:
        fail(f"openEuler patch SHA-256 mismatch: {actual_hash}")
    patch = patch_bytes.decode("utf-8")
    if patch.count(SECOND_COMMIT) != 1:
        fail("expected the pinned two-commit openEuler PR patch")
    first_commit = patch.split(SECOND_COMMIT, 1)[0]

    new_files = [
        kernel / "crypto/lz4k.c",
        kernel / "include/linux/lz4k.h",
        kernel / "lib/lz4k/lz4k_decode.c",
        kernel / "lib/lz4k/lz4k_encode.c",
    ]
    if any(path.exists() for path in new_files):
        fail("LZ4K implementation files already exist; refusing a partial or duplicate apply")
    zcomp_path = kernel / "drivers/block/zram/zcomp.c"
    if not zcomp_path.is_file():
        fail("missing drivers/block/zram/zcomp.c")
    zcomp_text = zcomp_path.read_text()
    # Fail before applying if this 5.4 tree does not have the expected sentinel layout.
    add_zcomp_backend(zcomp_text)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".patch") as stream:
        stream.write(first_commit)
        stream.flush()
        subprocess.run(["git", "apply", "--check", "--whitespace=nowarn", stream.name], cwd=kernel, check=True)
        subprocess.run(["git", "apply", "--whitespace=nowarn", stream.name], cwd=kernel, check=True)

    kconfig_path = kernel / "crypto/Kconfig"
    kconfig_path.write_text(add_crypto_acomp2_dependency(kconfig_path.read_text()))
    zcomp_path.write_text(add_zcomp_backend(zcomp_path.read_text()))

    installed_files = [
        kernel / "crypto/lz4k.c",
        kernel / "include/linux/lz4k.h",
        kernel / "lib/lz4k/Makefile",
        kernel / "lib/lz4k/lz4k_decode.c",
        kernel / "lib/lz4k/lz4k_encode.c",
        kernel / "lib/lz4k/lz4k_encode_private.h",
        kernel / "lib/lz4k/lz4k_private.h",
    ]
    missing = [str(path.relative_to(kernel)) for path in installed_files if not path.is_file()]
    if missing:
        fail(f"LZ4K source installation incomplete: {missing}")
    for path in installed_files:
        text = path.read_text()
        text = text.rstrip("\n") + "\n"
        if any(line.rstrip(" \t") != line for line in text.splitlines()):
            fail(f"LZ4K source contains trailing horizontal whitespace: {path.relative_to(kernel)}")
        path.write_text(text)
    kconfig = kconfig_path.read_text()
    block = kconfig.split("config CRYPTO_LZ4K\n", 1)[1].split("\n\n", 1)[0]
    if "\tselect CRYPTO_ACOMP2\n" not in block:
        fail("5.4 CRYPTO_ACOMP2 dependency is missing")
    zcomp = zcomp_path.read_text()
    if zcomp.count('#if IS_ENABLED(CONFIG_CRYPTO_LZ4K)\n\t"lz4k",\n#endif\n') != 1:
        fail("LZ4K zcomp backend is missing or duplicated")
    if '"lz4k",\n#endif\n\tNULL' not in zcomp:
        fail("LZ4K backend no longer precedes the zcomp NULL sentinel")


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} KERNEL_SOURCE_TREE", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    patch_path = root / "port/lz4k/openEuler-pr-1277.patch"
    try:
        apply_to_kernel(Path(sys.argv[1]), patch_path)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("LZ4K source applied with Linux 5.4 CRYPTO_ACOMP2 and zcomp NULL-sentinel adapters")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
