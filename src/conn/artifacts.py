from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


_REDACTED_KEYS = {
    "api_key",
    "clipboard",
    "clipboard_body",
    "image",
    "image_bytes",
    "image_data",
    "image_data_url",
    "secret",
    "token",
}


@dataclass(frozen=True, slots=True)
class ArtifactResult:
    path: Path
    preview: str


class ArtifactWriter:
    def __init__(self, data_dir: Path, *, inline_limit: int = 65_536,
                 preview_limit: int = 500):
        self.data_dir = Path(data_dir)
        self.inline_limit = inline_limit
        self.preview_limit = preview_limit

    def write(self, *, session_id: str, call_id: str, name: str,
              arguments: dict, ok: bool, output: str,
              turn_id: str | None, response_epoch: int | None,
              observation_epoch: int | None) -> ArtifactResult:
        day = time.strftime("%Y-%m-%d")
        out_dir = self.data_dir / "tool-results" / day / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        call_digest = hashlib.sha256(call_id.encode()).hexdigest()[:24]
        path = out_dir / f"call-{call_digest}.json"
        output_bytes = output.encode()
        output_digest = hashlib.sha256(output_bytes).hexdigest()
        parsed, output_format = _parse_output(output)
        stored = _sanitize_images(parsed) if output_format == "json" else parsed
        truncated = len(output_bytes) > self.inline_limit
        full_content_path: str | None = None
        inline_output = stored
        if truncated:
            suffix = "json" if output_format == "json" else "txt"
            sidecar = out_dir / f"call-{call_digest}-output.{suffix}"
            sidecar_output = (
                json.dumps(stored, ensure_ascii=False, sort_keys=True)
                if output_format == "json" else output
            )
            _atomic_write(sidecar, sidecar_output)
            full_content_path = str(sidecar)
            inline_output = None
        wrapper = {
            "schema_version": 1,
            "session_id": session_id,
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
            "ok": ok,
            "output": inline_output,
            "output_format": output_format,
            "output_bytes": len(output_bytes),
            "output_sha256": output_digest,
            "output_truncated": truncated,
            "full_content_path": full_content_path,
            "turn_id": turn_id,
            "response_epoch": response_epoch,
            "observation_epoch": observation_epoch,
        }
        _atomic_write(path, json.dumps(wrapper, indent=2, sort_keys=True))
        preview = json.dumps({
            "call_id": call_id,
            "name": name,
            "ok": ok,
            "output_bytes": len(output_bytes),
            "output_sha256": output_digest,
            "output_truncated": truncated,
            "full_content_path": full_content_path,
        }, sort_keys=True)
        return ArtifactResult(path=path, preview=preview)

    def trace_preview(self, name: str, output: str) -> str:
        parsed, output_format = _parse_output(output)
        if output_format == "text":
            return _bounded_metadata(output, self.preview_limit)
        sanitized = _sanitize(parsed)
        preview = json.dumps(sanitized, sort_keys=True, separators=(",", ":"))
        if len(preview.encode()) <= self.preview_limit:
            return preview
        return _bounded_metadata(output, self.preview_limit)


def _parse_output(output: str) -> tuple[object, str]:
    try:
        return json.loads(output), "json"
    except (TypeError, ValueError):
        return output, "text"


def _sanitize(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, item in value.items():
            normalized = key.lower()
            if normalized == "nodes":
                sanitized[key] = "<native-tree-omitted>"
            elif normalized in _REDACTED_KEYS or normalized.endswith("_secret"):
                sanitized[key] = "<redacted>"
            else:
                sanitized[key] = _sanitize(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item) for item in value[:20]]
    if isinstance(value, str) and value.startswith("data:image/"):
        return "<redacted>"
    return value


def _sanitize_images(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if key.lower() in {"image", "image_bytes", "image_data", "image_data_url"}
                else _sanitize_images(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_images(item) for item in value]
    if isinstance(value, str) and value.startswith("data:image/"):
        return "<redacted>"
    return value


def _bounded_metadata(output: str, limit: int) -> str:
    encoded = output.encode()
    payload = {
        "output_bytes": len(encoded),
        "output_sha256": hashlib.sha256(encoded).hexdigest(),
        "output_truncated": len(encoded) > limit,
    }
    return json.dumps(payload, sort_keys=True)


def _atomic_write(path: Path, content: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
