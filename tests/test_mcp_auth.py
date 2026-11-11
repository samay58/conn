import asyncio
import subprocess
import urllib.error
import urllib.request
import webbrowser
from unittest.mock import patch

import pytest
from mcp import Client
from mcp.shared.auth import (
    AuthorizationCodeResult,
    OAuthClientInformationFull,
    OAuthToken,
)

from conn import doctor, mcp_auth
from conn.config import Config, McpCfg, McpServerCfg, McpToolCfg
from conn.mcp_auth import (
    KeychainTokenStorage,
    LoopbackCallback,
    McpLoginFailed,
    McpLoginRequired,
    daemon_auth,
    logout,
)
from conn.mcp_client import McpManager

from test_mcp_client import make_server

SECRET_ACCESS = "access-secret-123"
SECRET_REFRESH = "refresh-secret-456"


class FakeKeyring:
    def __init__(self):
        self.items: dict[tuple[str, str], str] = {}
        self.deleted: list[tuple[str, str]] = []

    def get_password(self, service, account):
        return self.items.get((service, account))

    def set_password(self, service, account, value):
        self.items[(service, account)] = value

    def delete_password(self, service, account):
        self.deleted.append((service, account))
        if (service, account) not in self.items:
            raise mcp_auth.PasswordDeleteError("missing")
        del self.items[(service, account)]


@pytest.fixture
def kr(monkeypatch):
    fake = FakeKeyring()
    monkeypatch.setattr(mcp_auth, "keyring", fake)
    return fake


def oauth_cfg(name="granola", **kw) -> McpServerCfg:
    return McpServerCfg(name=name, url=f"https://{name}.example/mcp", auth="oauth",
                        tools={"a": McpToolCfg(kind="read")}, **kw)


def token() -> OAuthToken:
    return OAuthToken(access_token=SECRET_ACCESS, token_type="Bearer",
                      refresh_token=SECRET_REFRESH)


def client_info() -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id="client-1", redirect_uris=["http://127.0.0.1:8791/callback"],
        token_endpoint_auth_method="none")


def run(coro):
    return asyncio.run(coro)


def test_storage_round_trips_tokens_and_client_info(kr):
    async def go():
        s = KeychainTokenStorage("granola")
        assert await s.get_tokens() is None
        await s.set_tokens(token())
        await s.set_client_info(client_info())
        return await s.get_tokens(), await s.get_client_info()

    tokens, info = run(go())
    assert tokens.access_token == SECRET_ACCESS
    assert info.client_id == "client-1"
    assert {svc for svc, _ in kr.items} == {"conn-mcp-granola"}
    assert {acct for _, acct in kr.items} == {"tokens", "client"}


def test_storage_values_are_json_never_repr(kr):
    import json

    s = KeychainTokenStorage("granola")
    run(s.set_tokens(token()))
    stored = kr.items[("conn-mcp-granola", "tokens")]
    assert json.loads(stored)["access_token"] == SECRET_ACCESS
    assert SECRET_ACCESS not in repr(s) and SECRET_REFRESH not in repr(s)
    kr.items[("conn-mcp-granola", "tokens")] = "{not json"
    assert run(s.get_tokens()) is None


def test_daemon_auth_never_opens_a_browser(kr):
    assert daemon_auth(McpServerCfg(name="p", command=["x"])) is None
    provider = daemon_auth(oauth_cfg())

    async def go():
        with pytest.raises(McpLoginRequired):
            await provider.context.redirect_handler("https://auth.example/authorize")
        with pytest.raises(McpLoginRequired):
            await provider.context.callback_handler()

    with patch.object(subprocess, "run") as sub, patch.object(webbrowser, "open") as web:
        run(go())
    sub.assert_not_called()
    web.assert_not_called()


def test_no_tokens_means_login_required_skip():
    def needs_login(wrap):
        class NeedsLogin:
            async def __aenter__(self):
                if wrap:
                    raise ExceptionGroup("tg", [McpLoginRequired("granola")])
                raise McpLoginRequired("granola")

            async def __aexit__(self, *exc):
                return False

        return NeedsLogin()

    async def go(wrap):
        m = McpManager(McpCfg(servers=[oauth_cfg()]), client_factory=lambda c: needs_login(wrap))
        try:
            await m.start()
            return dict(m.status)
        finally:
            await m.stop()

    for wrap in (False, True):
        assert run(go(wrap))["granola"] == "skipped: login_required"


async def _get(url: str):
    def fetch():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    return await asyncio.to_thread(fetch)


def test_callback_server_returns_code_state_and_iss():
    async def go(query):
        cb = LoopbackCallback(port=0, timeout_s=5)
        await cb.start()
        waiter = asyncio.create_task(cb.wait())
        status, body = await _get(f"http://127.0.0.1:{cb.port}/callback?{query}")
        result = await waiter
        return status, body, result, cb._server

    status, body, result, server = run(go("code=abc&state=xyz&iss=https%3A%2F%2Fauth.example"))
    assert status == 200 and b"Conn is signed in. You can close this tab." in body
    assert result == AuthorizationCodeResult(code="abc", state="xyz", iss="https://auth.example")
    assert server is None  # stopped listening
    assert run(go("code=abc&state=xyz"))[2].iss is None


def test_callback_rejects_error_and_wrong_path():
    async def go():
        cb = LoopbackCallback(port=0, timeout_s=5)
        await cb.start()
        waiter = asyncio.create_task(cb.wait())
        status, _ = await _get(f"http://127.0.0.1:{cb.port}/other")
        assert status == 404 and not waiter.done()
        await _get(f"http://127.0.0.1:{cb.port}/callback?error=access_denied")
        with pytest.raises(McpLoginFailed, match="access_denied"):
            await waiter

    run(go())


def test_callback_binds_loopback_only():
    async def go():
        cb = LoopbackCallback(port=0)
        await cb.start()
        try:
            return cb.host, [s.getsockname()[0] for s in cb._server.sockets]
        finally:
            await cb.close()

    host, bound = run(go())
    assert host == "127.0.0.1" and bound == ["127.0.0.1"]


def test_logout_deletes_both_items(kr):
    run(KeychainTokenStorage("granola").set_tokens(token()))
    logout("granola")
    assert ("conn-mcp-granola", "tokens") in kr.deleted
    assert ("conn-mcp-granola", "client") in kr.deleted
    assert kr.items == {}
    logout("granola")  # missing items are fine


def test_doctor_reports_sign_in_state(kr):
    run(KeychainTokenStorage("granola").set_tokens(token()))
    cfg = Config(mcp=McpCfg(servers=[
        McpServerCfg(name="phoenix", command=["x"], tools={"a": McpToolCfg(kind="read")}),
        oauth_cfg("granola"), oauth_cfg("wispr")]))
    result = doctor._mcp(cfg)
    assert result["status"] == doctor.WARN
    for part in ("phoenix: stdio", "granola: signed in",
                 "wispr: not signed in; run --mcp-login wispr"):
        assert part in result["detail"]
    kr.items[("conn-mcp-wispr", "tokens")] = "x"
    assert doctor._mcp(cfg)["status"] == doctor.OK


def test_tokens_never_in_trace_or_status(kr):
    server = make_server()

    def factory(cfg):
        run_store = KeychainTokenStorage(cfg.name)

        class Stored:
            async def __aenter__(self):
                await run_store.set_tokens(token())
                self._c = Client(server)
                return await self._c.__aenter__()

            async def __aexit__(self, *exc):
                return await self._c.__aexit__(*exc)

        return Stored()

    async def go():
        m = McpManager(McpCfg(servers=[oauth_cfg()]), client_factory=factory)
        try:
            await m.start()
            return dict(m.status), m.drain_events()
        finally:
            await m.stop()

    status, events = run(go())
    assert status["granola"] == "connected"
    blob = repr(status) + repr(events)
    assert SECRET_ACCESS not in blob and SECRET_REFRESH not in blob
    assert kr.items  # tokens really were stored
