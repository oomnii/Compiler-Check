"""Run a compiled binary against one stdin payload."""

from __future__ import annotations

from pathlib import Path

from mctk.bytes_util import normalize_bytes_for_compare, utf8_bytes
from mctk.deadline import Deadline
from mctk.limits import ResourceLimits
from mctk.models import InputCase, RunResult
from mctk.oracles import OracleFn
from mctk.status import Status
from mctk.subprocess_util import run_captured
from mctk.validation import validate_stdin_bytes


def normalize_output(text: str) -> str:
    return normalize_bytes_for_compare(text.encode("utf-8")).decode("utf-8", errors="replace")


def expected_stdout_for_case(case: InputCase, oracle_fn: OracleFn | None) -> str | None:
    if case.expected_stdout is not None:
        return case.expected_stdout
    if oracle_fn is not None:
        return oracle_fn(case.stdin)
    return None


def stderr_matches(expected_stderr: str | None, stderr_bytes: bytes, *, truncated: bool) -> bool:
    if expected_stderr is None:
        return True
    if truncated:
        return False
    exp_b = normalize_bytes_for_compare(utf8_bytes(expected_stderr))
    err_b = normalize_bytes_for_compare(stderr_bytes)
    return err_b == exp_b


def outputs_match(expected_stdout: str | None, stdout_bytes: bytes, *, truncated: bool) -> bool:
    if expected_stdout is None:
        return True
    if truncated:
        return False
    exp_b = normalize_bytes_for_compare(utf8_bytes(expected_stdout))
    out_b = normalize_bytes_for_compare(stdout_bytes)
    return out_b == exp_b


def resolve_run_status(
    *,
    timed_out: bool,
    spawn_failed: bool,
    exit_code: int | None,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    stdout_truncated: bool,
    stderr_truncated: bool,
    expected_stdout: str | None,
    expected_stderr: str | None,
    use_oracle: bool,
) -> tuple[Status, str | None, bool | None]:
    if timed_out:
        return Status.TIMEOUT, expected_stdout, None
    if spawn_failed or exit_code is None:
        return Status.SPAWN_ERROR, expected_stdout, None
    if stdout_truncated or stderr_truncated:
        if expected_stdout is not None:
            if use_oracle:
                return Status.ORACLE_DISAGREEMENT, expected_stdout, False
            return Status.WRONG_OUTPUT, expected_stdout, None
    if exit_code != 0:
        return Status.RUNTIME_ERROR, expected_stdout, None
    if expected_stderr is not None:
        if not stderr_matches(expected_stderr, stderr_bytes, truncated=stderr_truncated):
            return Status.WRONG_OUTPUT, expected_stdout, None
    if expected_stdout is not None:
        if not outputs_match(expected_stdout, stdout_bytes, truncated=stdout_truncated):
            if use_oracle:
                return Status.ORACLE_DISAGREEMENT, expected_stdout, False
            return Status.WRONG_OUTPUT, expected_stdout, None
    if use_oracle and expected_stdout is not None:
        return Status.OK, expected_stdout, True
    return Status.OK, expected_stdout, None


def run_case(
    binary_path: Path,
    case: InputCase,
    limits: ResourceLimits,
    deadline: Deadline | None = None,
    oracle_fn: OracleFn | None = None,
) -> RunResult:
    stdin_bytes = utf8_bytes(case.stdin)
    validate_stdin_bytes(stdin_bytes)
    if deadline and deadline.expired():
        return skipped_run(
            case,
            Status.DEADLINE_EXCEEDED,
            message="suite overall deadline exceeded before run",
            stdin_bytes=stdin_bytes,
        )

    timeout = limits.run_timeout_sec
    deadline_mono = None
    if deadline:
        timeout = deadline.cap_timeout(timeout)
        deadline_mono = deadline.started_at + deadline.overall_sec
        if timeout <= 0:
            return skipped_run(
                case,
                Status.DEADLINE_EXCEEDED,
                message="suite overall deadline exceeded before run",
                stdin_bytes=stdin_bytes,
            )

    expected = expected_stdout_for_case(case, oracle_fn)
    use_oracle = oracle_fn is not None and case.expected_stdout is None

    captured = run_captured(
        [str(binary_path)],
        input_bytes=stdin_bytes,
        timeout_sec=timeout,
        max_stdout_bytes=limits.max_stdout_bytes,
        max_stderr_bytes=limits.max_stderr_bytes,
        deadline_mono=deadline_mono,
    )

    status, oracle_expected, oracle_agreement = resolve_run_status(
        timed_out=captured.timed_out,
        spawn_failed=captured.spawn_failed,
        exit_code=captured.returncode,
        stdout_bytes=captured.stdout_bytes,
        stderr_bytes=captured.stderr_bytes,
        stdout_truncated=captured.stdout_truncated,
        stderr_truncated=captured.stderr_truncated,
        expected_stdout=expected,
        expected_stderr=case.expected_stderr,
        use_oracle=use_oracle,
    )

    return RunResult(
        case_name=case.name,
        status=status,
        exit_code=captured.returncode,
        stdout=captured.stdout,
        stderr=captured.stderr,
        stdin=case.stdin,
        stdin_bytes=stdin_bytes,
        stdout_bytes=captured.stdout_bytes,
        stderr_bytes=captured.stderr_bytes,
        timed_out=captured.timed_out,
        skipped=False,
        stdout_truncated=captured.stdout_truncated,
        stderr_truncated=captured.stderr_truncated,
        process_reaped=captured.process_reaped,
        duration_sec=captured.duration_sec,
        oracle_expected=oracle_expected,
        oracle_agreement=oracle_agreement,
    )


def skipped_run(
    case: InputCase,
    reason: Status,
    *,
    message: str = "",
    stdin_bytes: bytes | None = None,
) -> RunResult:
    sb = stdin_bytes if stdin_bytes is not None else utf8_bytes(case.stdin)
    return RunResult(
        case_name=case.name,
        status=reason,
        exit_code=None,
        stdout="",
        stderr=message,
        stdin=case.stdin,
        stdin_bytes=sb,
        timed_out=reason == Status.TIMEOUT,
        skipped=True,
    )
