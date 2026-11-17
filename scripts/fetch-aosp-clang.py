#!/usr/bin/env python3
"""Fetch an exact AOSP Clang tree from Gitiles with checked, split archives.

Gitiles may terminate a very large archive response without curl noticing. This
helper validates every archive before extraction and recursively splits failed
subtrees into smaller archives, falling back to Git-blob-verified raw files.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", help="Gitiles repository URL")
    parser.add_argument("commit", help="full immutable Git commit")
    parser.add_argument("directory", help="toolchain directory within the repository")
    parser.add_argument("destination", type=Path, help="empty directory to populate")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="optional persistent cache for verified archive and blob downloads",
    )
    return parser.parse_args()


def gitiles_path(path: str) -> str:
    return quote(path.strip("/"), safe="/")


def read_json(base: str, commit: str, path: str) -> dict:
    url = f"{base}/+/{commit}/{gitiles_path(path)}/?format=JSON"
    last_error = None
    for attempt in range(1, 4):
        try:
            with urlopen(url, timeout=90) as response:
                text = response.read().decode("utf-8")
            return json.loads(text[text.index("\n") + 1 :])
        except (OSError, ValueError, URLError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError(f"could not read Gitiles tree {path}: {last_error}")


def safe_tar_members(archive: Path) -> None:
    listing = subprocess.run(
        ["tar", "-tzf", str(archive)],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for name in listing.stdout.splitlines():
        item = PurePosixPath(name)
        if item.is_absolute() or ".." in item.parts:
            raise RuntimeError(f"unsafe member in pinned archive: {name!r}")


def verify_archive(archive: Path) -> bool:
    if not archive.is_file() or archive.stat().st_size == 0:
        return False
    gzip_check = subprocess.run(
        ["gzip", "-t", str(archive)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
    )
    if gzip_check.returncode != 0:
        return False
    try:
        safe_tar_members(archive)
    except (subprocess.CalledProcessError, RuntimeError):
        return False
    return True


def blob_oid(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def fetch_blob(base: str, commit: str, path: str, entry: dict, destination: Path, cache: Path | None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = entry.get("id")
    mode = int(entry.get("mode", 0))
    cached = cache / "blobs" / expected if cache is not None and expected else None
    data = None

    if cached is not None and cached.is_file():
        candidate = cached.read_bytes()
        if blob_oid(candidate) == expected:
            data = candidate
        else:
            cached.unlink()

    if data is None:
        url = f"{base}/+/{commit}/{gitiles_path(path)}?format=TEXT"
        last_error = None
        for attempt in range(1, 4):
            try:
                with urlopen(url, timeout=180) as response:
                    encoded = response.read()
                data = base64.b64decode(encoded, validate=False)
                break
            except (OSError, ValueError, URLError) as exc:
                last_error = exc
                data = None
                if attempt < 3:
                    time.sleep(attempt * 2)
        if data is None:
            raise RuntimeError(f"could not fetch Gitiles blob {path}: {last_error}")
        actual = blob_oid(data)
        if actual != expected:
            raise RuntimeError(f"Git blob hash mismatch for {path}: {actual} != {expected}")
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            temp_cache = cached.with_name(cached.name + f".tmp.{os.getpid()}")
            temp_cache.write_bytes(data)
            os.replace(temp_cache, cached)

    if mode == 0o120000:
        target = data.decode("utf-8")
        if destination.exists() or destination.is_symlink():
            destination.unlink()
        destination.symlink_to(target)
    else:
        destination.write_bytes(data)
        if mode:
            destination.chmod(mode & 0o777)


def download_archive(url: str, path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + f".part.{os.getpid()}")
    try:
        result = subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--retry",
                "3",
                "--retry-all-errors",
                "--retry-delay",
                "3",
                "--retry-max-time",
                "900",
                url,
                "--output",
                str(part),
            ],
            check=False,
        )
        if result.returncode != 0 or not verify_archive(part):
            return False
        os.replace(part, path)
        return True
    finally:
        if part.exists():
            part.unlink()


def fetch_tree(
    base: str,
    commit: str,
    root: str,
    relative: str,
    destination: Path,
    cache: Path | None,
    depth: int = 0,
) -> None:
    if depth > 20:
        raise RuntimeError(f"Gitiles tree nesting is unexpectedly deep at {relative}")

    cache_archive = None
    if cache is not None:
        cache_archive = cache / "archives" / commit / (relative.replace("/", "__") + ".tar.gz")
    archive = None
    if cache_archive is not None and cache_archive.is_file():
        if verify_archive(cache_archive):
            archive = cache_archive
        else:
            cache_archive.unlink()

    if archive is None:
        archive_url = f"{base}/+archive/{commit}/{gitiles_path(root + '/' + relative)}.tar.gz"
        with tempfile.TemporaryDirectory(prefix="aosp-clang-archive-") as temp_dir:
            downloaded = Path(temp_dir) / "subtree.tar.gz"
            print(f"Fetching Clang subtree {relative} from pinned Gitiles commit", flush=True)
            if download_archive(archive_url, downloaded):
                if cache_archive is not None:
                    cache_archive.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(downloaded, cache_archive)
                    archive = cache_archive
                else:
                    destination.mkdir(parents=True, exist_ok=True)
                    subprocess.run(
                        ["tar", "-xzf", str(downloaded), "-C", str(destination), "--no-same-owner"],
                        check=True,
                    )
                    print(
                        f"Verified {relative}: {downloaded.stat().st_size} bytes, "
                        f"SHA-256 {hashlib.sha256(downloaded.read_bytes()).hexdigest()}",
                        flush=True,
                    )
                    return

    if archive is not None:
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["tar", "-xzf", str(archive), "-C", str(destination), "--no-same-owner"],
            check=True,
        )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        print(f"Verified cached {relative}: {archive.stat().st_size} bytes, SHA-256 {digest}", flush=True)
        return

    print(f"Archive for {relative} was incomplete; recursively splitting this pinned tree", flush=True)
    tree = read_json(base, commit, root + "/" + relative)
    entries = tree.get("entries", [])
    if not entries:
        raise RuntimeError(f"empty or unreadable Gitiles tree: {relative}")
    for entry in entries:
        child = relative + "/" + entry["name"]
        child_dest = destination / entry["name"]
        if entry.get("type") == "tree":
            fetch_tree(base, commit, root, child, child_dest, cache, depth + 1)
        elif entry.get("type") == "blob":
            fetch_blob(base, commit, root + "/" + child, entry, child_dest, cache)
        else:
            raise RuntimeError(f"unsupported Gitiles entry type at {child}: {entry.get('type')}")


def main() -> int:
    args = parse_args()
    base = args.base_url.rstrip("/")
    commit = args.commit.lower()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise SystemExit("commit must be a full 40-character hexadecimal Git SHA")
    root = args.directory.strip("/")
    if not root or ".." in PurePosixPath(root).parts:
        raise SystemExit("toolchain directory must be a safe relative path")

    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise SystemExit(f"destination must be empty: {destination}")
    cache = args.cache_dir.resolve() if args.cache_dir else None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    root_tree = read_json(base, commit, root)
    entries = root_tree.get("entries", [])
    if not entries:
        raise SystemExit(f"pinned Clang directory is empty or unavailable: {root}")

    for entry in entries:
        relative = entry["name"]
        target = destination / relative
        if entry.get("type") == "tree":
            fetch_tree(base, commit, root, relative, target, cache)
        elif entry.get("type") == "blob":
            fetch_blob(base, commit, root + "/" + relative, entry, target, cache)
        else:
            raise RuntimeError(f"unsupported Gitiles entry type at {relative}: {entry.get('type')}")

    clang = destination / "bin" / "clang"
    if not clang.is_file() or not os.access(clang, os.X_OK):
        raise RuntimeError("the pinned Clang tree was fetched but bin/clang is missing or not executable")
    print(f"Complete verified Clang tree at {destination}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
