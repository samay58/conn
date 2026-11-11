"""OAuth sign-in for remote MCP servers. Tokens live in the macOS login
Keychain through `keyring` (Security framework, so no secret ever appears on a
command line). The sign-in callback listens on 127.0.0.1 only. The daemon never
opens a browser: a background process that pops windows would surprise Samay
mid-sentence, so only the explicit `--mcp-login` command does.
"""

from __future__ import annotations

import asyncio
import subprocess
from urllib.parse import parse_qs, urlparse

import keyring
from keyring.errors import PasswordDeleteError
from mcp.client.auth import AuthorizationCodeResult, OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from .config import McpServerCfg

CALLBACK_PORT = 8791
CALLBACK_TIMEOUT_S = 300.0
_SERVICE_PREFIX = "conn-mcp-"

CLIENT_METADATA = OAuthClientMetadata(
    client_name="Conn",
    redirect_uris=[f"http://127.0.0.1:{CALLBACK_PORT}/callback"],
    grant_types=["authorization_code", "refresh_token"],
    response_types=["code"],
    token_endpoint_auth_method="none",
)

_DONE_PAGE = (b"<!doctype html><meta charset=utf-8><title>Conn</title>"
              b"<p>Conn is signed in. You can close this tab.</p>")


class McpLoginRequired(Exception):
    """No usable tokens; the daemon skips this server until `--mcp-login` runs."""


class McpLoginFailed(Exception):
    """Sign-in did not finish. The message is a short reason code, never server text."""


def _service(name: str) -> str:
    return _SERVICE_PREFIX + name


class KeychainTokenStorage:
    def __init__(self, name: str):
        self._name = name

    def __repr__(self) -> str:
        return f"KeychainTokenStorage({self._name!r})"

    async def _read(self, account: str, model):
        raw = await asyncio.to_thread(keyring.get_password, _service(self._name), account)
        if not raw:
            return None
        try:
            return model.model_validate_json(raw)
        except ValueError:
            return None  # corrupt value counts as absent

    async def _write(self, account: str, value) -> None:
        await asyncio.to_thread(keyring.set_password, _service(self._name), account,
                                value.model_dump_json())

    async def get_tokens(self) -> OAuthToken | None:
        return await self._read("tokens", OAuthToken)

    async def set_tokens(self, tokens: OAuthToken) -> None:
        await self._write("tokens", tokens)

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return await self._read("client", OAuthClientInformationFull)

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        await self._write("client", client_info)


def has_tokens(name: str) -> bool:
    try:
        return bool(keyring.get_password(_service(name), "tokens"))
    except Exception:  # noqa: BLE001 - a locked or broken Keychain reads as signed out
        return False


def logout(name: str) -> None:
    for account in ("tokens", "client"):
        try:
            keyring.delete_password(_service(name), account)
        except PasswordDeleteError:
            pass


class LoopbackCallback:
    """One-shot HTTP listener for the OAuth redirect, bound to 127.0.0.1."""

    host = "127.0.0.1"

    def __init__(self, port: int = CALLBACK_PORT, timeout_s: float = CALLBACK_TIMEOUT_S):
        self.port = port
        self._timeout_s = timeout_s
        self._server: asyncio.Server | None = None
        self._future: asyncio.Future | None = None

    async def start(self) -> None:
        self._future = asyncio.get_running_loop().create_future()
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def wait(self) -> AuthorizationCodeResult:
        try:
            return await asyncio.wait_for(asyncio.shield(self._future), self._timeout_s)
        except TimeoutError:
            raise McpLoginFailed("timeout") from None
        finally:
            await self.close()

    async def _handle(self, reader, writer) -> None:
        status, body = "404 Not Found", b""
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
            parts = head.split(b"\r\n", 1)[0].decode("latin-1").split(" ")
            target = urlparse(parts[1]) if len(parts) >= 2 and parts[0] == "GET" else None
            if target is not None and target.path == "/callback":
                query = {k: v[0] for k, v in parse_qs(target.query).items()}
                if "error" in query:
                    reason = "".join(c for c in query["error"] if c.isalnum() or c == "_")[:40]
                    self._finish(exc=McpLoginFailed(reason or "oauth_error"))
                    status, body = "400 Bad Request", b"Sign-in was not completed."
                elif query.get("code"):
                    self._finish(result=AuthorizationCodeResult(
                        code=query["code"], state=query.get("state"), iss=query.get("iss")))
                    status, body = "200 OK", _DONE_PAGE
                else:
                    status, body = "400 Bad Request", b"Missing code."
        except Exception:  # noqa: BLE001 - a malformed request just gets 404
            pass
        writer.write(f"HTTP/1.1 {status}\r\nContent-Type: text/html\r\n"
                     f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body)
        try:
            await writer.drain()
        finally:
            writer.close()

    def _finish(self, *, result=None, exc=None) -> None:
        if self._future is not None and not self._future.done():
            if exc is not None:
                self._future.set_exception(exc)
            else:
                self._future.set_result(result)


def daemon_auth(server_cfg: McpServerCfg) -> OAuthClientProvider | None:
    if server_cfg.auth != "oauth":
        return None
    name = server_cfg.name

    async def refuse_redirect(_url: str) -> None:
        raise McpLoginRequired(name)

    async def refuse_callback() -> AuthorizationCodeResult:
        raise McpLoginRequired(name)

    return OAuthClientProvider(
        server_url=server_cfg.url, client_metadata=CLIENT_METADATA,
        storage=KeychainTokenStorage(name),
        redirect_handler=refuse_redirect, callback_handler=refuse_callback)


def _find(error: BaseException, kind: type) -> BaseException | None:
    if isinstance(error, kind):
        return error
    for inner in getattr(error, "exceptions", ()):
        found = _find(inner, kind)
        if found is not None:
            return found
    return None


def _open_in_browser(url: str) -> None:
    subprocess.run(["/usr/bin/open", url], check=False)


async def login(server_cfg: McpServerCfg, *, port: int = CALLBACK_PORT,
                timeout_s: float = CALLBACK_TIMEOUT_S, opener=_open_in_browser) -> list[str]:
    from .mcp_client import _auth_http_client

    callback = LoopbackCallback(port=port, timeout_s=timeout_s)

    async def redirect(url: str) -> None:
        if urlparse(url).scheme != "https":
            raise McpLoginFailed("insecure_authorization_url")
        await asyncio.to_thread(opener, url)

    provider = OAuthClientProvider(
        server_url=server_cfg.url, client_metadata=CLIENT_METADATA,
        storage=KeychainTokenStorage(server_cfg.name),
        redirect_handler=redirect, callback_handler=callback.wait)
    await callback.start()
    names: list[str] = []
    try:
        async with _auth_http_client(server_cfg.url, provider) as client:
            cursor = None
            while True:
                page = await client.list_tools(cursor=cursor)
                names.extend(t.name for t in page.tools)
                cursor = page.next_cursor
                if cursor is None:
                    break
    except BaseExceptionGroup as group:
        failed = _find(group, McpLoginFailed)
        if failed is not None:
            raise failed from None
        raise
    finally:
        await callback.close()
    return names
