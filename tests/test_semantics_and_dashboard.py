"""Suite semantics, byte policy, and dashboard request guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mctk.bytes_util import normalize_bytes_for_compare
from mctk.compare import cross_config_observations, run_eligible_for_behavior_compare, stdout_mismatch
from mctk.dashboard_validate import validate_origin, validate_run_payload
from mctk.interpretation import IssueFlag, OverallVerdict, interpret_suite
from mctk.models import (
    CompileResult,
    CompilerConfig,
    InputCase,
    ProfileReport,
    RunResult,
)
from mctk.status import Status
from mctk.suite_loader import _load_shared_cases
from mctk.validation import validate_unique_case_names

pytest.importorskip("flask")
from mctk.dashboard import create_app

ROOT = Path(__file__).resolve().parents[1]


def _cfg(opt: str = "O0") -> CompilerConfig:
    return CompilerConfig(
        toolchain_id="g++",
        compiler_executable="g++",
        family="gcc",
        version_line="test",
        optimization=opt,
    )


def test_lone_cr_is_not_normalized_to_lf():
    assert normalize_bytes_for_compare(b"a\rb") == b"a\rb"
    assert normalize_bytes_for_compare(b"a\r\nb") == b"a\nb"
    assert normalize_bytes_for_compare(b"a\rb") != normalize_bytes_for_compare(b"a\nb")


def test_duplicate_case_names_rejected():
    cases = (
        InputCase("same", "1\n"),
        InputCase("same", "2\n"),
    )
    with pytest.raises(ValueError, match="duplicate case name"):
        validate_unique_case_names(cases, context="test.cpp")


def test_partial_executed_coverage_is_inconclusive():
    ok = RunResult("c1", Status.OK, 0, "1\n", "", "x", stdout_bytes=b"1\n", stdin_bytes=b"x")
    skip = RunResult(
        "c1",
        Status.DEADLINE_EXCEEDED,
        None,
        "",
        "deadline",
        "x",
        skipped=True,
        stdin_bytes=b"x",
    )
    profiles = [
        ProfileReport(Path("a.cpp"), "x", _cfg("O0"), CompileResult(Status.OK, None, "", "", []), [ok]),
        ProfileReport(Path("a.cpp"), "x", _cfg("O2"), CompileResult(Status.OK, None, "", "", []), [ok]),
        ProfileReport(Path("a.cpp"), "x", _cfg("O2"), CompileResult(Status.OK, None, "", "", []), [skip]),
    ]
    profiles[2].config = CompilerConfig(
        toolchain_id="clang++",
        compiler_executable="clang++",
        family="clang",
        version_line="t",
        optimization="O2",
    )
    r = interpret_suite(profiles, expected_release_by_source={"a.cpp": 3})
    assert r["coverage"] == "PARTIAL"
    assert r["overall_verdict"] == OverallVerdict.INCONCLUSIVE.value


def test_single_config_without_oracle_is_inconclusive():
    run = RunResult("c1", Status.OK, 0, "5\n", "", "in", stdout_bytes=b"5\n", stdin_bytes=b"in")
    profiles = [
        ProfileReport(
            Path("a.cpp"),
            "x",
            _cfg(),
            CompileResult(Status.OK, None, "", "", []),
            [run],
        )
    ]
    r = interpret_suite(profiles, expected_release_by_source={str(Path("a.cpp")): 1})
    flags = {i["flag"] for i in r["issues"]}
    assert IssueFlag.INSUFFICIENT_COMPARISONS.value in flags
    assert r["overall_verdict"] == OverallVerdict.INCONCLUSIVE.value


def test_oracle_disagreement_still_cross_config_eligible():
    run_a = RunResult(
        "c1",
        Status.ORACLE_DISAGREEMENT,
        0,
        "bad\n",
        "",
        "in",
        stdout_bytes=b"bad\n",
        stdin_bytes=b"in",
        oracle_agreement=False,
    )
    run_b = RunResult(
        "c1",
        Status.OK,
        0,
        "good\n",
        "",
        "in",
        stdout_bytes=b"good\n",
        stdin_bytes=b"in",
    )
    group = [
        ProfileReport(Path("p.cpp"), "x", _cfg("O0"), CompileResult(Status.OK, None, "", "", []), [run_a]),
        ProfileReport(Path("p.cpp"), "x", _cfg("O2"), CompileResult(Status.OK, None, "", "", []), [run_b]),
    ]
    assert run_eligible_for_behavior_compare(run_a)
    eligible = cross_config_observations(group, "c1")
    assert len(eligible) == 2
    assert stdout_mismatch(eligible, "c1")


def test_origin_validation_rejects_host_suffix_tricks():
    with pytest.raises(ValueError):
        validate_origin("http://localhost.evil.example", "localhost:8765")
    with pytest.raises(ValueError):
        validate_origin("http://127.0.0.1.evil.example", "127.0.0.1:8765")


def test_generated_mode_rejects_non_integer_seed():
    app = create_app(ROOT)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = "t"
    body = {
        "mode": "generated",
        "program_id": "arithmetic",
        "seed": None,
        "case_count": 4,
        "toolchains": ["g++"],
        "optimizations": ["O0"],
        "csrf_token": "t",
    }
    known = {"g++"}
    with pytest.raises(ValueError, match="integer"):
        validate_run_payload(body, known_toolchains=known)


def test_custom_mode_requires_at_least_one_toolchain():
    with pytest.raises(ValueError, match="at least one compiler"):
        validate_run_payload(
            {"mode": "custom", "toolchains": [], "optimizations": ["O0"], "source_text": "x", "stdin_text": "y\n"},
            known_toolchains={"g++"},
        )


def test_unknown_run_id_returns_404():
    app = create_app(ROOT)
    app.config["RUNS_DIR"] = str(ROOT / ".pytest_runs_unknown")
    Path(app.config["RUNS_DIR"]).mkdir(parents=True, exist_ok=True)
    client = app.test_client()
    resp = client.get("/api/run/does-not-exist-000/status")
    assert resp.status_code == 404


def test_compile_session_key_includes_source_path():
    from mctk.compile import _session_key

    cfg = _cfg()
    p1 = Path("/tmp/a/main.cpp")
    p2 = Path("/tmp/b/main.cpp")
    d = "abc"
    assert _session_key(p1, d, cfg) != _session_key(p2, d, cfg)
