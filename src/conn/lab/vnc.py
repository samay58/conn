from __future__ import annotations

import ctypes
from dataclasses import dataclass
import re
import socket
import struct
from typing import Callable


_TART_VNC = re.compile(
    r"vnc://:([A-Za-z0-9-]{1,128})@127\.0\.0\.1:([0-9]{1,5})"
)
_KEYSYMS = {
    "shift": 0xFFE1,
    "control": 0xFFE3,
    "meta": 0xFFEB,
    "alt": 0xFFE9,
    "return": 0xFF0D,
    "tab": 0xFF09,
    "escape": 0xFF1B,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
}


def parse_tart_vnc(line: str) -> tuple[str, int] | None:
    match = _TART_VNC.search(line)
    if match is None:
        return None
    port = int(match.group(2))
    if not 1 <= port <= 65535:
        return None
    return match.group(1), port


def vnc_key(password: str) -> bytes:
    source = password.encode()[:8].ljust(8, b"\0")
    return bytes(
        int(f"{value:08b}"[::-1], 2)
        for value in source
    )


def _encrypt_challenge(challenge: bytes, password: str) -> bytes:
    if len(challenge) != 16:
        raise ValueError("VNC challenge must contain 16 bytes")
    library = ctypes.CDLL("/usr/lib/system/libcommonCrypto.dylib")
    library.CCCrypt.argtypes = [
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    output = ctypes.create_string_buffer(16)
    moved = ctypes.c_size_t()
    status = library.CCCrypt(
        0,
        1,
        2,
        vnc_key(password),
        8,
        None,
        challenge,
        16,
        output,
        16,
        ctypes.byref(moved),
    )
    if status != 0 or moved.value != 16:
        raise RuntimeError(f"vnc_des_failed:{status}")
    return output.raw


def logical_to_framebuffer(
    *,
    point: tuple[float, float],
    logical_size: tuple[float, float],
    framebuffer_size: tuple[int, int],
) -> tuple[int, int]:
    logical_width, logical_height = logical_size
    if logical_width <= 0 or logical_height <= 0:
        raise ValueError("logical display size must be positive")
    x = round(point[0] * framebuffer_size[0] / logical_width)
    y = round(point[1] * framebuffer_size[1] / logical_height)
    if not 0 <= x < framebuffer_size[0] or not 0 <= y < framebuffer_size[1]:
        raise ValueError("pointer target is outside the framebuffer")
    return x, y


def _receive_exact(connection, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("vnc_connection_closed")
        data.extend(chunk)
    return bytes(data)


@dataclass(slots=True)
class VNCClient:
    connection: object
    framebuffer_size: tuple[int, int]
    pixel_format: tuple[int, ...]

    @classmethod
    def connect(
        cls,
        password: str,
        port: int,
        *,
        socket_factory: Callable = socket.create_connection,
        encrypt: Callable[[bytes, str], bytes] = _encrypt_challenge,
        timeout_s: float = 5,
    ) -> VNCClient:
        if not 1 <= port <= 65535:
            raise ValueError("VNC port is invalid")
        connection = socket_factory(("127.0.0.1", port), timeout=timeout_s)
        try:
            version = _receive_exact(connection, 12)
            if version != b"RFB 003.008\n":
                raise ConnectionError("unsupported_vnc_version")
            connection.sendall(version)
            security_types = _receive_exact(
                connection,
                _receive_exact(connection, 1)[0],
            )
            if 2 not in security_types:
                raise ConnectionError("vnc_password_auth_unavailable")
            connection.sendall(b"\x02")
            challenge = _receive_exact(connection, 16)
            connection.sendall(encrypt(challenge, password))
            if _receive_exact(connection, 4) != b"\0\0\0\0":
                raise ConnectionError("vnc_authentication_failed")
            connection.sendall(b"\x01")
            header = _receive_exact(connection, 24)
            width, height = struct.unpack(">HH", header[:4])
            pixel_format = struct.unpack(
                ">BBBBHHHBBBxxx", header[4:20]
            )
            name_length = struct.unpack(">I", header[20:24])[0]
            if name_length > 1_024:
                raise ConnectionError("vnc_server_name_too_long")
            _receive_exact(connection, name_length)
            return cls(connection, (width, height), pixel_format)
        except BaseException:
            connection.close()
            raise

    def click(
        self,
        point: tuple[float, float],
        *,
        logical_size: tuple[float, float],
    ) -> None:
        x, y = logical_to_framebuffer(
            point=point,
            logical_size=logical_size,
            framebuffer_size=self.framebuffer_size,
        )
        for mask in (0, 1, 0):
            self.connection.sendall(struct.pack(">BBHH", 5, mask, x, y))

    def type_text(self, text: str) -> None:
        if not text or len(text) > 1_024:
            raise ValueError("VNC text is empty or exceeds the limit")
        if any(not 32 <= ord(character) <= 126 for character in text):
            raise ValueError("VNC text must be printable ASCII")
        for character in text:
            for down in (1, 0):
                self.connection.sendall(
                    struct.pack(">BBxxI", 4, down, ord(character))
                )

    def key_chord(self, keys: tuple[str, ...]) -> None:
        if not 1 <= len(keys) <= 4:
            raise ValueError("VNC key chord must contain 1 to 4 keys")
        values = []
        for key in keys:
            normalized = key.strip().lower()
            if normalized in _KEYSYMS:
                values.append(_KEYSYMS[normalized])
            elif len(normalized) == 1 and normalized.isascii():
                values.append(ord(normalized))
            else:
                raise ValueError("VNC key chord contains an unsupported key")
        for keysym in values:
            self.connection.sendall(struct.pack(">BBxxI", 4, 1, keysym))
        for keysym in reversed(values):
            self.connection.sendall(struct.pack(">BBxxI", 4, 0, keysym))

    def close(self) -> None:
        self.connection.close()
