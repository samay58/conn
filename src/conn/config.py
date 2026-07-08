from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field

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
    session_cap_usd: float = 1.00
    warn_at_usd: float = 0.50
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


class AppsCfg(BaseModel):
    allowlist: list[str] = Field(default_factory=list)


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
    port: int = 8787


class AxCfg(BaseModel):
    snapshot_ttl_s: float = 10.0
    max_elements: int = 120
    max_depth: int = 12
    deny_bundles: list[str] = Field(
        default_factory=lambda: ["com.1password.1password", "com.apple.keychainaccess"]
    )


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
    interactions: InteractionsCfg = InteractionsCfg()
    risk_overrides: dict[str, str] = Field(default_factory=dict)
    pricing: PricingCfg = PricingCfg()

    data_dir: Path = PROJECT_ROOT / "data"

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
    if not path.exists():
        return Config()
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Config(**raw)
