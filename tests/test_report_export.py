import base64
import json
from pathlib import Path

import pytest

from mctk.bytes_util import (
    SCHEMA_VERSION,
    captured_stream_payload,
    normalize_bytes_for_compare,
    sha256_hex,
    utf8_bytes,
)
from mctk.limits import ResourceLimits
from mctk.models import (
    CompileResult,
    CompilerConfig,
    InputCase,
    ProfileReport,
    RunResult,
    SuiteReport,
)
from mctk.report import build_json_payload, write_report
from mctk.runner import outputs_match
from mctk.status import Status
from mctk.subprocess_util import run_captured


def test_captured_invalid_utf8_base64_roundtrip():
    proc = run_captured(
        [
            "python",
            "-c",
            "import sys; sys.stdout.buffer.write(b'ok\\xff\\xfe\\n')",
        ],
        timeout_sec=10,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
    )
    payload = captured_stream_payload(proc.stdout_bytes, proc.stdout_truncated)
    raw = base64.b64decode(payload["bytes_base64"])
    assert raw == proc.stdout_bytes
    assert payload["bytes_sha256"] == sha256_hex(proc.stdout_bytes)
    assert "\ufffd" in payload["display_text"] or "ok" in payload["display_text"]


def test_whitespace_preserved_in_comparison():
    expected = "a  b\n"
    stdout = utf8_bytes("a  b\r\n")
    assert outputs_match(expected, stdout, truncated=False)
    assert not outputs_match("a b\n", stdout, truncated=False)


def test_report_metadata_and_cache_hit(tmp_path: Path):
    cfg = CompilerConfig(
        toolchain_id="g++",
        compiler_executable="g++",
        family="gcc",
        version_line="test",
        optimization="O0",
    )
    source = "int main(){}\n"
    run = RunResult(
        case_name="c1",
        status=Status.OK,
        exit_code=0,
        stdout="",
        stderr="",
        stdin="1 2\n",
        stdin_bytes=utf8_bytes("1 2\n"),
        stdout_bytes=utf8_bytes("3\n"),
        stderr_bytes=b"",
        duration_sec=0.01,
    )
    profile = ProfileReport(
        source_path=Path("add.cpp"),
        source_text=source,
        config=cfg,
        compile=CompileResult(
            status=Status.OK,
            binary_path=Path("a.exe"),
            stdout="",
            stderr="",
            command=["g++", "-std=c++17", "-O0", "add.cpp", "-o", "a.exe"],
            cache_hit=True,
            duration_sec=None,
        ),
        runs=[run],
    )
    report = SuiteReport(
        resource_limits=ResourceLimits(),
        toolchains=[],
        suite_path=Path("suite.yaml"),
        run_id="testrun_001",
        generated_at_utc="2026-10-11T12:00:00Z",
        profiles=[profile],
    )
    out = tmp_path / "report.json"
    write_report(report, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == SCHEMA_VERSION  # 1.2.0
    assert data["run_id"] == "testrun_001"
    assert data["comparison_policy"]
    comp = data["profiles"][0]["observations"]["compile"]
    assert comp["cache_hit"] is True
    assert comp["duration_sec"] is None
    assert comp["command_argv"]
    assert data["profiles"][0]["source_sha256"] == sha256_hex(utf8_bytes(source))
    assert data["profiles"][0]["observations"]["runs"][0]["stdin_sha256"] == sha256_hex(
        utf8_bytes("1 2\n")
    )
    assert "_meta" in data and data["_meta"]["reproduction"]["powershell_scripts"]


def test_normalize_bytes_only_crlf():
    assert normalize_bytes_for_compare(b"a\r\nb") == b"a\nb"
    assert normalize_bytes_for_compare(b"a  b\n") == b"a  b\n"
    assert normalize_bytes_for_compare(b"a\rb") == b"a\rb"
