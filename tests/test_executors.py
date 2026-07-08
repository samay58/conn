"""Executor tests with subprocess mocked: assert the exact argv each tool runs,
so a refactor can never quietly widen what conn touches on the machine.
"""

import json
from unittest.mock import patch

import pytest

from conn.events import Gate
from conn.tools import mac, phoenix
from conn.tools.base import ToolError


def ok_proc(stdout=b"", returncode=0):
    class P:
        pass
    p = P()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = b""
    return p


class TestArgv:
    def test_open_app_argv(self, ctx):
        with patch("conn.tools.mac.subprocess.run", return_value=ok_proc()) as run:
            mac.open_app({"app": "Obsidian"}, ctx)
        assert run.call_args.args[0] == ["/usr/bin/open", "-a", "Obsidian"]

    def test_browser_search_urlencodes(self, ctx):
        with patch("conn.tools.mac.subprocess.run", return_value=ok_proc()) as run:
            mac.browser_search({"query": "openai realtime docs"}, ctx)
        argv = run.call_args.args[0]
        assert argv[0] == "/usr/bin/open"
        assert argv[1] == "https://www.google.com/search?q=openai+realtime+docs"

    def test_clipboard_pipes_to_pbcopy(self, ctx):
        with patch("conn.tools.mac.subprocess.run", return_value=ok_proc()) as run:
            out = mac.clipboard_set({"text": "hello"}, ctx)
        assert run.call_args.args[0] == ["/usr/bin/pbcopy"]
        assert run.call_args.kwargs["input"] == b"hello"
        assert out == {"chars": 5}

    def test_screenshot_argv_and_failure(self, ctx):
        with patch("conn.tools.mac.subprocess.run", return_value=ok_proc(returncode=1)):
            with pytest.raises(ToolError, match="screencapture failed"):
                mac.screenshot({}, ctx)

    def test_open_app_failure_raises(self, ctx):
        with patch("conn.tools.mac.subprocess.run", return_value=ok_proc(returncode=1)):
            with pytest.raises(ToolError, match="could not open"):
                mac.open_app({"app": "Ghost"}, ctx)


class TestPhoenixExecutors:
    def test_qmd_search_argv_cwd_and_env(self, ctx):
        with patch("conn.tools.phoenix.shutil.which", return_value="/fake/bin/qmd"), \
             patch("conn.tools.phoenix.subprocess.run",
                   return_value=ok_proc(stdout="")) as run:
            run.return_value.stdout = ""
            phoenix.phoenix_search({"query": "transformer paper"}, ctx)
        argv = run.call_args.args[0]
        assert argv == ["/fake/bin/qmd", "search", "transformer paper"]
        assert run.call_args.kwargs["cwd"] == ctx.cfg.phoenix.vault_root
        # qmd's launcher script needs `node` beside it even when the daemon
        # was spawned by the app with a minimal PATH.
        assert run.call_args.kwargs["env"]["PATH"].startswith("/fake/bin")

    def test_qmd_missing_raises_clear_error(self, ctx, tmp_path):
        with patch("conn.tools.phoenix.shutil.which", return_value=None), \
             patch("conn.tools.phoenix.Path.home", return_value=tmp_path), \
             patch("conn.tools.phoenix.Path.exists", return_value=False):
            with pytest.raises(ToolError, match="qmd_not_found"):
                phoenix.phoenix_search({"query": "x"}, ctx)

    def test_open_note_builds_obsidian_url(self, ctx, tmp_path):
        note = tmp_path / "vault" / "01-active" / "tasks.md"
        note.parent.mkdir(parents=True)
        note.write_text("# tasks")
        with patch("conn.tools.phoenix.subprocess.run", return_value=ok_proc()) as run:
            out = phoenix.open_note({"path": "01-active/tasks.md"}, ctx)
        argv = run.call_args.args[0]
        assert argv[0] == "/usr/bin/open"
        assert argv[1] == "obsidian://open?vault=phoenix&file=01-active/tasks"
        assert out["path"] == "01-active/tasks.md"

    def test_open_note_adds_md_extension(self, ctx, tmp_path):
        note = tmp_path / "vault" / "note.md"
        note.write_text("x")
        with patch("conn.tools.phoenix.subprocess.run", return_value=ok_proc()):
            out = phoenix.open_note({"path": "note"}, ctx)
        assert out["path"] == "note.md"

    def test_open_missing_note_suggests_search(self, ctx):
        with pytest.raises(ToolError, match="note_not_found"):
            phoenix.open_note({"path": "does/not/exist.md"}, ctx)


GOLDEN_QMD = """qmd://phoenix/04-knowledge-base/reading-notes/transformer-paper-2017.md:1 #ac709a
Title: Attention Is All You Need - reading notes
Context: Phoenix is Samay's markdown knowledge vault. Boilerplate dropped.
Score: 0.89
@@ -1,3 @@ (0 before, 35 after)
# Attention Is All You Need - reading notes

Source: Gmail live read on 2026-06-22.

qmd://phoenix/01-active/tasks.md:480 #71701e
Title: Tasks
Score: 0.71
@@ -480,4 @@ (2 before, 16 after)
### Agent Tinkering - Learning by Osmosis + GPT Realtime 2
"""


class TestQmdParser:
    def test_golden_parse(self):
        results = phoenix.parse_qmd_output(GOLDEN_QMD)
        assert len(results) == 2
        first, second = results
        assert first["path"].endswith("transformer-paper-2017.md")
        assert first["line"] == 1
        assert first["docid"] == "ac709a"
        assert first["score"] == 0.89
        assert first["title"].startswith("Attention")
        assert "Context:" not in first["snippet"]
        assert "@@" not in first["snippet"]
        assert "Gmail live read" in first["snippet"]
        assert second["path"] == "01-active/tasks.md"
        assert second["line"] == 480

    def test_empty_output(self):
        assert phoenix.parse_qmd_output("") == []


class TestHarnessRun:
    def test_run_wraps_success_envelope(self, harness):
        import asyncio
        call = harness.gate("c1", "wait_for_user", "{}")
        result = asyncio.run(harness.run(call))
        env = json.loads(result.output)
        assert result.ok and env["ok"] is True
        assert env["data"] == {"standing_by": True}
        assert "duration_ms" in env

    def test_run_wraps_tool_error(self, harness):
        import asyncio

        def boom(args, ctx):
            raise ToolError("could not open 'Ghost'")
        harness._executors = {"app_open": boom}
        call = harness.gate("c1", "app_open", '{"app": "Obsidian"}')
        assert call.gate is Gate.AUTO
        result = asyncio.run(harness.run(call))
        env = json.loads(result.output)
        assert result.ok is False and env["ok"] is False
        assert "Ghost" in env["error"]

    def test_run_times_out(self, harness):
        import asyncio
        import time as _time

        def sleepy(args, ctx):
            _time.sleep(0.2)
            return {}
        harness._executors = {"wait_for_user": sleepy}
        import dataclasses
        fast_spec = dataclasses.replace(harness.registry["wait_for_user"], timeout_s=0.05)
        harness.registry["wait_for_user"] = fast_spec
        call = harness.gate("c1", "wait_for_user", "{}")
        result = asyncio.run(harness.run(call))
        env = json.loads(result.output)
        assert env["ok"] is False and "timeout" in env["error"]


class TestPromptAndEvalSuite:
    def test_tools_section_spells_out_grounded_protocol(self):
        from conn import prompt

        lines = prompt.INSTRUCTIONS.splitlines()
        start = lines.index('# Tools') + 1
        end = lines.index('# Completion discipline')
        section = lines[start:end]
        joined = '\n'.join(section)

        assert len(section) < 30
        assert 'stale_ref' in joined
        assert 'element_not_visible' in joined
        assert 'app_focus_tab' in joined
        assert 'app_menu' in joined
        assert 'never guess refs' in joined.lower()
        assert 'snapshots on demand only' in joined.lower()
        assert 'computer_ax_tree' not in joined
        assert 'disabled and will be refused' not in joined

    def test_owned_eval_cases_extend_the_legacy_suite(self):
        from conn import evals

        ids = [case['id'] for case in evals.load_eval_cases()]

        assert len(ids) == 13
        assert ids[:8] == [
            'open-app',
            'vault-search-then-open',
            'context-read',
            'clipboard-needs-approval-approve',
            'clipboard-needs-approval-deny',
            'blocked-ui-click-refused',
            'switch-then-menu',
            'latency-v2-kinds-present',
        ]
        assert ids[8:] == [
            'stale-ref-round-trip',
            'secure-field-refusal',
            'hotkey-not-allowlisted',
            'focus-tab-ambiguity',
            'app-menu-no-match',
        ]


    def test_run_case_passes_secure_field_refusal(self, cfg, tmp_path):
        import asyncio
        from conn import evals

        cfg.data_dir = tmp_path / "data"
        case = next(case for case in evals.load_eval_cases() if case["id"] == "secure-field-refusal")

        result = asyncio.run(evals._run_case(case, cfg))

        assert result["passed"], result["failures"]
        assert result["tools"] == ["computer_ax_snapshot", "computer_type_text"]

    def test_run_case_records_tool_payloads_for_candidate_style_results(self, cfg, tmp_path):
        import asyncio
        from conn import evals

        cfg.data_dir = tmp_path / "data"
        case = next(case for case in evals.load_eval_cases() if case["id"] == "focus-tab-ambiguity")

        result = asyncio.run(evals._run_case(case, cfg))

        assert result["passed"], result["failures"]
        assert result["tool_data"]["app_focus_tab"][0]["candidates"] == ["Alpha", "Alphas"]
