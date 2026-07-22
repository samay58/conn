from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class HotkeysCfg(BaseModel):
    ptt: str = "alt_r"
    auto: list[str] = Field(default_factory=list)
    confirm: list[str] = Field(default_factory=list)


class RealtimeCfg(BaseModel):
    model: str = "gpt-realtime-2"
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
    screenshots: ScreenshotsCfg = ScreenshotsCfg()
    server: ServerCfg = ServerCfg()
    ax: AxCfg = AxCfg()
    actions: ActionsCfg = ActionsCfg()
    interactions: InteractionsCfg = InteractionsCfg()
    risk_overrides: dict[str, str] = Field(default_factory=dict)
    pricing: PricingCfg = PricingCfg()

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


def load_config(path: Path | None = None) -> Config:
    path = path or PROJECT_ROOT / "config.toml"
    raw = {}
    if path.exists():
        with open(path, "rb") as f:
            raw = tomllib.load(f)
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
