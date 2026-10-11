import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mctk.limits import ResourceLimits
from mctk.models import BuildProfile, CompilerConfig, InputCase
from mctk.pipeline import execute_profile, execute_suite
from mctk.report import write_report
from mctk.status import Status
from tests.conftest import REAL, require_smoke_toolchain


@pytest.fixture
def add_source(tmp_path: Path) -> Path:
    p = tmp_path / "add.cpp"
    p.write_text(
        "#include <iostream>\n"
        "int main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<\"\\n\";}\n",
        encoding="utf-8",
    )
    return p


def _gcc_config() -> CompilerConfig:
    gcc = require_smoke_toolchain()
    return CompilerConfig.from_toolchain(gcc, "O0")


@REAL
def test_report_embeds_full_source_and_stdin(tmp_path: Path, add_source: Path):
    limits = ResourceLimits()
    profile = BuildProfile(
        source_path=add_source,
        config=_gcc_config(),
        cases=(
            InputCase(name="a", stdin="1 2\n"),
            InputCase(name="b", stdin="3 4\n"),
        ),
        oracle_id="arithmetic_sum",
    )
    report = execute_suite(
        [profile],
        limits,
        tmp_path / "cache",
        expected_release_by_source={str(add_source.resolve()): 1},
        enable_ubsan=False,
    )
    out = tmp_path / "report.json"
    write_report(report, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "iostream" in data["profiles"][0]["source_text"]
    stdins = {r["stdin"] for r in data["profiles"][0]["observations"]["runs"]}
    assert stdins == {"1 2\n", "3 4\n"}
    assert data["resource_limits"]["memory_limit_enforcement"] == "NOT_ENFORCED"
    assert data["interpretation"]["overall_verdict"] == "PASS"


@REAL
def test_compile_once_run_many(add_source: Path, tmp_path: Path):
    limits = ResourceLimits()
    profile = BuildProfile(
        source_path=add_source,
        config=_gcc_config(),
        cases=(
            InputCase(name="one", stdin="1 1\n"),
            InputCase(name="two", stdin="2 2\n"),
        ),
        oracle_id="arithmetic_sum",
    )
    compile_calls = 0
    real_run = __import__("mctk.subprocess_util", fromlist=["run_captured"]).run_captured

    def counting_run(cmd, **kwargs):
        nonlocal compile_calls
        exe = cmd[0].lower()
        if exe.endswith("g++") or exe.endswith("g++.exe"):
            compile_calls += 1
        return real_run(cmd, **kwargs)

    with patch("mctk.compile.run_captured", side_effect=counting_run):
        report = execute_profile(profile, limits, tmp_path / "cache")

    assert compile_calls == 1
    assert all(r.status == Status.OK for r in report.runs)


def test_shared_cases_across_configs_in_loader(tmp_path: Path):
    suite = tmp_path / "suite.yaml"
    src = tmp_path / "t.cpp"
    src.write_text("int main(){}\n", encoding="utf-8")
    suite.write_text(
        f"""
resource_limits:
  overall_deadline_sec: 60
sources:
  - path: {src.name}
    cases:
      - name: a
        stdin: "1\\n"
      - name: b
        stdin: "2\\n"
    compiler_configs:
      - toolchain: g++
        optimization: O0
      - toolchain: g++
        optimization: O2
""",
        encoding="utf-8",
    )
    from mctk.suite_loader import load_suite

    require_smoke_toolchain()
    loaded = load_suite(suite)
    cases_sets = {tuple(c.name for c in p.cases) for p in loaded.profiles}
    assert cases_sets == {("a", "b")}
    assert len(loaded.profiles) == 2
