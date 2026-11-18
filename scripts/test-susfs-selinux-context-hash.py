#!/usr/bin/env python3
"""Static regression checks for SUSFS 2.4 SELinux context-to-SID hashing.

Run against a fully prepared 5.4 kernel tree after the BakaSU and SUSFS
sources have been integrated:
    python3 scripts/test-susfs-selinux-context-hash.py <kernel-source-root>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def function_body(source: str, name: str) -> str:
    """Return a C function body by matching its name and balanced braces."""
    for match in re.finditer(rf"\b{re.escape(name)}\s*\(", source):
        opening_paren = source.find("(", match.start())
        closing_paren = source.find(")", opening_paren + 1)
        if closing_paren < 0:
            continue
        opening_brace = closing_paren + 1
        while opening_brace < len(source):
            while opening_brace < len(source) and source[opening_brace].isspace():
                opening_brace += 1
            # Some versioned definitions place #endif between the signature and
            # the shared opening brace, as pinned BakaSU does for 5.4/5.10.
            if opening_brace >= len(source) or source[opening_brace] != "#":
                break
            directive_end = source.find("\n", opening_brace)
            if directive_end < 0:
                opening_brace = len(source)
                break
            opening_brace = directive_end + 1
        if opening_brace >= len(source) or source[opening_brace] != "{":
            continue

        depth = 0
        state = "code"
        i = opening_brace
        while i < len(source):
            char = source[i]
            nxt = source[i + 1] if i + 1 < len(source) else ""
            if state == "line_comment":
                if char == "\n":
                    state = "code"
            elif state == "block_comment":
                if char == "*" and nxt == "/":
                    state = "code"
                    i += 1
            elif state in ("string", "char"):
                if char == "\\":
                    i += 1
                elif (state == "string" and char == '"') or (
                    state == "char" and char == "'"
                ):
                    state = "code"
            else:
                if char == "/" and nxt == "/":
                    state = "line_comment"
                    i += 1
                elif char == "/" and nxt == "*":
                    state = "block_comment"
                    i += 1
                elif char == '"':
                    state = "string"
                elif char == "'":
                    state = "char"
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return source[opening_brace + 1 : i]
            i += 1
    fail(f"could not find a function definition for {name}()")


def require_pattern(pattern: str, text: str, message: str, flags: int = re.S) -> None:
    if not re.search(pattern, text, flags):
        fail(message)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <kernel-source-root>")
    root = Path(sys.argv[1]).resolve()
    services_path = root / "security/selinux/ss/services.c"
    sidtab_path = root / "security/selinux/ss/sidtab.c"
    hooks_path = root / "security/selinux/hooks.c"
    compat_path = root / "KernelSU/kernel/tools/kernel_compat.mk"
    hide_path = root / "KernelSU/kernel/feature/selinux_hide.c"
    bakasu_kbuild_path = root / "KernelSU/kernel/Kbuild"
    for path in (services_path, sidtab_path, hooks_path, compat_path, hide_path, bakasu_kbuild_path):
        if not path.is_file():
            fail(f"required integrated source is missing: {path.relative_to(root)}")

    services = services_path.read_text(encoding="utf-8")
    sidtab = sidtab_path.read_text(encoding="utf-8")
    hooks = hooks_path.read_text(encoding="utf-8")
    compat = compat_path.read_text(encoding="utf-8")
    hide = hide_path.read_text(encoding="utf-8")
    bakasu_kbuild = bakasu_kbuild_path.read_text(encoding="utf-8")

    if not re.search(r"\bint\s+context_add_hash\s*\(", services):
        fail("the pinned SELinux services.c does not provide context_add_hash()")
    lookup = function_body(sidtab, "context_to_sid")
    require_pattern(
        r"hash_for_each_possible_rcu\s*\([^;]*context->hash",
        lookup,
        "sidtab lookup is no longer keyed by context->hash; review this test",
    )

    native = function_body(services, "context_struct_to_sid")
    require_pattern(
        r"if\s*\(\s*!context->hash\s*\)\s*\{\s*"
        r"rc\s*=\s*context_add_hash\s*\(\s*policydb\s*,\s*context\s*\)\s*;\s*"
        r"if\s*\(\s*rc\s*\)\s*return\s+rc\s*;\s*\}\s*"
        r"return\s+sidtab_context_to_sid\s*\(",
        native,
        "the native 5.4 context_struct_to_sid() helper no longer hashes before sidtab",
    )

    susfs_core = function_body(services, "susfs_security_context_to_sid_core")
    if susfs_core.count("context_struct_to_sid(state, &context, sid)") != 1:
        fail("SUSFS context-to-SID must delegate exactly once to the native hash-aware helper")
    if "sidtab_context_to_sid(" in susfs_core:
        fail("SUSFS context-to-SID still bypasses the native hash-aware helper")
    require_pattern(
        r"if\s*\(\s*rc\s*==\s*-EINVAL\s*&&\s*force\s*\).*?"
        r"context\.str\s*=\s*str\s*;.*?"
        r"rc\s*=\s*context_struct_to_sid\s*\(\s*state\s*,\s*&context\s*,\s*sid\s*\)",
        susfs_core,
        "SUSFS default/force parsing no longer reaches the hash-aware helper after fallback setup",
    )
    for wrapper in (
        "susfs_security_context_to_sid",
        "susfs_security_context_to_sid_default",
        "susfs_security_context_to_sid_force",
    ):
        body = function_body(services, wrapper)
        if "susfs_security_context_to_sid_core(" not in body:
            fail(f"{wrapper}() no longer routes through the checked SUSFS core")

    require_pattern(
        r'grep\s+-q\s+"\^int context_add_hash"\s+\$\(srctree\)/security/selinux/ss/services\.c',
        compat,
        "BakaSU compatibility makefile no longer detects context_add_hash()",
    )
    require_pattern(
        r"ccflags-y\s*\+=\s*-DKSU_COMPAT_HAS_CONTEXT_ADD_HASH",
        compat,
        "BakaSU compatibility macro is not enabled when context_add_hash() exists",
    )
    require_pattern(
        r"(?m)^\s*include\s+\$\(KSU_SRC\)/tools/kernel_compat\.mk\s*$",
        bakasu_kbuild,
        "BakaSU Kbuild does not include the compatibility makefile that enables the hash guard",
    )
    require_pattern(
        r"(?m)^\s*kernelsu-objs\s*\+=\s*feature/selinux_hide\.o\s*$",
        bakasu_kbuild,
        "BakaSU selinux_hide.c is not included in the compiled KernelSU objects",
    )
    bakasu_sid_conversion = function_body(hide, "ksu_security_context_to_sid")
    require_pattern(
        r"#ifdef\s+KSU_COMPAT_HAS_CONTEXT_ADD_HASH\s+"
        r"rc\s*=\s*context_add_hash\s*\(\s*policydb\s*,\s*&context\s*\)\s*;\s*"
        r"if\s*\(\s*!rc\s*\)\s*#endif\s+"
        r"rc\s*=\s*sidtab_context_to_sid\s*\(\s*sidtab\s*,\s*&context\s*,\s*sid\s*\)",
        bakasu_sid_conversion,
        "BakaSU primary SID conversion lost its #623 guarded hash initialization or failure short-circuit",
    )
    require_pattern(
        r"#ifdef\s+KSU_COMPAT_HAS_CONTEXT_ADD_HASH\s+"
        r"orig_rc\s*=\s*context_add_hash\s*\(\s*orig_policydb\s*,\s*&orig_context\s*\)\s*;\s*"
        r"#endif\s+if\s*\(\s*!orig_rc\s*\)\s*"
        r"orig_rc\s*=\s*sidtab_context_to_sid\s*\(\s*orig_sidtab\s*,\s*&orig_context\s*,\s*&orig_sid\s*\)",
        bakasu_sid_conversion,
        "BakaSU backup SID conversion lost its #623 guarded hash initialization",
    )

    hide_hook = function_body(hooks, "handle_selinux_inode_setxattr")
    if "ksu_selinux_hide_running" not in hide_hook or "susfs_selinux_inode_setxattr(" not in hide_hook:
        fail("SUSFS xattr handler is not gated by BakaSU SELinux-hide state as expected")
    susfs_xattr = function_body(hooks, "susfs_selinux_inode_setxattr")
    if "susfs_security_context_to_sid(" not in susfs_xattr or "susfs_security_context_to_sid_force(" not in susfs_xattr:
        fail("SUSFS xattr context and force paths no longer use the checked SID wrappers")

    print("PASS: sidtab hash lookup, native helper, SUSFS delegation, BakaSU #623 compatibility, and SELinux-hide xattr route")


if __name__ == "__main__":
    main()
