from mctk.models import InputCase
from mctk.runner import resolve_run_status
from mctk.status import Status


def test_spawn_error_when_exit_none():
    st, _, _ = resolve_run_status(
        timed_out=False,
        spawn_failed=True,
        exit_code=None,
        stdout_bytes=b"",
        stderr_bytes=b"",
        stdout_truncated=False,
        stderr_truncated=False,
        expected_stdout=None,
        expected_stderr=None,
        use_oracle=False,
    )
    assert st == Status.SPAWN_ERROR


def test_resolve_run_status_timeout_beats_wrong_output():
    case = InputCase(name="t", stdin="", expected_stdout="x")
    assert (
        resolve_run_status(
            timed_out=True,
            spawn_failed=False,
            exit_code=None,
            stdout_bytes=b"",
            stderr_bytes=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            expected_stdout=case.expected_stdout,
            expected_stderr=None,
            use_oracle=False,
        )[0]
        == Status.TIMEOUT
    )


def test_oracle_disagreement_status():
    assert (
        resolve_run_status(
            timed_out=False,
            spawn_failed=False,
            exit_code=0,
            stdout_bytes=b"wrong",
            stderr_bytes=b"",
            stdout_truncated=False,
            stderr_truncated=False,
            expected_stdout="right\n",
            expected_stderr=None,
            use_oracle=True,
        )[0]
        == Status.ORACLE_DISAGREEMENT
    )


def test_truncated_stdout_ineligible_for_ok():
    assert (
        resolve_run_status(
            timed_out=False,
            spawn_failed=False,
            exit_code=0,
            stdout_bytes=b"right\n",
            stderr_bytes=b"",
            stdout_truncated=True,
            stderr_truncated=False,
            expected_stdout="right\n",
            expected_stderr=None,
            use_oracle=False,
        )[0]
        == Status.WRONG_OUTPUT
    )
