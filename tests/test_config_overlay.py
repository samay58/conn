import pytest
from pydantic import ValidationError

from conn.config import Config, McpServerCfg, McpToolCfg, load_config


def _write(path, text):
    path.write_text(text)


def test_local_overlay_merges_over_tracked_config(tmp_path):
    _write(tmp_path / "config.toml",
           '[budget]\nsession_cap_usd = 5.0\n[phoenix]\nqmd_bin = "qmd"\n')
    _write(tmp_path / "config.local.toml", '[phoenix]\nqmd_bin = "/x/qmd"\n')
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.phoenix.qmd_bin == "/x/qmd"
    assert cfg.budget.session_cap_usd == 5.0


def test_local_overlay_appends_mcp_servers(tmp_path):
    _write(tmp_path / "config.toml", "[budget]\nsession_cap_usd = 5.0\n")
    _write(tmp_path / "config.local.toml",
           '[[mcp.servers]]\nname = "granola"\nurl = "https://example.invalid/mcp"\n'
           '[[mcp.servers]]\nname = "local"\ncommand = ["echo"]\n')
    cfg = load_config(tmp_path / "config.toml")
    assert [s.name for s in cfg.mcp.servers] == ["granola", "local"]


def test_local_list_replaces_tracked_list(tmp_path):
    _write(tmp_path / "config.toml",
           '[[mcp.servers]]\nname = "old"\ncommand = ["echo"]\n')
    _write(tmp_path / "config.local.toml",
           '[[mcp.servers]]\nname = "new"\ncommand = ["echo"]\n')
    cfg = load_config(tmp_path / "config.toml")
    assert [s.name for s in cfg.mcp.servers] == ["new"]


def test_missing_overlay_is_fine(tmp_path):
    _write(tmp_path / "config.toml", "[budget]\nsession_cap_usd = 4.0\n")
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.budget.session_cap_usd == 4.0


def test_server_needs_exactly_one_transport():
    with pytest.raises(ValidationError):
        McpServerCfg(name="s", command=["x"], url="https://e.invalid")
    with pytest.raises(ValidationError):
        McpServerCfg(name="s")
    assert McpServerCfg(name="s", command=["x"]).command == ["x"]


def test_server_name_and_stdio_auth_rules():
    with pytest.raises(ValidationError):
        McpServerCfg(name="Bad-Name", command=["x"])
    with pytest.raises(ValidationError):
        McpServerCfg(name="s", command=["x"], auth="oauth")
    assert McpServerCfg(name="s", url="https://e.invalid", auth="oauth").auth == "oauth"


def test_tool_kind_is_required():
    with pytest.raises(ValidationError):
        McpToolCfg()
    with pytest.raises(ValidationError):
        McpServerCfg(name="s", command=["x"], tools={"t": {"alias": "a"}})
    assert McpToolCfg(kind="read").kind == "read"


def test_mcp_disabled_by_default():
    assert Config().mcp.servers == []
