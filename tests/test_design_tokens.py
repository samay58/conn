"""Magic-number guard for Conn's SwiftUI island sources.

All motion/personality/palette/geometry constants must live in
DesignTokens.swift. This scans macos/Sources/Conn/*.swift and fails if any
scanned file reintroduces a magic number in an animation curve, or uses a
forbidden monospace/tracking/uppercased pattern outside the allowed exclusion
list.

Exclusions (not scanned):
- DesignTokens.swift: holds the numbers by design.
- PanelView.swift, WaveformView.swift: frozen panel-era surfaces carrying
  legacy pre-island style. WaveformView rejoins the guard at packet I7 in
  Phase 2 -- do not forget to remove it from EXCLUDED_FILES then.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONN_SOURCES = REPO_ROOT / "macos" / "Sources" / "Conn"

EXCLUDED_FILES = {"DesignTokens.swift", "PanelView.swift", "WaveformView.swift"}

MONOSPACE_FONT_NAMES = ("Menlo", "Monaco", "SFMono", "SF Mono", "Courier")


def find_violations(text: str) -> list[str]:
    """Return a list of forbidden-pattern names found in `text`, empty if none."""
    hits: list[str] = []

    # (a) numeric literal inside an animation curve: .animation(, withAnimation(,
    # or Spring( -- but NOT .animation(minimumInterval: which is a TimelineView
    # refresh schedule, not a design token.
    for match in re.finditer(r"\.animation\(|withAnimation\(|Spring\(", text):
        start = match.start()
        end = match.end()
        # Grab the call's argument list up to the matching close paren
        # (naive depth-tracking; good enough for single-line SwiftUI calls).
        depth = 1
        i = end
        while i < len(text) and depth > 0:
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
            i += 1
        call_text = text[start:i]

        if call_text.startswith(".animation(minimumInterval:"):
            continue

        if re.search(r"\d", call_text):
            hits.append("animation-curve-numeric-literal")

    # (b) design: .monospaced
    if "design: .monospaced" in text:
        hits.append("design-monospaced")

    # (c) monospace font names
    for name in MONOSPACE_FONT_NAMES:
        if name in text:
            hits.append("monospace-font-name")
            break

    # (d) .tracking(
    if ".tracking(" in text:
        hits.append("tracking")

    # (e) .uppercased()
    if ".uppercased()" in text:
        hits.append("uppercased")

    # (f) keyboard reachability: approvals are pointer-only, so no island
    # source may register a keyboard shortcut, focus machinery, key handling,
    # or default-button treatment.
    if ".keyboardShortcut(" in text:
        hits.append("keyboard-shortcut")
    if ".borderedProminent" in text:
        hits.append("default-button-styling")
    if ".focusable(" in text:
        hits.append("focusable")
    if ".onKeyPress(" in text:
        hits.append("on-key-press")
    if "@FocusState" in text:
        hits.append("focus-state")
    if "defaultAction" in text or "cancelAction" in text:
        hits.append("default-action-role")

    return hits


GOOD_SNIPPETS = [
    "TimelineView(.animation(minimumInterval: 1.0/60.0)) { context in }",
    "let x = 1.0\nlet y = someName",
    "Text(title).font(.body)",
]

BAD_SNIPPETS = [
    ("animation-curve-numeric-literal", ".animation(.easeInOut(duration: 0.3), value: x)"),
    ("animation-curve-numeric-literal", "withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) { }"),
    ("animation-curve-numeric-literal", "let s = Spring(response: 0.28, dampingRatio: 0.8)"),
    ("design-monospaced", "Text(x).font(.system(size: 12, design: .monospaced))"),
    ("monospace-font-name", 'Text(x).font(.custom("Menlo", size: 12))'),
    ("monospace-font-name", 'Text(x).font(.custom("SF Mono", size: 12))'),
    ("tracking", "Text(x).tracking(1.2)"),
    ("uppercased", "let s = title.uppercased()"),
    ("keyboard-shortcut", "Button(\"Approve\") {}.keyboardShortcut(.escape)"),
    ("default-button-styling", "Button(\"Approve\") {}.buttonStyle(.borderedProminent)"),
    ("focusable", "Text(x).focusable(true)"),
    ("on-key-press", "content.onKeyPress(.return) { .handled }"),
    ("focus-state", "@FocusState private var focused: Bool"),
    ("default-action-role", "Button(role: .none) {}.keyboardShortcut(.defaultAction)"),
]


@pytest.mark.parametrize("snippet", GOOD_SNIPPETS)
def test_good_snippets_have_no_violations(snippet: str) -> None:
    assert find_violations(snippet) == []


@pytest.mark.parametrize("expected_kind,snippet", BAD_SNIPPETS)
def test_bad_snippets_are_flagged(expected_kind: str, snippet: str) -> None:
    hits = find_violations(snippet)
    assert expected_kind in hits


def _scanned_swift_files() -> list[Path]:
    return sorted(
        p for p in CONN_SOURCES.glob("*.swift") if p.name not in EXCLUDED_FILES
    )


def test_conn_sources_are_clean() -> None:
    files = _scanned_swift_files()
    assert files, "expected at least one scanned Swift file"

    offenders: dict[str, list[str]] = {}
    for path in files:
        text = path.read_text()
        hits = find_violations(text)
        if hits:
            offenders[path.name] = hits

    assert offenders == {}, f"magic-number guard violations: {offenders}"
