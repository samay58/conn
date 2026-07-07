"""Phoenix vault executors: qmd search and Obsidian note opening."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from .base import ExecutionContext, ToolError

_RESULT_HEAD = re.compile(r"^qmd://(?P<collection>[^/]+)/(?P<path>.+?):(?P<line>\d+)\s+#(?P<docid>\w+)")


def parse_qmd_output(text: str) -> list[dict]:
    """qmd search prints result blocks:

    qmd://phoenix/<relpath>:<line> #docid
    Title: ...
    Context: <collection boilerplate, dropped>
    Score: 0.89
    @@ -1,3 @@ (0 before, 35 after)
    <snippet lines>
    <blank line between blocks>
    """
    results: list[dict] = []
    current: dict | None = None
    snippet: list[str] = []
    for line in text.splitlines():
        head = _RESULT_HEAD.match(line)
        if head:
            if current is not None:
                current["snippet"] = "\n".join(snippet).strip()
                results.append(current)
            current = {"path": head["path"], "line": int(head["line"]),
                       "docid": head["docid"], "title": None, "score": None}
            snippet = []
            continue
        if current is None:
            continue
        if line.startswith("Title: "):
            current["title"] = line[len("Title: "):]
        elif line.startswith("Context: ") or line.startswith("@@"):
            continue
        elif line.startswith("Score: "):
            try:
                current["score"] = float(line[len("Score: "):])
            except ValueError:
                pass
        else:
            snippet.append(line)
    if current is not None:
        current["snippet"] = "\n".join(snippet).strip()
        results.append(current)
    return results


def phoenix_search(args: dict, ctx: ExecutionContext) -> dict:
    query = args["query"]
    limit = int(args.get("limit", 5))
    proc = subprocess.run(
        [ctx.cfg.phoenix.qmd_bin, "search", query],
        capture_output=True, text=True, timeout=20,
        cwd=ctx.cfg.phoenix.vault_root,
    )
    if proc.returncode != 0:
        raise ToolError(f"qmd search failed: {proc.stderr.strip()[:300]}")
    results = parse_qmd_output(proc.stdout)[:limit]
    for r in results:
        r["snippet"] = r["snippet"][:400]
    return {"query": query, "results": results, "count": len(results)}


def open_note(args: dict, ctx: ExecutionContext) -> dict:
    raw = str(args["path"]).lstrip("/")
    root = Path(ctx.cfg.phoenix.vault_root).resolve()
    target = (root / raw).resolve()
    if not target.exists() and not raw.endswith(".md"):
        candidate = (root / f"{raw}.md").resolve()
        if candidate.exists():
            target, raw = candidate, f"{raw}.md"
    if not target.exists():
        raise ToolError(f"note_not_found: {raw!r}. Try phoenix_search first.")
    rel = target.relative_to(root).as_posix()
    file_param = rel[:-3] if rel.endswith(".md") else rel
    url = f"obsidian://open?vault={quote(ctx.cfg.phoenix.obsidian_vault)}&file={quote(file_param)}"
    proc = subprocess.run(["/usr/bin/open", url], capture_output=True, timeout=10)
    if proc.returncode != 0:
        raise ToolError(f"could not open note: {proc.stderr.decode().strip()}")
    return {"path": rel, "opened_via": "obsidian_url"}
