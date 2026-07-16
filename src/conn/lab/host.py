from __future__ import annotations

import hashlib
import os
from pathlib import Path


def metadata_digest(
    roots: tuple[Path, ...],
    *,
    base: Path,
    max_entries: int = 50_000,
    max_depth: int = 2,
) -> str:
    if not 1 <= max_entries <= 100_000:
        raise ValueError("metadata entry limit is invalid")
    if not 0 <= max_depth <= 4:
        raise ValueError("metadata depth is invalid")
    base = base.expanduser().resolve(strict=False)
    digest = hashlib.sha256()
    entries = 0
    for root_index, raw_root in enumerate(roots):
        root = raw_root.expanduser().resolve(strict=False)
        if not root.exists():
            digest.update(f"{root_index}:missing\0".encode())
            continue
        candidates = [root]
        if root.is_dir():
            for current, directories, files in os.walk(
                root, followlinks=False
            ):
                current_path = Path(current)
                depth = len(current_path.relative_to(root).parts)
                directories.sort()
                files.sort()
                if depth >= max_depth:
                    directories.clear()
                candidates.extend(current_path / name for name in directories)
                candidates.extend(current_path / name for name in files)
        for path in sorted(set(candidates)):
            entries += 1
            if entries > max_entries:
                raise RuntimeError("host metadata watch is unbounded")
            try:
                stat = path.stat(follow_symlinks=False)
            except OSError as error:
                digest.update(
                    f"{root_index}:unreadable:{type(error).__name__}\0".encode()
                )
                continue
            try:
                relative = path.relative_to(base)
            except ValueError:
                relative = Path(f"root-{root_index}") / path.relative_to(root)
            digest.update(str(relative).encode())
            digest.update(b"\0")
            digest.update(
                f"{stat.st_mode}:{stat.st_size}:{stat.st_mtime_ns}".encode()
            )
            digest.update(b"\0")
    return digest.hexdigest()


def capture_host_snapshot() -> dict:
    import AppKit
    import Quartz

    frontmost = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    event = Quartz.CGEventCreate(None)
    location = Quartz.CGEventGetLocation(event)
    home = Path.home()
    return {
        "frontmost_bundle": (
            frontmost.bundleIdentifier()
            if frontmost is not None and frontmost.bundleIdentifier()
            else "unknown"
        ),
        "pointer": {
            "x": round(float(location.x), 3),
            "y": round(float(location.y), 3),
        },
        "clipboard_sha256": _clipboard_digest(
            AppKit.NSPasteboard.generalPasteboard()
        ),
        "applications_sha256": metadata_digest(
            (Path("/Applications"),),
            base=Path("/"),
            max_depth=1,
        ),
        "personal_data_sha256": personal_data_digest(home),
    }


def personal_data_digest(home: Path) -> str:
    home = home.expanduser().resolve(strict=False)
    roots = (
        home / "Desktop",
        home / "Documents",
        home / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite",
        home / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite-wal",
        home / "Library/Safari/History.db",
        home / "Library/Safari/History.db-wal",
    )
    return metadata_digest(roots, base=home, max_depth=2)


def _clipboard_digest(pasteboard) -> str:
    digest = hashlib.sha256()
    items = list(pasteboard.pasteboardItems() or [])
    if len(items) > 128:
        raise RuntimeError("host clipboard item set is unbounded")
    total_bytes = 0
    for item in items:
        types = sorted(str(value) for value in (item.types() or []))
        if len(types) > 128:
            raise RuntimeError("host clipboard type set is unbounded")
        for type_name in types:
            data = item.dataForType_(type_name)
            raw = bytes(data) if data is not None else b""
            total_bytes += len(raw)
            if total_bytes > 16_000_000:
                raise RuntimeError("host clipboard is unbounded")
            digest.update(type_name.encode())
            digest.update(b"\0")
            digest.update(raw)
            digest.update(b"\0")
    return digest.hexdigest()
