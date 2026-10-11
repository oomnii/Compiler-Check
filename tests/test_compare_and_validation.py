"""Compare policy, interpretation edge cases, and input validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from mctk.compare import normalized_stdout_bytes
from mctk.inputgen import generate_cases
from mctk.interpretation import IssueFlag, OverallVerdict, interpret_suite
from mctk.models import (
    CompileResult,
    CompilerConfig,
    InputCase,
    ProfileReport,
    RunResult,
)
from mctk.oracles import oracle_sort_array
from mctk.runner import resolve_run_status
from mctk.status import Status
from mctk.validation import validate_case_count


def _cfg() -> CompilerConfig:
    return CompilerConfig(
        toolchain_id="g++",
        compiler_executable="g++",
        family="gcc",
        version_line="test",
        optimization="O0",
    )


def test_stdout_compare_normalizes_crlf_only():
    run = RunResult(
        "c",
        Status.OK,
        0,
        "1\r\n",
        "",
        "x",
        stdout_bytes=b"1\r\n",
        stdin_bytes=b"x",
    )
    assert normalized_stdout_bytes(run) == b"1\n"


def test_truncated_stdout_is_not_ok():
    st, _, _ = resolve_run_status(
        timed_out=False,
        spawn_failed=False,
        exit_code=0,
        stdout_bytes=b"ok\n",
        stderr_bytes=b"",
        stdout_truncated=True,
        stderr_truncated=False,
        expected_stdout="ok\n",
        expected_stderr=None,
        use_oracle=False,
    )
    assert st == Status.WRONG_OUTPUT


def test_empty_suite_yields_fail():
    r = interpret_suite([], expected_release_by_source={})
    assert r["overall_verdict"] == OverallVerdict.FAIL.value
    assert any(i["flag"] == IssueFlag.EMPTY_SUITE.value for i in r["issues"])


def test_compile_error_and_insufficient_comparisons_fail():
    run = RunResult(
        "c1",
        Status.OK,
        0,
        "5\n",
        "",
        "in",
        stdout_bytes=b"5\n",
        stdin_bytes=b"in",
    )
    profiles = [
        ProfileReport(
            source_path=Path("a.cpp"),
            source_text="x",
            config=_cfg(),
            compile=CompileResult(Status.OK, None, "", "", []),
            runs=[run],
        ),
        ProfileReport(
            source_path=Path("a.cpp"),
            source_text="x",
            config=
            CompilerConfig(
                toolchain_id="g++",
                compiler_executable="g++",
                family="gcc",
                version_line="t",
                optimization="O2",
            ),
            compile=CompileResult(Status.COMPILE_ERROR, None, "", "", []),
            runs=[
                RunResult(
                    "c1",
                    Status.SKIPPED,
                    None,
                    "",
                    "",
                    "in",
                    skipped=True,
                    stdin_bytes=b"in",
                )
            ],
        ),
    ]
    r = interpret_suite(profiles, expected_release_by_source={str(Path("a.cpp")): 2})
    flags = {i["flag"] for i in r["issues"]}
    assert IssueFlag.INSUFFICIENT_COMPARISONS.value in flags
    assert IssueFlag.COMPILE_ERROR.value in flags
    assert r["overall_verdict"] == OverallVerdict.FAIL.value


def test_case_count_cap_enforced():
    with pytest.raises(ValueError):
        validate_case_count(31)


def test_sort_oracle_empty_input():
    assert oracle_sort_array("0\n") == "\n"


def test_sort_generator_includes_empty_boundary():
    cases = generate_cases("sort_array", 99, 5)
    assert cases[0].name == "boundary_empty"
    assert cases[0].stdin == "0\n"


def test_configuration_ids_differ_by_optimization():
    a = _cfg()
    b = CompilerConfig(
        toolchain_id="g++",
        compiler_executable="g++",
        family="gcc",
        version_line="test",
        optimization="O2",
    )
    assert a.configuration_id() != b.configuration_id()
