from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

import pytest

from conn.lab.runner import (
    CommandResult,
    CommandTimedOut,
    LabRunner,
    LabRunnerConfig,
    LabRunnerError,
    SubprocessExecutor,
    TartClient,
    wait_for_vnc_endpoint,
)


@dataclass
class FakeProcess:
    running: bool = True
    terminated: bool = False
    killed: bool = False
    output_lines: tuple[str, ...] = ()

    def poll(self) -> int | None:
        return None if self.running else 0

    def wait(self, timeout: float | None = None) -> int:
        self.running = False
        return 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def read_line(self, timeout_s: float) -> str | None:
        if not self.output_lines:
            return None
        line, *remaining = self.output_lines
        self.output_lines = tuple(remaining)
        return line


class FakeExecutor:
    def __init__(
        self,
        *,
        marker_present: bool = True,
        marker_errors: list[BaseException] | None = None,
        guest_error=None,
    ):
        self.marker_present = marker_present
        self.marker_errors = list(marker_errors or [])
        self.guest_error = guest_error
        self.run_calls: list[tuple[str, ...]] = []
        self.input_calls: list[tuple[tuple[str, ...], str]] = []
        self.start_calls: list[tuple[str, ...]] = []
        self.start_input_calls: list[tuple[tuple[str, ...], str]] = []
        self.process = FakeProcess()

    def run(self, argv, *, timeout_s: float) -> CommandResult:
        args = tuple(str(item) for item in argv)
        self.run_calls.append(args)
        if args[-3:] == ("test", "-f", "/Users/admin/.conn-lab-guest"):
            if self.marker_errors:
                raise self.marker_errors.pop(0)
            return CommandResult(args, 0 if self.marker_present else 1, "", "")
        if "CONN_SERVER_PORT=18787" in args and self.guest_error is not None:
            raise self.guest_error
        return CommandResult(args, 0, "guest-ok\n", "")

    def start(self, argv) -> FakeProcess:
        args = tuple(str(item) for item in argv)
        self.start_calls.append(args)
        return self.process

    def start_captured(self, argv) -> FakeProcess:
        return self.start(argv)

    def run_input(
        self, argv, input_text: str, *, timeout_s: float
    ) -> CommandResult:
        args = tuple(str(item) for item in argv)
        self.input_calls.append((args, input_text))
        return CommandResult(args, 0, "guest-ok\n", "")

    def start_captured_input(self, argv, input_text: str) -> FakeProcess:
        args = tuple(str(item) for item in argv)
        self.start_input_calls.append((args, input_text))
        return self.process


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def sleep(self, duration: float) -> None:
        self.value += duration


def config(tmp_path: Path, **changes) -> LabRunnerConfig:
    repo = tmp_path / "repo"
    artifacts = repo / "data" / "lab-runs"
    artifacts.mkdir(parents=True)
    values = {
        "repo_root": repo,
        "artifact_root": artifacts,
        "boot_timeout_s": 0.1,
        "command_timeout_s": 2,
        "cleanup_timeout_s": 1,
    }
    values.update(changes)
    return LabRunnerConfig(**values)


def test_runner_refuses_host_port_and_paths_outside_lab_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="18787"):
        config(tmp_path, guest_port=8787)

    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="artifact_root"):
        LabRunnerConfig(repo_root=repo, artifact_root=tmp_path / "elsewhere")


def test_missing_guest_marker_cleans_only_disposable_clone(tmp_path: Path) -> None:
    fake = FakeExecutor(marker_present=False)
    clock = FakeClock()
    runner = LabRunner(
        config(tmp_path),
        executor=fake,
        clock=clock,
        sleeper=clock.sleep,
    )

    with pytest.raises(LabRunnerError, match="guest_marker_missing"):
        runner.run_command("run-missing-marker", ["/usr/bin/true"])

    flattened = [" ".join(call) for call in fake.run_calls + fake.start_calls]
    assert any("tart stop conn-lab-run-missing-marker" in call for call in flattened)
    assert any("tart delete conn-lab-run-missing-marker" in call for call in flattened)
    assert not any("stop conn-lab-golden" in call for call in flattened)
    assert not any("delete conn-lab-golden" in call for call in flattened)
    assert not any("8787" in call for call in flattened)
    assert not any("/Applications/Conn.app" in call for call in flattened)


def test_success_uses_two_allowed_mounts_and_guest_port(tmp_path: Path) -> None:
    fake = FakeExecutor()
    clock = FakeClock()
    runner = LabRunner(
        config(tmp_path),
        executor=fake,
        clock=clock,
        sleeper=clock.sleep,
    )

    result = runner.run_command("run-success", ["/usr/bin/printf", "ok"])

    assert result.returncode == 0
    assert result.stdout == "guest-ok\n"
    assert len(fake.start_calls) == 1
    start = fake.start_calls[0]
    mounts = [argument for argument in start if argument.startswith("--dir=")]
    assert len(mounts) == 2
    assert any(argument.startswith("--dir=repo:") and argument.endswith(":ro")
               for argument in mounts)
    assert any(argument.startswith("--dir=artifacts:") and not argument.endswith(":ro")
               for argument in mounts)
    guest_calls = [
        call for call in fake.run_calls if "CONN_SERVER_PORT=18787" in call
    ]
    assert guest_calls == [(
        "tart", "exec", "conn-lab-run-success", "env",
        "CONN_SERVER_PORT=18787", "/usr/bin/printf", "ok",
    )]
    assert any(call[:3] == ("tart", "get", "conn-lab-run-success")
               for call in fake.run_calls)


def test_boot_exec_timeout_is_retried_until_guest_marker_appears(
    tmp_path: Path,
) -> None:
    fake = FakeExecutor(
        marker_errors=[CommandTimedOut(("tart", "exec"), 5)]
    )
    clock = FakeClock()
    runner = LabRunner(
        config(tmp_path),
        executor=fake,
        clock=clock,
        sleeper=clock.sleep,
    )

    result = runner.run_command("run-slow-boot", ["/usr/bin/true"])

    assert result.returncode == 0
    marker_calls = [
        call for call in fake.run_calls
        if call[-3:] == ("test", "-f", "/Users/admin/.conn-lab-guest")
    ]
    assert len(marker_calls) == 2


@pytest.mark.parametrize(
    "guest_error",
    [
        CommandTimedOut(("tart", "exec"), 2),
        KeyboardInterrupt(),
    ],
)
def test_guest_failure_still_stops_and_deletes_clone(
    tmp_path: Path, guest_error: BaseException
) -> None:
    fake = FakeExecutor(guest_error=guest_error)
    clock = FakeClock()
    runner = LabRunner(
        config(tmp_path),
        executor=fake,
        clock=clock,
        sleeper=clock.sleep,
    )

    with pytest.raises(type(guest_error)):
        runner.run_command("run-failure", ["/usr/bin/false"])

    assert ("tart", "stop", "conn-lab-run-failure") in fake.run_calls
    assert ("tart", "delete", "conn-lab-run-failure") in fake.run_calls


def test_subprocess_timeout_is_bounded() -> None:
    executor = SubprocessExecutor(termination_grace_s=0.1)
    started = time.monotonic()

    with pytest.raises(CommandTimedOut):
        executor.run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout_s=0.05,
        )

    assert time.monotonic() - started < 1


def test_vnc_guest_uses_isolated_mounts_without_host_window(tmp_path: Path) -> None:
    fake = FakeExecutor()
    client = TartClient(config(tmp_path), fake)
    artifact_dir = client.config.artifact_root / "2026-07-16" / "vnc"
    artifact_dir.mkdir(parents=True)

    client.start_vnc("conn-lab-vnc", artifact_dir)

    start = fake.start_calls[-1]
    assert "--vnc-experimental" in start
    assert "--no-graphics" in start
    assert "--net-softnet" not in start
    assert "--no-audio" in start
    assert "--no-clipboard" in start
    assert len([item for item in start if item.startswith("--dir=")]) == 2


def test_softnet_is_explicit_opt_in(tmp_path: Path) -> None:
    fake = FakeExecutor()
    client = TartClient(config(tmp_path, use_softnet=True), fake)
    artifact_dir = client.config.artifact_root / "2026-07-16" / "softnet"
    artifact_dir.mkdir(parents=True)

    client.start_vnc("conn-lab-softnet", artifact_dir)

    assert "--net-softnet" in fake.start_calls[-1]


def test_vnc_endpoint_waits_for_tart_loopback_url() -> None:
    process = FakeProcess(output_lines=(
        "booting\n",
        "Opening vnc://:upon-siege-habit-time@127.0.0.1:57622...\n",
    ))

    assert wait_for_vnc_endpoint(process, timeout_s=1) == (
        "upon-siege-habit-time",
        57622,
    )


def test_vnc_session_is_ready_and_always_cleaned_up(tmp_path: Path) -> None:
    fake = FakeExecutor()
    fake.process.output_lines = (
        "Opening vnc://:upon-siege-habit-time@127.0.0.1:57622...\n",
    )
    runner = LabRunner(config(tmp_path), executor=fake)

    with runner.vnc_session("vnc-session") as session:
        assert session.vm_name == "conn-lab-vnc-session"
        assert session.vnc_endpoint == ("upon-siege-habit-time", 57622)

    assert ("tart", "stop", "conn-lab-vnc-session") in fake.run_calls
    assert ("tart", "delete", "conn-lab-vnc-session") in fake.run_calls


def test_vnc_session_records_lifecycle_timings_after_cleanup(
    tmp_path: Path,
) -> None:
    fake = FakeExecutor()
    fake.process.output_lines = (
        "Opening vnc://:upon-siege-habit-time@127.0.0.1:57622...\n",
    )
    runner = LabRunner(config(tmp_path), executor=fake)

    with runner.vnc_session("timed-session") as session:
        artifact_dir = session.artifact_dir

    timings = json.loads((artifact_dir / "runner-timings.json").read_text())
    assert set(timings) == {
        "boot_ms",
        "cleanup_ms",
        "clone_ms",
        "total_ms",
    }
    assert all(
        isinstance(value, int) and value >= 0
        for value in timings.values()
    )


@pytest.mark.parametrize("failed_process", ["Conn", "ConnActionFixture"])
def test_guest_process_failure_still_cleans_the_disposable_vm(
    tmp_path: Path, failed_process: str
) -> None:
    fake = FakeExecutor()
    fake.process.output_lines = (
        "Opening vnc://:upon-siege-habit-time@127.0.0.1:57622...\n",
    )
    runner = LabRunner(config(tmp_path), executor=fake)

    with pytest.raises(LabRunnerError, match=f"{failed_process}_exited"):
        with runner.vnc_session("crash-cleanup"):
            raise LabRunnerError(f"{failed_process}_exited")

    assert ("tart", "stop", "conn-lab-crash-cleanup") in fake.run_calls
    assert ("tart", "delete", "conn-lab-crash-cleanup") in fake.run_calls
    assert ("tart", "stop", "conn-lab-golden") not in fake.run_calls
    assert ("tart", "delete", "conn-lab-golden") not in fake.run_calls


def test_private_guest_commands_keep_secrets_out_of_host_arguments(
    tmp_path: Path,
) -> None:
    fake = FakeExecutor()
    client = TartClient(config(tmp_path), fake)

    result = client.execute_private(
        "conn-lab-worker",
        ["/bin/launchctl", "setenv", "CONN_BRIDGE_TOKEN", "secret-token"],
    )
    worker = client.start_private_execute(
        "conn-lab-worker",
        ["/usr/bin/true"],
        environment={
            "CONN_DATA_DIR": "/Volumes/My Shared Files/artifacts/data",
            "OPENAI_API_KEY": "secret-key",
        },
    )

    assert result.returncode == 0
    assert worker is fake.process
    calls = fake.input_calls + fake.start_input_calls
    assert len(calls) == 2
    for argv, payload in calls:
        joined = "\0".join(argv)
        assert argv[:5] == (
            "tart",
            "exec",
            "-i",
            "conn-lab-worker",
            "env",
        )
        assert "CONN_SERVER_PORT=18787" in argv
        assert "secret-token" not in joined
        assert "secret-key" not in joined
        assert "CONN_SERVER_PORT=8787" not in joined
        assert json.loads(payload)["schema_version"] == 1
    assert "secret-token" in fake.input_calls[0][1]
    assert "secret-key" in fake.start_input_calls[0][1]
