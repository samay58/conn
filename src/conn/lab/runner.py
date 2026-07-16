from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import time
from typing import Callable, Protocol, Sequence

from .private_exec import encode_request
from .vnc import parse_tart_vnc


GUEST_MARKER = "/Users/admin/.conn-lab-guest"
GUEST_DAEMON_PORT = 18787
GUEST_REPO = "/Volumes/My Shared Files/repo"
GUEST_PYTHON = f"{GUEST_REPO}/.venv/bin/python"
_VM_NAME = re.compile(r"^conn-lab-[a-z0-9]+(?:-[a-z0-9]+)*$")
_RUN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ENVIRONMENT_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class LabRunnerError(RuntimeError):
    pass


class CommandTimedOut(LabRunnerError):
    def __init__(self, argv: Sequence[str], timeout_s: float):
        self.argv = tuple(argv)
        self.timeout_s = timeout_s
        super().__init__(f"command_timeout:{timeout_s:g}s")


@dataclass(frozen=True, slots=True)
class CommandResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ManagedProcess(Protocol):
    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


class CapturedProcess(ManagedProcess, Protocol):
    def read_line(self, timeout_s: float) -> str | None: ...


class CommandExecutor(Protocol):
    def run(
        self, argv: Sequence[str], *, timeout_s: float
    ) -> CommandResult: ...

    def start(self, argv: Sequence[str]) -> ManagedProcess: ...

    def start_captured(self, argv: Sequence[str]) -> CapturedProcess: ...

    def run_input(
        self, argv: Sequence[str], input_text: str, *, timeout_s: float
    ) -> CommandResult: ...

    def start_captured_input(
        self, argv: Sequence[str], input_text: str
    ) -> CapturedProcess: ...


class CapturedSubprocess:
    def __init__(self, process: subprocess.Popen):
        self.process = process

    def poll(self) -> int | None:
        return self.process.poll()

    def wait(self, timeout: float | None = None) -> int:
        return self.process.wait(timeout=timeout)

    def terminate(self) -> None:
        self.process.terminate()

    def kill(self) -> None:
        self.process.kill()

    def read_line(self, timeout_s: float) -> str | None:
        stdout = self.process.stdout
        if stdout is None:
            raise LabRunnerError("captured_process_has_no_output")
        ready, _, _ = select.select([stdout], [], [], timeout_s)
        if not ready:
            return None
        line = stdout.readline()
        return line if line else None


class SubprocessExecutor:
    def __init__(
        self,
        *,
        termination_grace_s: float = 2,
        environment: dict[str, str] | None = None,
    ):
        if not 0 < termination_grace_s <= 10:
            raise ValueError("termination_grace_s must be in (0, 10]")
        self.termination_grace_s = termination_grace_s
        self.environment = dict(environment or {})

    def run(
        self, argv: Sequence[str], *, timeout_s: float
    ) -> CommandResult:
        args = _command(argv)
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=self._environment(),
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired as error:
            self._stop(process)
            raise CommandTimedOut(args, timeout_s) from error
        except BaseException:
            self._stop(process)
            raise
        return CommandResult(args, process.returncode, stdout, stderr)

    def start(self, argv: Sequence[str]) -> ManagedProcess:
        args = _command(argv)
        return subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=self._environment(),
        )

    def start_captured(self, argv: Sequence[str]) -> CapturedProcess:
        args = _command(argv)
        process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=self._environment(),
        )
        return CapturedSubprocess(process)

    def run_input(
        self, argv: Sequence[str], input_text: str, *, timeout_s: float
    ) -> CommandResult:
        args = _command(argv)
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=self._environment(),
        )
        try:
            stdout, stderr = process.communicate(
                input=input_text,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired as error:
            self._stop(process)
            raise CommandTimedOut(args, timeout_s) from error
        except BaseException:
            self._stop(process)
            raise
        return CommandResult(args, process.returncode, stdout, stderr)

    def start_captured_input(
        self, argv: Sequence[str], input_text: str
    ) -> CapturedProcess:
        args = _command(argv)
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            env=self._environment(),
        )
        try:
            if process.stdin is None:
                raise LabRunnerError("captured_process_has_no_input")
            process.stdin.write(input_text)
            process.stdin.close()
        except BaseException:
            self._stop(process)
            raise
        return CapturedSubprocess(process)

    def _environment(self) -> dict[str, str]:
        return os.environ | self.environment

    def _stop(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=self.termination_grace_s)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            process.wait(timeout=self.termination_grace_s)


@dataclass(frozen=True, slots=True)
class LabRunnerConfig:
    repo_root: Path
    artifact_root: Path
    tart_binary: str = "tart"
    golden_vm: str = "conn-lab-golden"
    guest_port: int = GUEST_DAEMON_PORT
    boot_timeout_s: float = 120
    command_timeout_s: float = 180
    cleanup_timeout_s: float = 10
    readiness_poll_s: float = 0.5
    use_softnet: bool = False

    def __post_init__(self) -> None:
        repo = Path(self.repo_root).expanduser().resolve(strict=True)
        artifacts = Path(self.artifact_root).expanduser().resolve(strict=False)
        allowed_artifacts = (repo / "data" / "lab-runs").resolve(strict=False)
        if artifacts != allowed_artifacts and allowed_artifacts not in artifacts.parents:
            raise ValueError("artifact_root must be under repo/data/lab-runs")
        if self.guest_port != GUEST_DAEMON_PORT:
            raise ValueError(f"guest_port must be {GUEST_DAEMON_PORT}")
        if not _VM_NAME.fullmatch(self.golden_vm):
            raise ValueError("golden_vm must be a conn-lab VM name")
        if not self.tart_binary or "\x00" in self.tart_binary:
            raise ValueError("tart_binary is invalid")
        for name, value, ceiling in (
            ("boot_timeout_s", self.boot_timeout_s, 300),
            ("command_timeout_s", self.command_timeout_s, 900),
            ("cleanup_timeout_s", self.cleanup_timeout_s, 30),
            ("readiness_poll_s", self.readiness_poll_s, 5),
        ):
            if not 0 < value <= ceiling:
                raise ValueError(f"{name} must be in (0, {ceiling}]")
        object.__setattr__(self, "repo_root", repo)
        object.__setattr__(self, "artifact_root", artifacts)


class TartClient:
    def __init__(self, config: LabRunnerConfig, executor: CommandExecutor):
        self.config = config
        self.executor = executor

    def clone(self, vm_name: str) -> CommandResult:
        self._disposable(vm_name)
        return self._required([
            self.config.tart_binary,
            "clone",
            self.config.golden_vm,
            vm_name,
        ], timeout_s=self.config.command_timeout_s)

    def start(self, vm_name: str, artifact_dir: Path) -> ManagedProcess:
        self._disposable(vm_name)
        return self.executor.start([
            self.config.tart_binary,
            "run",
            "--no-graphics",
            *self._network_arguments(),
            "--no-audio",
            "--no-clipboard",
            *self._mount_arguments(artifact_dir),
            vm_name,
        ])

    def start_vnc(
        self, vm_name: str, artifact_dir: Path
    ) -> CapturedProcess:
        self._disposable(vm_name)
        return self.executor.start_captured([
            self.config.tart_binary,
            "run",
            "--no-graphics",
            "--vnc-experimental",
            *self._network_arguments(),
            "--no-audio",
            "--no-clipboard",
            *self._mount_arguments(artifact_dir),
            vm_name,
        ])

    def _network_arguments(self) -> list[str]:
        return ["--net-softnet"] if self.config.use_softnet else []

    def _mount_arguments(self, artifact_dir: Path) -> list[str]:
        artifact_dir = artifact_dir.resolve(strict=True)
        if (
            artifact_dir != self.config.artifact_root
            and self.config.artifact_root not in artifact_dir.parents
        ):
            raise LabRunnerError("unsafe_artifact_mount")
        mount_values = [
            ("repo", self.config.repo_root, True),
            ("artifacts", artifact_dir, False),
        ]
        mount_args: list[str] = []
        for name, path, read_only in mount_values:
            text = str(path)
            if ":" in text or "\x00" in text:
                raise LabRunnerError("unsafe_mount_path")
            suffix = ":ro" if read_only else ""
            mount_args.append(f"--dir={name}:{text}{suffix}")
        return mount_args

    def inspect(self, vm_name: str) -> CommandResult:
        self._disposable(vm_name)
        return self._required([
            self.config.tart_binary,
            "get",
            vm_name,
            "--format",
            "json",
        ], timeout_s=10)

    def marker(self, vm_name: str) -> CommandResult:
        self._disposable(vm_name)
        return self.executor.run([
            self.config.tart_binary,
            "exec",
            vm_name,
            "test",
            "-f",
            GUEST_MARKER,
        ], timeout_s=5)

    def execute(
        self, vm_name: str, command: Sequence[str]
    ) -> CommandResult:
        self._disposable(vm_name)
        guest_command = _command(command)
        return self._required([
            self.config.tart_binary,
            "exec",
            vm_name,
            "env",
            f"CONN_SERVER_PORT={self.config.guest_port}",
            *guest_command,
        ], timeout_s=self.config.command_timeout_s)

    def execute_optional(
        self, vm_name: str, command: Sequence[str]
    ) -> CommandResult:
        self._disposable(vm_name)
        guest_command = _command(command)
        return self.executor.run([
            self.config.tart_binary,
            "exec",
            vm_name,
            "env",
            f"CONN_SERVER_PORT={self.config.guest_port}",
            *guest_command,
        ], timeout_s=self.config.command_timeout_s)

    def start_execute(
        self,
        vm_name: str,
        command: Sequence[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> CapturedProcess:
        self._disposable(vm_name)
        guest_command = _command(command)
        values = dict(environment or {})
        if len(values) > 16 or "CONN_SERVER_PORT" in values:
            raise ValueError("guest environment is invalid")
        environment_args = []
        for key, value in sorted(values.items()):
            if (
                not _ENVIRONMENT_KEY.fullmatch(key)
                or not value
                or len(value) > 4_096
                or "\x00" in value
            ):
                raise ValueError("guest environment is invalid")
            environment_args.append(f"{key}={value}")
        return self.executor.start_captured([
            self.config.tart_binary,
            "exec",
            vm_name,
            "env",
            f"CONN_SERVER_PORT={self.config.guest_port}",
            *environment_args,
            *guest_command,
        ])

    def execute_private(
        self,
        vm_name: str,
        command: Sequence[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> CommandResult:
        self._disposable(vm_name)
        payload = encode_request(command, environment=environment)
        result = self.executor.run_input(
            self._private_helper(vm_name),
            payload,
            timeout_s=self.config.command_timeout_s,
        )
        if result.returncode != 0:
            reason = result.stderr.strip()[:160] or f"exit_{result.returncode}"
            raise LabRunnerError(f"tart_command_failed:{reason}")
        return result

    def start_private_execute(
        self,
        vm_name: str,
        command: Sequence[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> CapturedProcess:
        self._disposable(vm_name)
        payload = encode_request(command, environment=environment)
        return self.executor.start_captured_input(
            self._private_helper(vm_name),
            payload,
        )

    def _private_helper(self, vm_name: str) -> tuple[str, ...]:
        return (
            self.config.tart_binary,
            "exec",
            "-i",
            vm_name,
            "env",
            f"CONN_SERVER_PORT={self.config.guest_port}",
            f"PYTHONPATH={GUEST_REPO}/src",
            GUEST_PYTHON,
            "-m",
            "conn.lab.private_exec",
        )

    def stop(self, vm_name: str) -> CommandResult:
        self._disposable(vm_name)
        return self.executor.run([
            self.config.tart_binary,
            "stop",
            vm_name,
        ], timeout_s=self.config.cleanup_timeout_s)

    def delete(self, vm_name: str) -> CommandResult:
        self._disposable(vm_name)
        return self.executor.run([
            self.config.tart_binary,
            "delete",
            vm_name,
        ], timeout_s=self.config.cleanup_timeout_s)

    def _required(
        self, argv: Sequence[str], *, timeout_s: float
    ) -> CommandResult:
        result = self.executor.run(argv, timeout_s=timeout_s)
        if result.returncode != 0:
            reason = result.stderr.strip()[:160] or f"exit_{result.returncode}"
            raise LabRunnerError(f"tart_command_failed:{reason}")
        return result

    def _disposable(self, vm_name: str) -> None:
        if (
            not _VM_NAME.fullmatch(vm_name)
            or vm_name == self.config.golden_vm
        ):
            raise LabRunnerError("unsafe_vm_name")


@dataclass(frozen=True, slots=True)
class VNCGuestSession:
    vm_name: str
    artifact_dir: Path
    vnc_endpoint: tuple[str, int]
    client: TartClient

    def execute(self, command: Sequence[str]) -> CommandResult:
        return self.client.execute(self.vm_name, command)

    def execute_optional(self, command: Sequence[str]) -> CommandResult:
        return self.client.execute_optional(self.vm_name, command)

    def start_execute(
        self,
        command: Sequence[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> CapturedProcess:
        return self.client.start_execute(
            self.vm_name,
            command,
            environment=environment,
        )

    def execute_private(
        self,
        command: Sequence[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> CommandResult:
        return self.client.execute_private(
            self.vm_name,
            command,
            environment=environment,
        )

    def start_private_execute(
        self,
        command: Sequence[str],
        *,
        environment: dict[str, str] | None = None,
    ) -> CapturedProcess:
        return self.client.start_private_execute(
            self.vm_name,
            command,
            environment=environment,
        )


class LabRunner:
    def __init__(
        self,
        config: LabRunnerConfig,
        *,
        executor: CommandExecutor | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.executor = executor or SubprocessExecutor(
            environment={"TART_NO_AUTO_PRUNE": "1"}
        )
        self.client = TartClient(config, self.executor)
        self.clock = clock
        self.sleeper = sleeper

    def run_command(
        self, run_id: str, command: Sequence[str]
    ) -> CommandResult:
        guest_command = _command(command)
        vm_name, artifact_dir = self._session_values(run_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)

        process: ManagedProcess | None = None
        cloned = False
        result: CommandResult | None = None
        error: BaseException | None = None
        traceback = None
        try:
            self.client.clone(vm_name)
            cloned = True
            process = self.client.start(vm_name, artifact_dir)
            self._wait_for_marker(vm_name, process)
            self.client.inspect(vm_name)
            result = self.client.execute(vm_name, guest_command)
        except BaseException as caught:
            error = caught
            traceback = caught.__traceback__

        cleanup_error = self._cleanup(vm_name, process) if cloned else None
        if error is not None:
            raise error.with_traceback(traceback)
        if cleanup_error is not None:
            raise cleanup_error
        if result is None:
            raise LabRunnerError("guest_result_missing")
        return result

    @contextmanager
    def vnc_session(self, run_id: str):
        vm_name, artifact_dir = self._session_values(run_id)
        artifact_dir.mkdir(parents=True, exist_ok=False)
        started = self.clock()
        timings = {
            "clone_ms": 0,
            "boot_ms": 0,
            "cleanup_ms": 0,
            "total_ms": 0,
        }
        process: CapturedProcess | None = None
        cloned = False
        error: BaseException | None = None
        traceback = None
        try:
            phase_started = self.clock()
            self.client.clone(vm_name)
            timings["clone_ms"] = _elapsed_ms(phase_started, self.clock())
            cloned = True
            phase_started = self.clock()
            process = self.client.start_vnc(vm_name, artifact_dir)
            endpoint = wait_for_vnc_endpoint(
                process,
                timeout_s=self.config.boot_timeout_s,
                clock=self.clock,
            )
            self._wait_for_marker(vm_name, process)
            self.client.inspect(vm_name)
            timings["boot_ms"] = _elapsed_ms(phase_started, self.clock())
            yield VNCGuestSession(
                vm_name=vm_name,
                artifact_dir=artifact_dir,
                vnc_endpoint=endpoint,
                client=self.client,
            )
        except BaseException as caught:
            error = caught
            traceback = caught.__traceback__
        phase_started = self.clock()
        cleanup_error = self._cleanup(vm_name, process) if cloned else None
        timings["cleanup_ms"] = _elapsed_ms(phase_started, self.clock())
        timings["total_ms"] = _elapsed_ms(started, self.clock())
        timing_error = None
        try:
            (artifact_dir / "runner-timings.json").write_text(
                json.dumps(timings, indent=2, sort_keys=True) + "\n"
            )
        except OSError as caught:
            timing_error = LabRunnerError(
                f"runner_timing_write_failed:{type(caught).__name__}"
            )
        if error is not None:
            raise error.with_traceback(traceback)
        if cleanup_error is not None:
            raise cleanup_error
        if timing_error is not None:
            raise timing_error

    def _session_values(self, run_id: str) -> tuple[str, Path]:
        if not _RUN_ID.fullmatch(run_id) or len(run_id) > 64:
            raise ValueError("run_id is invalid")
        vm_name = f"conn-lab-{run_id}"
        if len(vm_name) > 80 or vm_name == self.config.golden_vm:
            raise ValueError("run_id produces an unsafe VM name")
        return (
            vm_name,
            self.config.artifact_root / date.today().isoformat() / run_id,
        )

    def _wait_for_marker(
        self, vm_name: str, process: ManagedProcess
    ) -> None:
        deadline = self.clock() + self.config.boot_timeout_s
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                raise LabRunnerError(f"guest_boot_failed:exit_{exit_code}")
            try:
                marker = self.client.marker(vm_name)
            except CommandTimedOut:
                marker = None
            if marker is not None and marker.returncode == 0:
                return
            now = self.clock()
            if now >= deadline:
                raise LabRunnerError("guest_marker_missing")
            self.sleeper(min(self.config.readiness_poll_s, deadline - now))

    def _cleanup(
        self, vm_name: str, process: ManagedProcess | None
    ) -> LabRunnerError | None:
        failures: list[str] = []
        try:
            stopped = self.client.stop(vm_name)
            if stopped.returncode != 0:
                failures.append("stop")
        except BaseException:
            failures.append("stop")
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=self.config.cleanup_timeout_s)
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=self.config.cleanup_timeout_s)
                except BaseException:
                    process.kill()
                    try:
                        process.wait(timeout=self.config.cleanup_timeout_s)
                    except BaseException:
                        failures.append("process")
        try:
            deleted = self.client.delete(vm_name)
            if deleted.returncode != 0:
                failures.append("delete")
        except BaseException:
            failures.append("delete")
        if failures:
            return LabRunnerError(f"lab_cleanup_failed:{','.join(failures)}")
        return None


def _command(argv: Sequence[str]) -> tuple[str, ...]:
    args = tuple(str(item) for item in argv)
    if not args or len(args) > 128:
        raise ValueError("command must contain 1 to 128 arguments")
    if any(not item or len(item) > 4_096 or "\x00" in item for item in args):
        raise ValueError("command contains an invalid argument")
    return args


def _elapsed_ms(started: float, finished: float) -> int:
    return max(0, round((finished - started) * 1000))


def wait_for_vnc_endpoint(
    process: CapturedProcess,
    *,
    timeout_s: float,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[str, int]:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    deadline = clock() + timeout_s
    while True:
        exit_code = process.poll()
        if exit_code is not None:
            raise LabRunnerError(f"vnc_guest_boot_failed:exit_{exit_code}")
        remaining = deadline - clock()
        if remaining <= 0:
            raise LabRunnerError("vnc_endpoint_missing")
        line = process.read_line(min(remaining, 1))
        if line is None:
            continue
        endpoint = parse_tart_vnc(line)
        if endpoint is not None:
            return endpoint
