"""conn: push-to-talk voice command surface for the Mac.

  python -m conn --demo            scripted model, real tools, no credentials
  python -m conn --demo --simulate-tools   zero side effects at all
  python -m conn                   live gpt-realtime-2 session (needs OPENAI_API_KEY)
  python -m conn --doctor          environment and permission checks
  python -m conn --eval            run the demo eval suite, write trace artifacts
  python -m conn --latency-report <trace.jsonl>   print latency spans + budget pass/fail
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from .app import ConnApp
from .config import load_config
from .events import new_id
from .tools.base import ExecutionContext
from .tools.harness import ToolHarness
from .tools.registry import build_registry, export_openai


def main() -> None:
    parser = argparse.ArgumentParser(prog="conn", description=__doc__)
    parser.add_argument("--demo", action="store_true", help="scripted model, no credentials")
    parser.add_argument("--simulate-tools", action="store_true", help="with --demo: canned tool results, zero side effects")
    parser.add_argument("--doctor", action="store_true", help="run environment checks")
    parser.add_argument("--eval", action="store_true", help="run the demo eval suite")
    parser.add_argument("--latency-report", type=Path, default=None, metavar="TRACE_JSONL", help="print latency spans and budget pass/fail for a trace file")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--no-audio", action="store_true", help="live mode without mic/speaker")
    parser.add_argument("--no-hotkey", action="store_true", help="disable the global hotkey")
    args = parser.parse_args()

    if args.latency_report:
        from .latency import format_report, spans

        print(format_report(spans(args.latency_report)))
        return

    cfg = load_config(args.config)

    if args.doctor:
        from .doctor import format_report, run_doctor

        print(format_report(run_doctor(cfg)))
        return

    if args.eval:
        from .evals import run_evals

        sys.exit(run_evals(cfg))

    asyncio.run(_serve(cfg, args))


async def _serve(cfg, args) -> None:
    from .tools.ax import MacAxBackend, SnapshotStore

    registry = build_registry()
    session_shots = cfg.data_dir / "screenshots" / new_id("shots")
    ax_store = SnapshotStore(MacAxBackend(), cfg)
    ctx = ExecutionContext(cfg=cfg, screenshot_dir=session_shots, ax=ax_store)

    if args.demo:
        from .realtime.fake import FakeRealtimeAdapter
        from .tools.fake_executors import FAKE_EXECUTORS

        executors = FAKE_EXECUTORS if args.simulate_tools else None
        adapter = FakeRealtimeAdapter()
        audio = None
    else:
        if not cfg.api_key:
            print("OPENAI_API_KEY is not set. Run with --demo, or export the key.", file=sys.stderr)
            sys.exit(2)
        from .prompt import INSTRUCTIONS
        from .realtime.openai_ws import OpenAIRealtimeAdapter

        executors = None
        adapter = OpenAIRealtimeAdapter(cfg, export_openai(registry), INSTRUCTIONS)
        audio = None
        if not args.no_audio:
            try:
                from .audio import AudioPipe

                audio = AudioPipe(on_pcm=lambda pcm: None, on_drain=lambda: None)
            except Exception as e:
                print(f"audio unavailable ({e}); continuing in text mode", file=sys.stderr)

    harness = ToolHarness(registry, cfg, ctx, executors=executors)
    app = ConnApp(cfg, adapter, harness, audio=audio)

    loop = asyncio.get_running_loop()
    if audio is not None:
        from .events import PlaybackDrained

        audio.on_pcm = lambda pcm: asyncio.ensure_future(adapter.append_audio(pcm))
        audio.on_drain = lambda: asyncio.ensure_future(app.dispatch(PlaybackDrained()))
        audio.on_level = lambda source, value: app.publish({"type": "level", "source": source, "value": round(value, 3)})
        audio.start(loop)

    hotkey = None
    if not args.no_hotkey and not args.demo:
        from .hotkey import wire_hotkey

        hotkey = wire_hotkey(cfg.hotkeys.ptt, app, loop)

    await app.start()
    mode = "demo" if args.demo else "live"
    hk = f"global PTT on {cfg.hotkeys.ptt}" if hotkey else "console PTT only (hold Space)"
    print(f"conn {mode} session {app.session_id}")
    print(f"console: http://{cfg.server.host}:{cfg.server.port}  ({hk})")
    print(f"budget: ${cfg.budget.session_cap_usd:.2f} cap, warn at ${cfg.budget.warn_at_usd:.2f}")

    from .server.http import serve

    try:
        await serve(app)
    finally:
        if hotkey:
            hotkey.stop()
        if audio is not None:
            audio.stop()
        await app.stop()


if __name__ == "__main__":
    main()
