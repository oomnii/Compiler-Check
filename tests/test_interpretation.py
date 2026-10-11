from pathlib import Path

import pytest

from mctk.interpretation import (
    CoverageLevel,
    IssueFlag,
    OverallVerdict,
    interpret_suite,
)
from mctk.models import (
    CompileResult,
    CompilerConfig,
    InputCase,
    ProfileReport,
    RunResult,
)
from mctk.status import Status

MOCK = pytest.mark.mock_subprocess


def _cfg(tid: str, opt: str) -> CompilerConfig:
    return CompilerConfig(
        toolchain_id=tid,
        compiler_executable=tid,
        family="gcc",
        version_line="test",
        optimization=opt,
    )


def _profile(
    src: str,
    tid: str,
    opt: str,
    runs: list[RunResult],
    compile_status: Status = Status.OK,
) -> ProfileReport:
    return ProfileReport(
        source_path=Path(src),
        source_text="int main(){}",
        config=_cfg(tid, opt),
        compile=CompileResult(
            status=compile_status,
            binary_path=Path("x.exe") if compile_status == Status.OK else None,
            stdout="",
            stderr="",
            command=[tid, "x.cpp"],
        ),
        runs=runs,
    )


@MOCK
def test_oracle_failure_despite_compiler_agreement():
    case = InputCase(name="c1", stdin="1 2\n")
    runs_a = [
        RunResult(
            "c1",
            Status.ORACLE_DISAGREEMENT,
            0,
            "99\n",
            "",
            case.stdin,
            oracle_expected="3\n",
            oracle_agreement=False,
        )
    ]
    runs_b = [
        RunResult(
            "c1",
            Status.ORACLE_DISAGREEMENT,
            0,
            "99\n",
            "",
            case.stdin,
            oracle_expected="3\n",
            oracle_agreement=False,
        )
    ]
    profiles = [
        _profile("prog.cpp", "g++", "O0", runs_a),
        _profile("prog.cpp", "g++", "O2", runs_b),
    ]
    result = interpret_suite(
        profiles, expected_release_by_source={"prog.cpp": 2}
    )
    flags = {i["flag"] for i in result["issues"]}
    assert IssueFlag.ORACLE_DISAGREEMENT.value in flags
    assert IssueFlag.OUTPUT_MISMATCH_ACROSS_CONFIGS.value not in flags
    assert result["overall_verdict"] == OverallVerdict.FAIL.value
    assert result["coverage"] == CoverageLevel.FULL.value


@MOCK
def test_mismatch_and_timeout_yields_inconclusive_partial():
    ok_run_a = RunResult(
        "c1", Status.OK, 0, "5\n", "", "2 3\n", stdout_bytes=b"5\n", stdin_bytes=b"2 3\n"
    )
    ok_run_b = RunResult(
        "c1", Status.OK, 0, "9\n", "", "2 3\n", stdout_bytes=b"9\n", stdin_bytes=b"2 3\n"
    )
    timeout_run = RunResult(
        "c1", Status.TIMEOUT, None, "", "", "2 3\n", timed_out=True, skipped=False
    )
    profiles = [
        _profile("prog.cpp", "g++", "O0", [ok_run_a]),
        _profile("prog.cpp", "g++", "O2", [ok_run_b]),
        _profile("prog.cpp", "clang++", "O2", [timeout_run]),
    ]
    result = interpret_suite(
        profiles, expected_release_by_source={"prog.cpp": 3}
    )
    flags = {i["flag"] for i in result["issues"]}
    assert IssueFlag.OUTPUT_MISMATCH_ACROSS_CONFIGS.value in flags
    assert IssueFlag.TIMEOUT.value in flags
    assert result["coverage"] == CoverageLevel.PARTIAL.value
    assert result["overall_verdict"] == OverallVerdict.FAIL.value
