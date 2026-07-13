"""conn: push-to-talk voice command surface for the Mac.

  python -m conn --demo            scripted model, real tools, no credentials
  python -m conn --demo --simulate-tools   zero side effects at all
  python -m conn                   live gpt-realtime-2 session (needs OPENAI_API_KEY)
  python -m conn --doctor          environment and permission checks
  python -m conn --eval            run the demo eval suite, write trace artifacts
  python -m conn --latency-report [trace.jsonl]   latency spans + budget pass/fail (default: newest trace)
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
    parser.add_argument("--eval", action="store_true", help="run the harness-only demo eval suite")
    parser.add_argument(
        "--intent-eval", nargs="?", const="all", default=None,
        metavar="LIMIT",
        help="opt-in live model intent eval over the reviewed corpus; "
             "optional LIMIT caps the sample (billed API usage)")
    parser.add_argument(
        "--action-probe",
        choices=[
            "fixture", "terminal", "safari", "chrome", "notes", "obsidian",
            "all", "fixture-legacy",
        ],
        help="run a bounded hardware action probe",
    )
    parser.add_argument("--latency-report", nargs="?", const="latest", default=None, metavar="TRACE_JSONL", help="print latency spans and budget pass/fail for a trace file (no argument: newest trace)")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--no-audio", action="store_true", help="live mode without mic/speaker")
    parser.add_argument("--no-hotkey", action="store_true", help="disable the global hotkey")
    args = parser.parse_args()

    if args.latency_report:
        from .latency import distributions, format_report, spans

        if str(args.latency_report) == "latest":
            cfg = load_config(args.config)
            traces = sorted(
                cfg.data_dir.glob("traces/*/*.jsonl"),
                key=lambda p: p.stat().st_mtime,
            )
            if not traces:
                print(f"no traces found under {cfg.data_dir / 'traces'}", file=sys.stderr)
                sys.exit(1)
            trace_path = traces[-1]
            print(f"trace: {trace_path}")
        else:
            trace_path = Path(args.latency_report)
        print(format_report(spans(trace_path), distributions(trace_path)))
        return

    cfg = load_config(args.config)

    if args.doctor:
        from .doctor import format_report, run_doctor

        print(format_report(run_doctor(cfg)))
        return

    if args.eval:
        from .evals import run_evals

        sys.exit(run_evals(cfg))

    if args.intent_eval:
        from .intent_eval import run_intent_eval

        limit = None if str(args.intent_eval) == "all" else int(args.intent_eval)
        sys.exit(run_intent_eval(cfg, limit))

    if args.action_probe:
        from .action_probe import PROBE_TARGETS, run_fixture_probe, run_verified_probe

        repo_root = Path(__file__).resolve().parents[2]
        try:
            if args.action_probe == "fixture-legacy":
                result = run_fixture_probe(repo_root, cfg.data_dir)
                sys.exit(0 if result.false_success_reproduced else 1)
            targets = PROBE_TARGETS if args.action_probe == "all" else (args.action_probe,)
            records = [
                run_verified_probe(repo_root, cfg.data_dir, target)
                for target in targets
            ]
        except RuntimeError as error:
            print(f"action probe blocked: {error}", file=sys.stderr)
            sys.exit(2)
        failed = any(
            record.get("engine_outcome") != "verified"
            or record.get("independent_verdict") not in {"matched", "no_effect"}
            for record in records
            if record.get("probe") != "fixture"
        )
        fixture_failed = any(
            record.get("probe") == "fixture" and not record.get("receipt_agrees", False)
            for record in records
        )
        sys.exit(1 if failed or fixture_failed else 0)

    asyncio.run(_serve(cfg, args))


async def _serve(cfg, args) -> None:
    registry = build_registry()
    session_shots = cfg.data_dir / "screenshots" / new_id("shots")
    ctx = ExecutionContext(cfg=cfg, screenshot_dir=session_shots, ax=None)

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
                import sounddevice as sd

                from .audio import AudioPipe, resolve_input_device

                device, device_warning = resolve_input_device(
                    list(sd.query_devices()), cfg.audio.input_device)
                if device_warning:
                    print(device_warning, file=sys.stderr)
                audio = AudioPipe(on_pcm=lambda pcm: None, on_drain=lambda: None,
                                  preroll_ms=cfg.audio.preroll_ms,
                                  input_device=device,
                                  low_signal_rms=cfg.audio.low_signal_rms)
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
        audio.on_low_signal = lambda peak: app.on_low_signal(peak)
        audio.start(loop)

    hotkey = None
    if not args.no_hotkey and not args.demo:
        from .hotkey import wire_hotkey

        hotkey = wire_hotkey(cfg.hotkeys.ptt, app, loop)

    import os

    from .lifecycle import OwnershipLease

    lease = OwnershipLease.from_environment(os.environ)
    shutdown_event = asyncio.Event()
    app.shutdown_signal = shutdown_event.set
    lease_task = None
    if lease.bound:
        def orphaned() -> None:
            app.trace.log("lifecycle_orphaned", parent_pid=lease.parent_pid,
                          grace_s=lease.grace_s)
            shutdown_event.set()
        lease_task = asyncio.ensure_future(lease.watch(orphaned))

    await app.start()
    mode = "demo" if args.demo else "live"
    hk = f"global PTT on {cfg.hotkeys.ptt}" if hotkey else "console PTT only (hold Space)"
    print(f"conn {mode} session {app.session_id}")
    print(f"console: http://{cfg.server.host}:{cfg.server.port}  ({hk})")
    print(f"budget: ${cfg.budget.session_cap_usd:.2f} cap, warn at ${cfg.budget.warn_at_usd:.2f}")

    from .server.http import serve

    try:
        await serve(app, shutdown_event)
    finally:
        if lease_task is not None:
            lease_task.cancel()
        if hotkey:
            hotkey.stop()
        if audio is not None:
            audio.stop()
        await app.stop()


if __name__ == "__main__":
    main()
