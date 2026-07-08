"""Process identity for TCC. Grants bind to the code image the kernel is
actually running, not to the path that launched it. Framework python is a
launcher that execs Python.app, so a grant on .venv/bin/python (or its
realpath bin/python3.14) lands on a binary that never runs. This module names
the artifact TCC checks: the live process image from proc_pidpath, mapped to
the enclosing .app bundle when there is one, because the bundle is what the
Settings pane adds cleanly.
"""

from __future__ import annotations

import ctypes
import os
import sys

# proc_pidpath caps the buffer at PROC_PIDPATHINFO_MAXSIZE (4 * MAXPATHLEN).
_PIDPATH_BUF = 4 * 1024


def process_image_path(pid: int | None = None) -> str | None:
    """The executable image the kernel loaded for this process, from
    proc_pidpath. None off-macOS or on lookup failure."""
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError:
        return None
    buf = ctypes.create_string_buffer(_PIDPATH_BUF)
    n = libproc.proc_pidpath(pid if pid is not None else os.getpid(), buf, len(buf))
    if n <= 0:
        return None
    return buf.value.decode("utf-8", "surrogateescape")


def app_bundle_of(image_path: str) -> str | None:
    """The innermost .app bundle enclosing an image path, or None. The
    innermost wins because nested bundles (helpers inside an app) get their
    own TCC identity."""
    parts = image_path.split(os.sep)
    for index in range(len(parts) - 1, -1, -1):
        if parts[index].endswith(".app"):
            return os.sep.join(parts[: index + 1])
    return None


def grant_target(image_path: str | None = None) -> str:
    """The path to grant in System Settings for the current (or given)
    process image: the enclosing .app bundle when there is one, else the
    bare image binary. Falls back to sys.executable's realpath when
    proc_pidpath is unavailable, which is the best remaining guess."""
    image = image_path or process_image_path()
    if image is None:
        return os.path.realpath(sys.executable)
    return app_bundle_of(image) or image


def python_ax_trusted() -> bool | None:
    """The daemon's own Accessibility trust. None when the AX framework is
    unavailable (non-mac test hosts), which surfaces as unknown, not as a
    false alarm."""
    try:
        from ApplicationServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())
    except Exception:
        return None


def describe_identity() -> dict:
    """Everything doctor and refusal text need in one shot."""
    image = process_image_path()
    return {
        "executable": sys.executable,
        "image": image,
        "grant_target": grant_target(image),
    }
