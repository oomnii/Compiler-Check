import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from mctk.dashboard import _safe_report_path, create_app

from tests.conftest import require_smoke_toolchain

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_index_serves_ui():
    app = create_app(ROOT)
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"CompilerCheck" in resp.data
    assert b"dashboard.css" in resp.data


def test_dashboard_run_and_download(tmp_path):
    require_smoke_toolchain()
    app = create_app(ROOT)
    app.config["RUNS_DIR"] = str(tmp_path)
    app.config["SUITES"] = {"quick": str(ROOT / "examples" / "suite.yaml")}
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["csrf_token"] = "testtoken"

    resp = client.post(
        "/run",
        data={"suite_id": "quick", "csrf_token": "testtoken"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("run_id")
    assert body.get("report")
    runs = list(tmp_path.glob("*.json"))
    assert runs
    run_id = runs[0].stem
    dl = client.get(f"/download/{run_id}/report.json")
    assert dl.status_code == 200
    data = json.loads(dl.data)
    assert data["schema_version"] == "1.2.0"


def test_dashboard_rejects_bad_run_id():
    app = create_app(ROOT)
    client = app.test_client()
    assert client.get("/download/../evil/report.json").status_code == 404


def test_safe_report_path_rejects_traversal(tmp_path):
    with pytest.raises(Exception):
        _safe_report_path(tmp_path, "../../outside")
