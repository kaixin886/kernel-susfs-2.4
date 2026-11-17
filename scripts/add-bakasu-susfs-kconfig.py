#!/usr/bin/env python3
"""Add only validated, missing SUSFS v2.4 Kconfig entries to pinned BakaSU."""

from pathlib import Path
import os
import re
import stat
import sys
import tempfile


OPTIONS = {
    "KSU_SUSFS_AVD": {
        "prompt": 'bool "Enable SUSFS AVD and sus_type rules"',
        "block": """config KSU_SUSFS_AVD
    bool "Enable SUSFS AVD and sus_type rules"
    depends on KSU_SUSFS
    default y""",
    },
    "KSU_SUSFS_PRIORITY_UID_FILTER": {
        "prompt": 'bool "Enable SUSFS priority UID filter"',
        "block": """config KSU_SUSFS_PRIORITY_UID_FILTER
    bool "Enable SUSFS priority UID filter"
    depends on KSU_SUSFS
    default y""",
    },
}

TOP_LEVEL_START = re.compile(
    r"(?m)^(?:config\s+[A-Za-z0-9_]+|menu(?:\s|$)|comment(?:\s|$)|"
    r"choice(?:\s|$)|endchoice\s*$|if(?:\s|$)|endif\s*$|endmenu\s*$|"
    r"mainmenu(?:\s|$)|source(?:\s|$)|rsource(?:\s|$)|"
    r"osource(?:\s|$)|orsource(?:\s|$))"
)


def declaration_count(text: str, symbol: str) -> int:
    return len(re.findall(rf"(?m)^config {re.escape(symbol)}$", text))


def option_block(text: str, symbol: str) -> str:
    matches = list(re.finditer(rf"(?m)^config {re.escape(symbol)}$", text))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one {symbol} declaration, found {len(matches)}")

    start = matches[0].start()
    end = len(text)
    for token in TOP_LEVEL_START.finditer(text, matches[0].end()):
        if token.start() > start:
            end = token.start()
            break
    return text[start:end]


def validate_option(text: str, symbol: str) -> None:
    block = option_block(text, symbol)
    attributes = []
    help_seen = False
    help_text_seen = False
    for line in block.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped in ("help", "---help---"):
            if help_seen or attributes != [
                OPTIONS[symbol]["prompt"],
                "depends on KSU_SUSFS",
                "default y",
            ]:
                raise SystemExit(f"{symbol} has a malformed help block or option order")
            help_seen = True
            continue
        if help_seen:
            indent = len(line) - len(line.lstrip(" \t"))
            if indent < 8:
                raise SystemExit(f"{symbol} help text is not indented as a Kconfig help block")
            help_text_seen = True
        else:
            attributes.append(stripped)

    expected = [
        OPTIONS[symbol]["prompt"],
        "depends on KSU_SUSFS",
        "default y",
    ]
    if attributes != expected:
        raise SystemExit(
            f"existing {symbol} Kconfig block is not the expected bool/dependency/default: {attributes!r}"
        )
    if help_seen and not help_text_seen:
        raise SystemExit(f"{symbol} has an empty help block")


def atomic_write(path: Path, text: str) -> None:
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as temp:
            temp.write(text)
            temp.flush()
            os.fsync(temp.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(f"usage: {sys.argv[0]} <BakaSU-kernel-Kconfig>")

    path = Path(sys.argv[1])
    if path.is_symlink() or not path.is_file():
        raise SystemExit("Kconfig path must be a regular, non-symlink file")
    text = path.read_text(encoding="utf-8")
    counts = {symbol: declaration_count(text, symbol) for symbol in OPTIONS}
    duplicated = {symbol: count for symbol, count in counts.items() if count > 1}
    if duplicated:
        raise SystemExit(f"duplicate SUSFS Kconfig declarations detected: {duplicated}")

    for symbol, count in counts.items():
        if count == 1:
            validate_option(text, symbol)

    missing = [symbol for symbol, count in counts.items() if count == 0]
    if not missing:
        print("BakaSU SUSFS v2.4 Kconfig entries already valid")
        return

    menu = 'menu "KernelSU - SUSFS"'
    if text.count(menu) != 1:
        raise SystemExit("expected exactly one KernelSU - SUSFS menu")
    if declaration_count(text, "KSU_SUSFS_SUS_MAP") != 1:
        raise SystemExit("expected exactly one KSU_SUSFS_SUS_MAP anchor")

    anchor = "\nendmenu\n\nendmenu\n"
    if text.count(anchor) != 1 or text.index(anchor) < text.index(menu):
        raise SystemExit("expected the unique closing SUSFS/KernelSU menu pair")

    additions = "\n" + "\n".join(OPTIONS[symbol]["block"] for symbol in missing) + "\n"
    updated = text.replace(anchor, additions + anchor, 1)

    for symbol in OPTIONS:
        if declaration_count(updated, symbol) != 1:
            raise SystemExit(f"Kconfig patch did not produce exactly one {symbol}")
        validate_option(updated, symbol)

    atomic_write(path, updated)
    print("added missing SUSFS Kconfig option(s): " + ", ".join(missing))


if __name__ == "__main__":
    main()
