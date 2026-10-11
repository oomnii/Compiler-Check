"""Flask dashboard: responsive CompilerCheck UI over the verification engine."""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from mctk.dashboard_builder import (
    EXAMPLE_SUITES,
    GENERATED_PROGRAMS,
    build_loaded_suite,
    example_suite_paths,
    plan_run,
    preview_example_source,
)
from mctk.pipeline import execute_suite
from mctk.report import write_report
from mctk.toolchain import discover_toolchains
from mctk.ubsan import probe_ubsan
from mctk.dashboard_validate import validate_origin, validate_run_payload
from mctk.limits import ResourceLimits
import yaml

_PKG = Path(__file__).resolve().parent
_RUN_ID_RE = __import__("re").compile(r"^[0-9A-Za-zTZ._-]+$")
_RUN_LOCK = threading.Lock()
_BUSY = False

_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()


def _example_ubsan_flags(project_root: Path) -> dict[str, bool]:
    examples = (project_root / "examples").resolve()
    out: dict[str, bool] = {}
    for sid, meta in EXAMPLE_SUITES.items():
        path = examples / meta["file"]
        if not path.is_file():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        out[sid] = bool(data.get("ubsan", True))
    return out


@dataclass
class BootstrapData:
    csrf_token: str
    toolchains: list[dict[str, Any]]
    examples: dict[str, dict[str, str]]
    example_ubsan: dict[str, bool]
    generated_programs: dict[str, dict[str, str]]
    ubsan_status: list[dict[str, Any]]
    optimizations: list[str]
    busy: bool
    custom_default_source: str = field(
        default=(
            '#include <iostream>\n'
            "int main() {\n"
            "    int a, b;\n"
            "    if (!(std::cin >> a >> b)) return 1;\n"
            "    std::cout << (a + b) << '\\n';\n"
            "    return 0;\n"
            "}\n"
        )
    )


def _safe_report_path(runs_dir: Path, run_id: str) -> Path:
    if not run_id or not _RUN_ID_RE.match(run_id):
        abort(400, "invalid run id")
    path = (runs_dir / f"{run_id}.json").resolve()
    if not str(path).startswith(str(runs_dir.resolve())):
        abort(400, "invalid run path")
    return path


def _allowed_host() -> bool:
    host = (request.host or "").split(":")[0].lower()
    return host in ("127.0.0.1", "localhost")


def _check_origin() -> None:
    try:
        validate_origin(request.headers.get("Origin"), request.host or "")
    except ValueError as exc:
        abort(403, str(exc))


def _ubsan_summary(toolchains, runs_dir: Path) -> list[dict[str, Any]]:
    limits = ResourceLimits()
    out: list[dict[str, Any]] = []
    for tc in toolchains:
        probe = probe_ubsan(tc, limits, runs_dir / "_ubsan_probe")
        short = probe.message.split("\r")[0][:120]
        if len(probe.message) > 120:
            short += "…"
        out.append(
            {
                "toolchain_id": tc.id,
                "supported": probe.supported,
                "summary": short,
                "message": probe.message,
            }
        )
    return out


def _bootstrap(project_root: Path, runs_dir: Path) -> BootstrapData:
    tcs = discover_toolchains(smoke_cache_dir=runs_dir / "_smoke")
    return BootstrapData(
        csrf_token=session.get("csrf_token", ""),
        toolchains=[t.to_dict() for t in tcs],
        examples={k: v for k, v in EXAMPLE_SUITES.items() if k in example_suite_paths(project_root)},
        example_ubsan=_example_ubsan_flags(project_root),
        generated_programs=GENERATED_PROGRAMS,
        ubsan_status=_ubsan_summary(tcs, runs_dir),
        optimizations=["O0", "O2"],
        busy=_BUSY,
    )


def _run_verification_thread(
    app: Flask,
    run_id: str,
    payload: dict[str, Any],
    project_root: Path,
) -> None:
    global _BUSY
    started = time.monotonic()
    try:
        rd = Path(app.config["RUNS_DIR"])
        work_dir = rd / run_id / "work"
        json_path = rd / f"{run_id}.json"
        txt_path = rd / f"{run_id}.txt"

        loaded = build_loaded_suite(payload, project_root, work_dir)
        suite_path = None
        if payload.get("mode") == "example":
            sid = str(payload.get("suite_id", "quick"))
            suite_path = example_suite_paths(project_root).get(sid)

        report = execute_suite(
            loaded.profiles,
            loaded.limits,
            work_dir=work_dir,
            suite_path=suite_path,
            expected_release_by_source=loaded.expected_release_by_source,
            requested_release_by_source=loaded.requested_release_by_source,
            unfulfilled_requested=loaded.unfulfilled_requested,
            enable_ubsan=loaded.enable_ubsan,
            skipped_toolchains=loaded.skipped_toolchains,
        )
        report.run_id = run_id
        report.generated_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        write_report(report, json_path, txt_path)
        elapsed = time.monotonic() - started
        with _JOBS_LOCK:
            _JOBS[run_id] = {
                "status": "complete",
                "elapsed_sec": round(elapsed, 3),
                "error": None,
            }
    except Exception as exc:
        elapsed = time.monotonic() - started
        with _JOBS_LOCK:
            _JOBS[run_id] = {
                "status": "error",
                "elapsed_sec": round(elapsed, 3),
                "error": str(exc),
            }
    finally:
        global _BUSY
        _BUSY = False
        try:
            _RUN_LOCK.release()
        except RuntimeError:
            pass


def create_app(project_root: Path) -> Flask:
    project_root = project_root.resolve()

    app = Flask(
        __name__,
        template_folder=str(_PKG / "templates"),
        static_folder=str(_PKG / "static"),
        static_url_path="/static",
    )
    app.secret_key = secrets.token_hex(16)
    app.config["PROJECT_ROOT"] = str(project_root)
    app.config["RUNS_DIR"] = str(project_root / ".dashboard_runs")

    def _runs_dir() -> Path:
        p = Path(app.config["RUNS_DIR"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _load_report_json(run_id: str) -> dict[str, Any] | None:
        path = _safe_report_path(_runs_dir(), run_id)
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @app.before_request
    def _csrf_seed():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)

    @app.before_request
    def _local_only_mutations():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not _allowed_host():
                abort(403, "Dashboard accepts mutations on localhost only")

    @app.after_request
    def _dashboard_identity(response):
        response.headers["X-CompilerCheck-UI"] = "2"
        return response

    @app.get("/")
    def index():
        boot = _bootstrap(project_root, _runs_dir())
        return render_template(
            "dashboard/index.html",
            bootstrap_json=json.dumps(asdict(boot), ensure_ascii=False),
        )

    @app.get("/api/bootstrap")
    def api_bootstrap():
        boot = _bootstrap(project_root, _runs_dir())
        return jsonify(asdict(boot))

    @app.post("/api/plan")
    def api_plan():
        _check_origin()
        if not request.is_json:
            abort(400, "JSON body required")
        body = request.get_json(silent=True) or {}
        try:
            plan = plan_run(body, project_root)
            return jsonify(asdict(plan))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    @app.get("/api/example/<suite_id>/source")
    def api_example_source(suite_id: str):
        if suite_id not in EXAMPLE_SUITES:
            abort(404)
        text = preview_example_source(project_root, suite_id)
        return jsonify({"suite_id": suite_id, "source_text": text})

    @app.post("/api/run")
    def api_run():
        global _BUSY
        _check_origin()
        if not request.is_json:
            abort(400, "JSON body required")
        body = request.get_json(silent=True) or {}
        token = body.get("csrf_token", "")
        if token != session.get("csrf_token"):
            return jsonify({"error": "Invalid CSRF token."}), 403
        if not _RUN_LOCK.acquire(blocking=False):
            return jsonify({"error": "A verification run is already in progress."}), 409
        if _BUSY:
            _RUN_LOCK.release()
            return jsonify({"error": "A verification run is already in progress."}), 409

        try:
            known = {t["id"] for t in _bootstrap(project_root, _runs_dir()).toolchains}
            body = validate_run_payload(body, known_toolchains=known)
        except ValueError as exc:
            _RUN_LOCK.release()
            _BUSY = False
            return jsonify({"error": str(exc)}), 400

        _BUSY = True
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        with _JOBS_LOCK:
            _JOBS[run_id] = {"status": "running", "elapsed_sec": 0.0, "error": None, "started_mono": time.monotonic()}

        thread = threading.Thread(
            target=_run_verification_thread,
            args=(app, run_id, body, project_root),
            daemon=True,
        )
        thread.start()
        session["csrf_token"] = secrets.token_hex(16)
        return jsonify(
            {
                "run_id": run_id,
                "status": "running",
                "csrf_token": session["csrf_token"],
            }
        )

    @app.get("/api/run/<run_id>/status")
    def api_run_status(run_id: str):
        _safe_report_path(_runs_dir(), run_id)
        with _JOBS_LOCK:
            job = dict(_JOBS.get(run_id) or {})
        if not job:
            report_path = _runs_dir() / f"{run_id}.json"
            if not report_path.is_file():
                return jsonify({"error": "unknown run id", "run_id": run_id}), 404
            job = {"status": "complete", "elapsed_sec": None, "error": None}
        if job.get("status") == "running":
            started = job.get("started_mono", time.monotonic())
            job["elapsed_sec"] = round(time.monotonic() - started, 3)
        if job.get("status") == "complete":
            report = _load_report_json(run_id)
            if report:
                job["report"] = report
        return jsonify({"run_id": run_id, **job})

    def _sync_run(body: dict[str, Any]) -> tuple[str, dict[str, Any] | None, str | None]:
        global _BUSY
        if not _RUN_LOCK.acquire(blocking=False):
            return "", None, "A verification run is already in progress."
        if _BUSY:
            _RUN_LOCK.release()
            return "", None, "A verification run is already in progress."
        _BUSY = True
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
        _run_verification_thread(app, run_id, body, project_root)
        report = _load_report_json(run_id)
        with _JOBS_LOCK:
            job = _JOBS.get(run_id, {})
        if report is None:
            return run_id, None, job.get("error") or "Run failed"
        return run_id, report, None

    @app.post("/run")
    def run_suite_legacy():
        """Synchronous form POST (integration tests)."""
        token = request.form.get("csrf_token", "")
        if token != session.get("csrf_token"):
            return jsonify({"error": "Invalid CSRF token."}), 403
        body = {
            "mode": "example",
            "suite_id": request.form.get("suite_id", "quick"),
            "enable_ubsan": True,
        }
        run_id, report, err = _sync_run(body)
        session["csrf_token"] = secrets.token_hex(16)
        if err:
            return jsonify({"error": err, "run_id": run_id or None}), 500
        return jsonify({"run_id": run_id, "report": report})

    @app.get("/download/<run_id>/report.json")
    def download_json(run_id: str):
        path = _safe_report_path(_runs_dir(), run_id)
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name="report.json")

    @app.get("/download/<run_id>/report.txt")
    def download_txt(run_id: str):
        path = _safe_report_path(_runs_dir(), run_id).with_suffix(".txt")
        if not path.is_file():
            abort(404)
        return send_file(path, as_attachment=True, download_name="report.txt")

    return app


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description="CompilerCheck local dashboard")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    app = create_app(args.project_root)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
