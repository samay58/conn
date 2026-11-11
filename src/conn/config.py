from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class HotkeysCfg(BaseModel):
    ptt: str = "alt_r"
    auto: list[str] = Field(default_factory=list)
    confirm: list[str] = Field(default_factory=list)


class RealtimeCfg(BaseModel):
    model: str = "gpt-realtime-2.1"
    voice: str = "marin"
    reasoning_effort: str = "low"
    transcription_language: str = "en"   # ISO 639-1 pin; empty lets short clips decode as any language


class BudgetCfg(BaseModel):
    session_cap_usd: float = 5.00
    warn_at_usd: float = 2.50
    hard_stop: bool = True


class AudioCfg(BaseModel):
    preroll_ms: int = 400
    input_device: str = ""          # substring match against input device names; empty = system default
    low_signal_rms: float = 150.0   # listening windows peaking below this emit a low_signal hint


class SessionCfg(BaseModel):
    idle_timeout_s: int = 300
    done_flash_ms: int = 1500
    tap_threshold_ms: int = 300
    watchdog_timeout_s: float = 600
    reconnect_window_s: float = Field(default=300.0, gt=0)
    reconnect_max_delay_s: float = Field(default=30.0, gt=0)


class AppsCfg(BaseModel):
    allowlist: list[str] = Field(default_factory=list)
    bundle_ids: dict[str, str] = Field(default_factory=dict)
    team_ids: dict[str, str] = Field(default_factory=dict)


class BrowserCfg(BaseModel):
    search_url: str = "https://www.google.com/search?q={q}"


class PhoenixCfg(BaseModel):
    vault_root: str = str(Path.home() / "phoenix")
    qmd_bin: str = "qmd"
    obsidian_vault: str = "phoenix"
    # Phoenix's own index (kept fresh nightly). Empty means
    # <vault_root>/data/qmd/phoenix/index.sqlite and .../config.
    qmd_index: str = ""
    qmd_config_dir: str = ""
    # Collections Conn may search, mapped to their root under vault_root.
    # Work collections (every, nventures) are deliberately absent: search
    # snippets go to the model provider.
    qmd_collections: dict[str, str] = Field(default_factory=lambda: {
        "active": "01-active",
        "career": "02-personal/career-exploration",
        "personal": "02-personal",
        "kb": "04-knowledge-base",
        "mymind": "04-knowledge-base/mymind-cards",
    })


class ShortcutsCfg(BaseModel):
    enabled: bool = True
    # Wait this long for a Shortcut to finish; a longer one keeps running
    # and is reported as still running, never killed. The registry's 45 s
    # tool timeout must stay above this plus the list call.
    run_timeout_s: float = Field(default=20.0, gt=0, le=30)


class ScreenshotsCfg(BaseModel):
    keep: bool = False


class ServerCfg(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)


class AxCfg(BaseModel):
    snapshot_ttl_s: float = 10.0
    max_elements: int = 120
    max_depth: int = 12
    deny_bundles: list[str] = Field(
        default_factory=lambda: ["com.1password.1password", "com.apple.keychainaccess"]
    )


class ActionsCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")

    semantic_verify_ms: int = 1200
    visual_verify_ms: int = 2500
    create_verify_ms: int = 2500
    launch_verify_ms: int = 4000
    max_fallbacks: int = 1
    require_verified_success: bool = True
    visual_enabled: bool = False
    keep_failure_artifacts: bool = False


class InteractionsCfg(BaseModel):
    trusted: dict[str, list[str]] = Field(default_factory=dict)


class PricingCfg(BaseModel):
    """USD per 1M tokens."""

    text_in: float = 4.00
    text_out: float = 24.00
    audio_in: float = 32.00
    audio_out: float = 64.00
    cached_in: float = 0.40
    image_in: float = 5.00


class McpToolCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["read", "write"]          # Conn's declaration; plan 015 enforces it
    alias: str = ""                         # model-facing name; default "<server>_<tool>"
    description: str = ""                   # model-facing text, written by Samay or Conn
    preview: str = ""                       # chip text template, e.g. "Capture: {text}"
    fixed_args: dict[str, Any] = Field(default_factory=dict)  # injected, hidden from the model
    param_descriptions: dict[str, str] = Field(default_factory=dict)  # Conn's text for each argument
    timeout_s: float | None = Field(default=None, gt=0, le=60)  # overrides McpCfg.call_timeout_s


class McpServerCfg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str                               # [a-z][a-z0-9]*, used in names and Keychain items
    command: list[str] = Field(default_factory=list)   # stdio: argv
    url: str = ""                           # Streamable HTTP endpoint
    auth: Literal["none", "oauth"] = "none"
    env: dict[str, str] = Field(default_factory=dict, repr=False)
    cwd: str = ""
    withhold_markers: list[str] = Field(default_factory=list)
    tools: dict[str, McpToolCfg] = Field(default_factory=dict)   # the expose list
    connect_timeout_s: float | None = Field(default=None, gt=0, le=30)  # overrides McpCfg's; a cold stdio start can need ~8 s

    @model_validator(mode="after")
    def _check_shape(self) -> "McpServerCfg":
        if not re.fullmatch(r"[a-z][a-z0-9]{0,23}", self.name):
            raise ValueError("mcp server name must match ^[a-z][a-z0-9]{0,23}$")
        if bool(self.command) == bool(self.url):
            raise ValueError("mcp server needs exactly one of command or url")
        if self.command and self.auth != "none":
            raise ValueError("mcp stdio servers cannot use auth")
        return self


class McpCfg(BaseModel):
    enabled: bool = True
    max_tools: int = Field(default=14, ge=0, le=24)
    connect_timeout_s: float = Field(default=3.0, gt=0, le=15)
    call_timeout_s: float = Field(default=20.0, gt=0, le=60)
    servers: list[McpServerCfg] = Field(default_factory=list)


class Config(BaseModel):
    hotkeys: HotkeysCfg = Field(
        default_factory=HotkeysCfg,
        validation_alias=AliasChoices("hotkeys", "hotkey"),
    )
    realtime: RealtimeCfg = RealtimeCfg()
    audio: AudioCfg = AudioCfg()
    budget: BudgetCfg = BudgetCfg()
    session: SessionCfg = SessionCfg()
    apps: AppsCfg = AppsCfg()
    browser: BrowserCfg = BrowserCfg()
    phoenix: PhoenixCfg = PhoenixCfg()
    shortcuts: ShortcutsCfg = ShortcutsCfg()
    screenshots: ScreenshotsCfg = ScreenshotsCfg()
    server: ServerCfg = ServerCfg()
    ax: AxCfg = AxCfg()
    actions: ActionsCfg = ActionsCfg()
    interactions: InteractionsCfg = InteractionsCfg()
    risk_overrides: dict[str, str] = Field(default_factory=dict)
    pricing: PricingCfg = PricingCfg()
    mcp: McpCfg = McpCfg()

    data_dir: Path = PROJECT_ROOT / "data"
    source_path: Path | None = None

    @property
    def hotkey(self) -> HotkeysCfg:
        return self.hotkeys

    @property
    def api_key(self) -> str | None:
        key = os.environ.get("OPENAI_API_KEY")
        if key:
            return key
        key_file = Path.home() / ".config" / "openai" / "key"
        if key_file.exists():
            return key_file.read_text().strip() or None
        return None


def _deep_merge(base: dict, over: dict) -> dict:
    """Tables merge key by key; anything else, lists included, is replaced."""
    merged = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> Config:
    path = path or PROJECT_ROOT / "config.toml"
    raw = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    local = path.with_name("config.local.toml")
    if local.exists():
        with open(local, "rb") as f:
            raw = _deep_merge(raw, tomllib.load(f))
    server_port = os.environ.get("CONN_SERVER_PORT")
    if server_port is not None:
        try:
            port = int(server_port)
        except ValueError as error:
            raise ValueError("CONN_SERVER_PORT must be an integer") from error
        if not 1 <= port <= 65535:
            raise ValueError("CONN_SERVER_PORT must be between 1 and 65535")
        raw = {**raw, "server": {**raw.get("server", {}), "port": port}}
    data_dir = os.environ.get("CONN_DATA_DIR")
    if data_dir is not None:
        if not data_dir.strip():
            raise ValueError("CONN_DATA_DIR must not be empty")
        raw = {**raw, "data_dir": Path(data_dir).expanduser()}
    return Config(**raw, source_path=path)
