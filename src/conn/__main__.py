"""conn: push-to-talk voice command surface for the Mac.

  python -m conn --demo            scripted model, real tools, no credentials
  python -m conn --demo --simulate-tools   zero side effects at all
  python -m conn                   live gpt-realtime-2.1 session (needs OPENAI_API_KEY)
  python -m conn --doctor          environment and permission checks
  python -m conn --eval            run the demo eval suite, write trace artifacts
  python -m conn --latency-report [trace.jsonl]   latency spans + budget pass/fail (default: newest trace)
  python -m conn --cost-report [trace.jsonl | --days N]   per-command unit economics (default: newest trace)
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


def _cost_report(args) -> int:
    from .cost_report import days_report, session_report

    cfg = load_config(args.config)
    if args.days is not None:
        if args.days < 1:
            print("--days needs a positive number", file=sys.stderr)
            return 2
        print(days_report(cfg.data_dir, args.days, cfg.pricing))
        return 0
    if str(args.cost_report) == "latest":
        traces = sorted(cfg.data_dir.glob("traces/*/*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not traces:
            print(f"no traces found under {cfg.data_dir / 'traces'}", file=sys.stderr)
            return 1
        trace_path = traces[-1]
    else:
        trace_path = Path(args.cost_report)
        if not trace_path.exists():
            print(f"no such trace: {trace_path}", file=sys.stderr)
            return 1
    print(session_report(trace_path, cfg.pricing))
    return 0


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
    parser.add_argument("--cost-report", nargs="?", const="latest", default=None, metavar="TRACE_JSONL", help="print per-command cost, category shares and cache hit rate for a trace file (no argument: newest trace); with --days, a per-day rollup")
    parser.add_argument("--days", type=int, default=None, metavar="N", help="with --cost-report: roll up the last N days of traces")
    parser.add_argument("--mcp-login", metavar="NAME", help="sign in to a remote MCP server in the browser and exit")
    parser.add_argument("--mcp-logout", metavar="NAME", help="forget the stored sign-in for an MCP server and exit")
    parser.add_argument("--mcp-tools", action="store_true", help="connect to configured MCP servers, print their exposed tools and exit")
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

    if args.cost_report or args.days:
        sys.exit(_cost_report(args))

    cfg = load_config(args.config)

    if args.doctor:
        from .doctor import format_report, run_doctor

        print(format_report(run_doctor(cfg)))
        return

    if args.mcp_login or args.mcp_logout:
        sys.exit(_mcp_sign_in(cfg, args))
    if args.mcp_tools:
        sys.exit(asyncio.run(_mcp_tools(cfg)))

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


def _should_start_mcp(cfg, args) -> bool:
    return bool(not args.demo and cfg.mcp.enabled and cfg.mcp.servers)


def _mcp_sign_in(cfg, args) -> int:
    from .mcp_auth import McpLoginFailed, login, logout

    name = args.mcp_login or args.mcp_logout
    server = next((s for s in cfg.mcp.servers if s.name == name), None)
    if server is None or server.auth != "oauth":
        print(f"{name}: not a configured OAuth MCP server", file=sys.stderr)
        return 2
    if args.mcp_logout:
        logout(name)
        print(f"{name} signed out")
        return 0
    try:
        names = asyncio.run(login(server))
    except McpLoginFailed as error:
        print(f"{name} sign-in failed: {error}")
        return 1
    except BaseException as error:  # noqa: BLE001 - OAuth errors can carry server text; print the type only
        if isinstance(error, KeyboardInterrupt):
            raise
        print(f"{name} sign-in failed: {type(error).__name__}")
        return 1
    print(f"{name} signed in: {len(names)} tools offered ({', '.join(names)})")
    return 0


async def _mcp_tools(cfg) -> int:
    import json

    from .mcp_auth import daemon_auth
    from .mcp_client import McpManager

    if not cfg.mcp.servers:
        print("no MCP servers configured")
        return 0
    manager = McpManager(cfg.mcp, data_dir=cfg.data_dir, auth_for=daemon_auth)
    try:
        infos = await manager.start()
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    try:
        for server in cfg.mcp.servers:
            print(f"{server.name}: {manager.status.get(server.name, 'unknown')}")
            for info in (i for i in infos if i.server == server.name):
                kind = server.tools[info.tool].kind
                schema = json.dumps(info.input_schema, separators=(",", ":"))
                print(f"  {info.server}.{info.tool} kind={kind} read_only={info.read_only_hint} "
                      f"destructive={info.destructive_hint} schema={schema}")
    finally:
        await manager.stop()
    return 0


async def _serve(cfg, args) -> None:
    registry = build_registry()
    session_shots = cfg.data_dir / "screenshots" / new_id("shots")
    ctx = ExecutionContext(cfg=cfg, screenshot_dir=session_shots, ax=None)

    mcp_manager = None
    if _should_start_mcp(cfg, args):
        from .mcp_auth import daemon_auth
        from .mcp_client import McpManager

        mcp_manager = McpManager(cfg.mcp, data_dir=cfg.data_dir, auth_for=daemon_auth)
        try:
            infos = await mcp_manager.start()
            # A server that is down keeps its cached tools, so a call says
            # "unavailable" instead of the tool vanishing.
            for server in cfg.mcp.servers:
                if mcp_manager.status.get(server.name, "").startswith("skipped:"):
                    infos += [i for i in mcp_manager.cached_infos(server.name)
                              if i.tool in server.tools]
            from .tools.mcp_bridge import register_mcp_tools

            for name, reason in register_mcp_tools(registry, infos, cfg, mcp_manager):
                print(f"mcp tool refused: {name}: {reason}", file=sys.stderr)
        except ValueError as error:
            await mcp_manager.stop()
            print(str(error), file=sys.stderr)
            sys.exit(2)
        ctx.mcp = mcp_manager

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
        from .prompt import instructions_for
        from .realtime.openai_ws import OpenAIRealtimeAdapter

        executors = None
        tools = export_openai(registry)
        adapter = OpenAIRealtimeAdapter(cfg, tools, instructions_for(tools))
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
    if mcp_manager is not None:
        # app.trace is replaced on a session reset, so look it up each time.
        ctx.trace = lambda event, **fields: app.trace.log(event, **fields)
        for event, fields in mcp_manager.drain_events():
            app.trace.log(event, **fields)

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
        if mcp_manager is not None:
            await mcp_manager.stop()


if __name__ == "__main__":
    main()
