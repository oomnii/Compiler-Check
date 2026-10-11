import subprocess
import sys
import textwrap

import pytest

from mctk.subprocess_util import run_captured

MOCK = pytest.mark.mock_subprocess


@MOCK
def test_stdout_cap_enforced_during_capture():
    code = textwrap.dedent(
        """
        import sys
        sys.stdout.write("a" * 10000)
        """
    )
    proc = run_captured(
        [sys.executable, "-c", code],
        timeout_sec=10,
        max_stdout_bytes=128,
        max_stderr_bytes=128,
    )
    assert proc.stdout_truncated
    assert len(proc.stdout.encode("utf-8")) <= 128 + 64
    assert proc.process_reaped


@MOCK
def test_timeout_kills_and_reaps():
    code = "import time; time.sleep(30)"
    proc = run_captured(
        [sys.executable, "-c", code],
        timeout_sec=0.3,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
    )
    assert proc.timed_out
    assert proc.process_reaped
    assert proc.returncode is None
