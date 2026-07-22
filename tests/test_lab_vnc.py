import struct

import pytest

from conn.lab.vnc import (
    VNCClient,
    connect_with_retry,
    logical_to_framebuffer,
    parse_tart_vnc,
    vnc_key,
)


class FakeSocket:
    def __init__(self, response: bytes):
        self.response = bytearray(response)
        self.sent = bytearray()

    def recv(self, size: int) -> bytes:
        chunk = bytes(self.response[:size])
        del self.response[:size]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def close(self) -> None:
        pass


def test_tart_vnc_endpoint_parser_accepts_only_loopback_url() -> None:
    assert parse_tart_vnc(
        "Opening vnc://:upon-siege-habit-time@127.0.0.1:57622..."
    ) == ("upon-siege-habit-time", 57622)
    assert parse_tart_vnc("vnc://:secret@10.0.0.2:5900") is None


def test_vnc_password_key_reverses_each_bit() -> None:
    assert vnc_key("password") == bytes.fromhex("0e86ceceeef64e26")


def test_logical_points_scale_to_retina_framebuffer() -> None:
    assert logical_to_framebuffer(
        point=(784, 15),
        logical_size=(1024, 768),
        framebuffer_size=(2048, 1536),
    ) == (1568, 30)


def test_client_authenticates_and_sends_physical_pointer_click() -> None:
    challenge = bytes(range(16))
    pixel_format = struct.pack(
        ">BBBBHHHBBBxxx", 32, 24, 0, 1, 255, 255, 255, 16, 8, 0
    )
    response = (
        b"RFB 003.008\n"
        + b"\x01\x02"
        + challenge
        + b"\x00\x00\x00\x00"
        + struct.pack(">HH", 2048, 1536)
        + pixel_format
        + struct.pack(">I", 14)
        + b"Virtualization"
    )
    socket = FakeSocket(response)
    client = VNCClient.connect(
        "secret",
        57622,
        socket_factory=lambda *_args, **_kwargs: socket,
        encrypt=lambda _challenge, _password: b"x" * 16,
    )

    client.click((873, 166), logical_size=(1024, 768))

    assert bytes(socket.sent).endswith(
        b"".join(
            struct.pack(">BBHH", 5, mask, 1746, 332)
            for mask in (0, 1, 0)
        )
    )


def test_connect_retries_two_preinput_platform_failures() -> None:
    attempts = []
    expected = object()

    def connector(password: str, port: int):
        attempts.append((password, port))
        if len(attempts) < 3:
            raise PermissionError(1, "Operation not permitted")
        return expected

    result = connect_with_retry(
        "secret",
        57622,
        connector=connector,
        sleeper=lambda _delay: None,
    )

    assert result is expected
    assert attempts == [("secret", 57622)] * 3


def test_connect_stops_after_three_preinput_failures() -> None:
    attempts = []

    def connector(password: str, port: int):
        attempts.append((password, port))
        raise PermissionError(1, "Operation not permitted")

    with pytest.raises(PermissionError):
        connect_with_retry(
            "secret",
            57622,
            connector=connector,
            sleeper=lambda _delay: None,
        )

    assert attempts == [("secret", 57622)] * 3


def test_client_types_bounded_ascii_as_native_key_events() -> None:
    socket = FakeSocket(b"")
    client = VNCClient(
        connection=socket,
        framebuffer_size=(2048, 1536),
        pixel_format=(),
    )

    client.type_text("Seed 1")

    assert bytes(socket.sent) == b"".join(
        struct.pack(">BBxxI", 4, down, ord(character))
        for character in "Seed 1"
        for down in (1, 0)
    )


def test_client_sends_modifier_chord_as_ordered_native_key_events() -> None:
    socket = FakeSocket(b"")
    client = VNCClient(
        connection=socket,
        framebuffer_size=(2048, 1536),
        pixel_format=(),
    )

    client.key_chord(("meta", "n"))

    assert bytes(socket.sent) == b"".join([
        struct.pack(">BBxxI", 4, 1, 0xFFEB),
        struct.pack(">BBxxI", 4, 1, ord("n")),
        struct.pack(">BBxxI", 4, 0, ord("n")),
        struct.pack(">BBxxI", 4, 0, 0xFFEB),
    ])
