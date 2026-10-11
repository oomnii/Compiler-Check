import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import REAL, require_smoke_toolchain

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_SUITE = ROOT / "examples" / "suite.yaml"


@REAL
def test_example_suite_via_cli(tmp_path: Path):
    require_smoke_toolchain()
    report_path = tmp_path / "report.json"
    cache_dir = tmp_path / "cache"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mctk.cli",
            str(EXAMPLE_SUITE),
            "--cache-dir",
            str(cache_dir),
            "--report",
            str(report_path),
        ],
        cwd=ROOT / "examples",
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(report_path.read_text(encoding="utf-8"))
    release = [
        p for p in data["profiles"] if p["compiler_config"]["build_kind"] == "release"
    ]
    assert len(release) >= 2
    case_sets = [
        tuple(r["case_name"] for r in p["observations"]["runs"]) for p in release
    ]
    assert len(set(case_sets)) == 1
    assert case_sets[0] == ("small", "medium", "large")
    assert data["interpretation"]["overall_verdict"] == "PASS"
    assert data["interpretation"]["coverage"] == "FULL"
    assert data["interpretation"]["requested_coverage"] == "PARTIAL"
    assert data["interpretation"]["unfulfilled_requested_configurations"]
    assert data["schema_version"]
    assert data["run_id"]
    assert data["_meta"]["reproduction"]["powershell_scripts"]


@REAL
def test_generated_suite_via_cli(tmp_path: Path):
    require_smoke_toolchain()
    report_path = tmp_path / "generated.json"
    cache_dir = tmp_path / "cache"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "mctk.cli",
            "generated_suite.yaml",
            "--cache-dir",
            str(cache_dir),
            "--report",
            str(report_path),
        ],
        cwd=ROOT / "examples",
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    data = json.loads(report_path.read_text(encoding="utf-8"))
    release = [
        p for p in data["profiles"] if p["compiler_config"]["build_kind"] == "release"
    ]
    assert len(release) == 6
    assert data["interpretation"]["coverage"] == "FULL"
    assert report_path.with_suffix(".txt").exists()
