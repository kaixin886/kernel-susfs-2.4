#!/usr/bin/env python3
"""Host-side codec and Linux 5.4 adapter regression tests for LZ4K."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "port/lz4k/openEuler-pr-1277.patch"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "apply_lz4k_patch", ROOT / "scripts/apply_lz4k_patch.py"
)
assert MODULE_SPEC and MODULE_SPEC.loader
adapter = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(adapter)


HARNESS = r'''#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lz4k.h"

#define PAGE 4096U
#define CAP (PAGE * 2U)

static uint32_t rng_state = 0x8427911U;
static uint32_t next_u32(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 17;
    rng_state ^= rng_state << 5;
    return rng_state;
}

static int check_roundtrip(const char *name, const uint8_t *src,
                           uint8_t *compressed, uint8_t *decoded,
                           void *state)
{
    int clen = lz4k_encode(state, src, compressed, PAGE, CAP, 0);
    if (clen < 0) {
        fprintf(stderr, "%s: encoder returned %d\n", name, clen);
        return 1;
    }
    if (clen == 0)
        return 0; /* The upstream API reports incompressible pages as zero. */
    if ((unsigned int)clen > CAP) {
        fprintf(stderr, "%s: encoder returned an oversized length %d\n", name, clen);
        return 1;
    }
    memset(decoded, 0xa5, PAGE);
    int dlen = lz4k_decode(compressed, decoded, (unsigned int)clen, PAGE);
    if (dlen != (int)PAGE || memcmp(src, decoded, PAGE) != 0) {
        fprintf(stderr, "%s: roundtrip mismatch (compressed=%d, decoded=%d)\n",
                name, clen, dlen);
        return 1;
    }
    return 0;
}

int main(void)
{
    const unsigned int state_size = lz4k_encode_state_bytes_min();
    void *state = calloc(1, state_size);
    uint8_t *src = malloc(PAGE);
    uint8_t *compressed = malloc(CAP);
    uint8_t *decoded = malloc(PAGE);
    uint8_t *bad = malloc(CAP);
    if (!state || !src || !compressed || !decoded || !bad) {
        fprintf(stderr, "allocation failed\n");
        return 2;
    }

    for (unsigned int i = 0; i < PAGE; ++i)
        src[i] = 0;
    if (check_roundtrip("all-zero", src, compressed, decoded, state))
        return 3;

    for (unsigned int period = 1; period <= 257; period++) {
        for (unsigned int i = 0; i < PAGE; ++i)
            src[i] = (uint8_t)((i % period) * 37U + (i % 11U));
        if (check_roundtrip("periodic", src, compressed, decoded, state))
            return 4;
    }

    for (unsigned int trial = 0; trial < 512; ++trial) {
        uint8_t dictionary[127];
        for (unsigned int i = 0; i < sizeof(dictionary); ++i)
            dictionary[i] = (uint8_t)next_u32();
        for (unsigned int i = 0; i < PAGE; ++i) {
            if ((trial & 1U) && i >= 64U)
                src[i] = src[i % 64U];
            else if ((trial % 3U) == 0)
                src[i] = dictionary[i % sizeof(dictionary)];
            else
                src[i] = (uint8_t)next_u32();
        }
        if (check_roundtrip("generated", src, compressed, decoded, state))
            return 5;
    }

    /* Fuzz malformed streams under ASan/UBSan to exercise decoder bounds. */
    for (unsigned int trial = 0; trial < 5000; ++trial) {
        unsigned int len = 1U + next_u32() % 256U;
        for (unsigned int i = 0; i < len; ++i)
            bad[i] = (uint8_t)next_u32();
        (void)lz4k_decode(bad, decoded, len, PAGE);
    }

    /* Mutate valid streams as a second malformed-input corpus. */
    for (unsigned int i = 0; i < PAGE; ++i)
        src[i] = (uint8_t)(i % 13U);
    int clen = lz4k_encode(state, src, compressed, PAGE, CAP, 0);
    if (clen > 0) {
        for (unsigned int trial = 0; trial < 1000; ++trial) {
            memcpy(bad, compressed, (size_t)clen);
            bad[next_u32() % (unsigned int)clen] ^= (uint8_t)(1U << (next_u32() & 7U));
            (void)lz4k_decode(bad, decoded, (unsigned int)clen, PAGE);
        }
    }

    free(bad);
    free(decoded);
    free(compressed);
    free(src);
    free(state);
    puts("LZ4K codec roundtrip and malformed-input tests: PASS");
    return 0;
}
'''

COMPAT_SHIM = r'''#include <stdbool.h>
#include <stdint.h>
#define EXPORT_SYMBOL(symbol)
#define MODULE_LICENSE(value)
#define MODULE_DESCRIPTION(value)
'''


def test_adapters() -> None:
    kconfig = (
        "config CRYPTO_LZ4K\n"
        '\ttristate "LZ4K compression algorithm"\n'
        "\tselect CRYPTO_ALGAPI\n"
        "\tselect LZ4K_COMPRESS\n"
        "\tselect LZ4K_DECOMPRESS\n"
        "\thelp\n"
        "\t  This is the LZ4K algorithm.\n\n"
        "config NEXT_OPTION\n"
    )
    updated = adapter.add_crypto_acomp2_dependency(kconfig)
    assert updated.count("select CRYPTO_ACOMP2") == 1
    assert adapter.add_crypto_acomp2_dependency(updated) == updated
    try:
        adapter.add_crypto_acomp2_dependency(kconfig.replace("select CRYPTO_ALGAPI\n", ""))
    except RuntimeError:
        pass
    else:
        raise AssertionError("missing CRYPTO_ALGAPI anchor was not rejected")

    zcomp = (
        "static const char * const backends[] = {\n"
        '\t"lz4",\n'
        "\tNULL\n"
        "};\n"
    )
    updated_zcomp = adapter.add_zcomp_backend(zcomp)
    assert updated_zcomp.count('"lz4k"') == 1
    assert updated_zcomp.index('"lz4k"') < updated_zcomp.index("NULL")
    assert adapter.add_zcomp_backend(updated_zcomp) == updated_zcomp
    try:
        adapter.add_zcomp_backend(zcomp.replace("\tNULL\n", ""))
    except RuntimeError:
        pass
    else:
        raise AssertionError("missing NULL sentinel was not rejected")
    assert hashlib.sha256(PATCH.read_bytes()).hexdigest() == adapter.UPSTREAM_SHA256
    build_script = (ROOT / "scripts" / "build-kernel.sh").read_text()
    assert build_script.count("--enable CRYPTO_LZ4K") == 1
    assert "ZRAM_KCONFIG_BEFORE" in build_script and "ZRAM_KCONFIG_AFTER" in build_script
    assert "LZ4K integration changed existing zram Kconfig" in build_script
    assert "CONFIG_ZRAM_DEF_COMP" not in build_script
    print("Linux 5.4 Kconfig/zcomp adapter tests: PASS")


def test_codec() -> None:
    with tempfile.TemporaryDirectory(prefix="lz4k-codec-test-") as temp:
        work = Path(temp)
        apply_cmd = [
            "git",
            "apply",
            "--whitespace=nowarn",
            "--include=include/linux/lz4k.h",
            "--include=lib/lz4k/*",
            str(PATCH),
        ]
        subprocess.run(apply_cmd, cwd=work, check=True)
        source_dir = work / "lib/lz4k"
        compile_cmd = [
            os.environ.get("CC", "cc"),
            "-std=gnu11",
            "-O1",
            "-g",
            "-fsanitize=address,undefined",
            "-fno-omit-frame-pointer",
            "-Wall",
            "-Wextra",
            "-include",
            str(work / "compat.h"),
            "-I",
            str(work / "include/linux"),
            str(work / "codec_test.c"),
            str(source_dir / "lz4k_encode.c"),
            str(source_dir / "lz4k_decode.c"),
            "-o",
            str(work / "codec_test"),
        ]
        (work / "codec_test.c").write_text(HARNESS)
        (work / "compat.h").write_text(COMPAT_SHIM)
        subprocess.run(compile_cmd, check=True)
        env = os.environ.copy()
        env["ASAN_OPTIONS"] = "detect_leaks=1:abort_on_error=1"
        env["UBSAN_OPTIONS"] = "halt_on_error=1"
        subprocess.run([str(work / "codec_test")], env=env, check=True)


def main() -> int:
    try:
        test_adapters()
        test_codec()
    except (AssertionError, OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"LZ4K regression failed: {exc}", file=__import__("sys").stderr)
        return 1
    print("All LZ4K regression tests: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
