"""Subprocess helpers: streaming caps, deadlines on stdin, kill+reap."""

from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass


@dataclass
class CapturedProcess:
    returncode: int | None
    stdout_bytes: bytes
    stderr_bytes: bytes
    timed_out: bool
    duration_sec: float
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    process_reaped: bool = True
    spawn_failed: bool = False

    @property
    def stdout(self) -> str:
        from mctk.bytes_util import bytes_to_display

        return bytes_to_display(self.stdout_bytes, self.stdout_truncated)

    @property
    def stderr(self) -> str:
        from mctk.bytes_util import bytes_to_display

        return bytes_to_display(self.stderr_bytes, self.stderr_truncated)


class _LimitedReader:
    def __init__(self, stream, max_bytes: int) -> None:
        self._stream = stream
        self._max = max_bytes
        self._buf = bytearray()
        self._truncated = False
        self._done = threading.Event()

    def run(self) -> None:
        try:
            while True:
                if len(self._buf) >= self._max:
                    self._truncated = True
                    chunk = self._stream.read(4096)
                    if not chunk:
                        break
                    continue
                room = self._max - len(self._buf)
                chunk = self._stream.read(min(4096, room))
                if not chunk:
                    break
                if len(chunk) > room:
                    self._buf.extend(chunk[:room])
                    self._truncated = True
                    break
                self._buf.extend(chunk)
                if len(self._buf) >= self._max:
                    peek = self._stream.read(1)
                    if peek:
                        self._truncated = True
                        while self._stream.read(4096):
                            pass
                    break
        finally:
            self._done.set()

    def result(self) -> tuple[bytes, bool]:
        self._done.wait(timeout=30)
        return bytes(self._buf), self._truncated


def _write_stdin(proc: subprocess.Popen, data: bytes, deadline_mono: float | None) -> bool:
    if proc.stdin is None:
        return True
    if not data:
        try:
            proc.stdin.close()
        except OSError:
            return False
        return True

    outcome: dict[str, bool] = {"ok": True}

    def _writer() -> None:
        try:
            proc.stdin.write(data)
            proc.stdin.close()
        except OSError:
            outcome["ok"] = False

    thread = threading.Thread(target=_writer, daemon=True)
    thread.start()
    while thread.is_alive():
        if deadline_mono is not None and time.monotonic() >= deadline_mono:
            outcome["ok"] = False
            _kill_tree(proc)
            thread.join(timeout=1.0)
            return False
        thread.join(timeout=0.05)
    return outcome["ok"]


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                check=False,
            )
        else:
            proc.kill()
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _reap(proc: subprocess.Popen) -> bool:
    try:
        proc.wait(timeout=15)
        return True
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.wait(timeout=15)
        return True


def run_captured(
    cmd: list[str],
    *,
    input_text: str | None = None,
    input_bytes: bytes | None = None,
    timeout_sec: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    cwd: str | None = None,
    deadline_mono: float | None = None,
) -> CapturedProcess:
    started = time.monotonic()
    step_deadline = started + timeout_sec
    if deadline_mono is not None:
        step_deadline = min(step_deadline, deadline_mono)

    if step_deadline <= started:
        return CapturedProcess(
            returncode=None,
            stdout_bytes=b"",
            stderr_bytes=b"deadline exhausted before launch",
            timed_out=True,
            duration_sec=0.0,
            process_reaped=True,
        )

    stdin_payload: bytes | None = None
    if input_bytes is not None:
        stdin_payload = input_bytes
    elif input_text is not None:
        stdin_payload = input_text.encode("utf-8")

    proc: subprocess.Popen | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if stdin_payload is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
        )
    except OSError as exc:
        return CapturedProcess(
            returncode=None,
            stdout_bytes=b"",
            stderr_bytes=str(exc).encode("utf-8"),
            timed_out=False,
            duration_sec=time.monotonic() - started,
            process_reaped=True,
            spawn_failed=True,
        )

    out_reader = _LimitedReader(proc.stdout, max_stdout_bytes)
    err_reader = _LimitedReader(proc.stderr, max_stderr_bytes)
    t_out = threading.Thread(target=out_reader.run, daemon=True)
    t_err = threading.Thread(target=err_reader.run, daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    spawn_failed = False
    if stdin_payload is not None:
        if not _write_stdin(proc, stdin_payload, step_deadline):
            timed_out = True
            _kill_tree(proc)

    while proc.poll() is None and not timed_out:
        if time.monotonic() >= step_deadline:
            timed_out = True
            _kill_tree(proc)
            break
        time.sleep(0.02)

    reaped = _reap(proc)
    stdout_bytes, out_trunc = out_reader.result()
    stderr_bytes, err_trunc = err_reader.result()
    duration = time.monotonic() - started

    return CapturedProcess(
        returncode=None if timed_out else proc.returncode,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        timed_out=timed_out,
        duration_sec=duration,
        stdout_truncated=out_trunc,
        stderr_truncated=err_trunc,
        process_reaped=reaped,
        spawn_failed=spawn_failed,
    )
