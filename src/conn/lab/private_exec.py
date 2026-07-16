from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import sys
from typing import Sequence


MAX_REQUEST_BYTES = 65_536
_ENVIRONMENT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass(frozen=True, slots=True)
class PrivateRequest:
    command: tuple[str, ...]
    environment: dict[str, str]


def encode_request(
    command: Sequence[str],
    *,
    environment: dict[str, str] | None = None,
) -> str:
    request = _validate(command, environment or {})
    payload = json.dumps(
        {
            "schema_version": 1,
            "command": list(request.command),
            "environment": request.environment,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(payload.encode()) > MAX_REQUEST_BYTES:
        raise ValueError("private request exceeds byte limit")
    return payload


def parse_request(payload: str) -> PrivateRequest:
    if len(payload.encode()) > MAX_REQUEST_BYTES:
        raise ValueError("private request exceeds byte limit")
    try:
        raw = json.loads(payload)
    except (TypeError, ValueError) as error:
        raise ValueError("private request is invalid") from error
    if (
        not isinstance(raw, dict)
        or set(raw) != {"schema_version", "command", "environment"}
        or raw.get("schema_version") != 1
    ):
        raise ValueError("private request is invalid")
    return _validate(raw.get("command"), raw.get("environment"))


def _validate(command: object, environment: object) -> PrivateRequest:
    if (
        not isinstance(command, (list, tuple))
        or not 1 <= len(command) <= 128
        or any(
            not isinstance(item, str)
            or not item
            or len(item) > 4_096
            or "\x00" in item
            for item in command
        )
    ):
        raise ValueError("private request command is invalid")
    if not isinstance(environment, dict) or len(environment) > 16:
        raise ValueError("private environment is invalid")
    clean_environment: dict[str, str] = {}
    for key, value in environment.items():
        if (
            not isinstance(key, str)
            or not _ENVIRONMENT_KEY.fullmatch(key)
            or key == "CONN_SERVER_PORT"
            or not isinstance(value, str)
            or not value
            or len(value) > 4_096
            or "\x00" in value
        ):
            raise ValueError("private environment is invalid")
        clean_environment[key] = value
    return PrivateRequest(tuple(command), clean_environment)


def main() -> None:
    payload = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("private request exceeds byte limit")
    request = parse_request(payload.decode())
    os.execvpe(
        request.command[0],
        request.command,
        os.environ | request.environment,
    )


if __name__ == "__main__":
    main()
