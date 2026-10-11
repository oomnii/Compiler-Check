"""Persist suite reports (JSON + text) with byte-accurate exports and PowerShell repro."""

from __future__ import annotations

import base64
import json
import os
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mctk.bytes_util import (
    COMPARISON_POLICY,
    SCHEMA_VERSION,
    captured_stream_payload,
    sha256_hex,
    utf8_bytes,
)
from mctk.limits import RESOURCE_LIMITS_DOC
from mctk.models import ProfileReport, RunResult, SuiteReport
from mctk.status import STATUS_PRECEDENCE_DOC


def ensure_report_metadata(report: SuiteReport) -> None:
    if not report.run_id:
        report.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    if not report.generated_at_utc:
        report.generated_at_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _serialize_compile(comp) -> dict[str, Any]:
    return {
        "status": comp.status.label,
        "command_argv": comp.command,
        "stdout": captured_stream_payload(comp.stdout_bytes, comp.stdout_truncated),
        "stderr": captured_stream_payload(comp.stderr_bytes, comp.stderr_truncated),
        "binary_path": str(comp.binary_path) if comp.binary_path else None,
        "timed_out": comp.timed_out,
        "process_reaped": comp.process_reaped,
        "duration_sec": comp.duration_sec,
        "cache_hit": comp.cache_hit,
    }


def _serialize_run(r: RunResult) -> dict[str, Any]:
    return {
        "case_name": r.case_name,
        "status": r.status.label,
        "exit_code": r.exit_code,
        "stdin": r.stdin,
        "stdin_sha256": sha256_hex(r.stdin_bytes),
        "stdin_bytes_base64": base64.b64encode(r.stdin_bytes).decode("ascii"),
        "stdout": captured_stream_payload(r.stdout_bytes, r.stdout_truncated),
        "stderr": captured_stream_payload(r.stderr_bytes, r.stderr_truncated),
        "timed_out": r.timed_out,
        "skipped": r.skipped,
        "process_reaped": r.process_reaped,
        "duration_sec": r.duration_sec,
        "oracle_expected": r.oracle_expected,
        "oracle_agreement": r.oracle_agreement,
    }


def _serialize_profile(p: ProfileReport) -> dict[str, Any]:
    source_bytes = utf8_bytes(p.source_text)
    return {
        "source_path": str(p.source_path),
        "source_text": p.source_text,
        "source_sha256": sha256_hex(source_bytes),
        "source_bytes_base64": base64.b64encode(source_bytes).decode("ascii"),
        "template_name": p.template_name,
        "oracle_id": p.oracle_id,
        "observations": {
            "compile": _serialize_compile(p.compile),
            "runs": [_serialize_run(r) for r in p.runs],
        },
        "observation_summary": p.observation_summary(),
            "compiler_config": {
                "configuration_id": p.config.configuration_id(),
                "toolchain_id": p.config.toolchain_id,
                "executable": p.config.compiler_executable,
            "family": p.config.family,
            "version_line": p.config.version_line,
            "optimization": p.config.optimization,
            "flags": list(p.config.flags),
            "build_kind": p.config.build_kind,
            "language_std": list(p.config.language_std),
        },
    }


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _repro_compile_argv_ps(command: list[str], p: ProfileReport) -> list[str]:
    src = str(p.source_path.resolve())
    bin_p = str(p.compile.binary_path.resolve()) if p.compile.binary_path else ""
    exe_name = "program.exe" if os.name == "nt" else "program"
    mapped: list[str] = []
    skip = False
    for i, arg in enumerate(command):
        if skip:
            skip = False
            continue
        if arg == "-o" and i + 1 < len(command):
            mapped.extend(["-o", "$BinaryFile"])
            skip = True
            continue
        if arg == src or (arg.endswith(".cpp") and Path(arg).name == Path(src).name):
            mapped.append("$SourceFile")
        elif bin_p and arg == bin_p:
            mapped.append("$BinaryFile")
        else:
            mapped.append(arg)
    if "$BinaryFile" not in mapped:
        mapped.extend(["-o", "$BinaryFile"])
    return mapped


def _profile_powershell_script(report: SuiteReport, idx: int, p: ProfileReport) -> str:
    profile_slug = f"profile_{idx}_{p.config.toolchain_id}_{p.config.optimization}"
    source_b64 = base64.b64encode(utf8_bytes(p.source_text)).decode("ascii")
    comp_argv = _repro_compile_argv_ps(p.compile.command, p)
    argv_ps = ", ".join(
        part if part.startswith("$") else _ps_quote(part) for part in comp_argv
    )
    lines = [
        f"# Profile {profile_slug} (run_id={report.run_id})",
        "$ReproDir = Join-Path $PSScriptRoot " + _ps_quote(f"repro_{report.run_id}_{profile_slug}"),
        "New-Item -ItemType Directory -Force -Path $ReproDir | Out-Null",
        "$SourceFile = Join-Path $ReproDir 'source.cpp'",
        "$BinaryFile = Join-Path $ReproDir " + _ps_quote("program.exe" if os.name == "nt" else "program"),
        f"[System.IO.File]::WriteAllBytes($SourceFile, [Convert]::FromBase64String({_ps_quote(source_b64)}))",
        f"$CompileArgv = @({argv_ps})",
        "$CompileRest = @()",
        "if ($CompileArgv.Length -gt 1) { $CompileRest = $CompileArgv[1..($CompileArgv.Length-1)] }",
        "& $CompileArgv[0] @CompileRest",
        "if ($LASTEXITCODE -ne 0) { throw 'Repro compile failed' }",
    ]
    for r in p.runs:
        if r.skipped:
            continue
        stdin_b64 = base64.b64encode(r.stdin_bytes).decode("ascii")
        case_file = f"stdin_{r.case_name}.bin"
        lines.extend(
            [
                f"# case {r.case_name}",
                f"$StdinFile = Join-Path $ReproDir {_ps_quote(case_file)}",
                f"[System.IO.File]::WriteAllBytes($StdinFile, [Convert]::FromBase64String({_ps_quote(stdin_b64)}))",
                "$StdinBytes = [System.IO.File]::ReadAllBytes($StdinFile)",
                "$psi = New-Object System.Diagnostics.ProcessStartInfo",
                "$psi.FileName = $BinaryFile",
                "$psi.UseShellExecute = $false",
                "$psi.RedirectStandardInput = $true",
                "$psi.RedirectStandardOutput = $true",
                "$psi.RedirectStandardError = $true",
                "$proc = [System.Diagnostics.Process]::Start($psi)",
                "$proc.StandardInput.BaseStream.Write($StdinBytes, 0, $StdinBytes.Length)",
                "$proc.StandardInput.Close()",
                "$stdoutText = $proc.StandardOutput.ReadToEnd()",
                "$stderrText = $proc.StandardError.ReadToEnd()",
                "$proc.WaitForExit()",
                f"Write-Host \"case {r.case_name} exit=$($proc.ExitCode)\"",
            ]
        )
    return "\n".join(lines)


def _powershell_repro_bundle(report: SuiteReport) -> dict[str, Any]:
    scripts: list[dict[str, Any]] = []
    for idx, p in enumerate(report.profiles):
        if p.compile.status.label != "ok" or not p.compile.command:
            continue
        script = _profile_powershell_script(report, idx, p)
        scripts.append(
            {
                "profile_index": idx,
                "profile_slug": f"profile_{idx}_{p.config.toolchain_id}_{p.config.optimization}",
                "script": script,
            }
        )
    return {
        "powershell_scripts": scripts,
        "notes": (
            "Use Set-Location to a directory whose path contains spaces if desired; "
            "scripts rely on $PSScriptRoot, Join-Path, literal-path file writes, and "
            "the call operator (&) for the compiler executable."
        ),
    }


def reproduction_powershell_lines(report: SuiteReport) -> list[str]:
    bundle = _powershell_repro_bundle(report)
    out: list[str] = []
    for entry in bundle["powershell_scripts"]:
        out.append(f"# --- {entry['profile_slug']} ---")
        out.extend(entry["script"].splitlines())
        out.append("")
    return out


def build_json_payload(report: SuiteReport) -> dict[str, Any]:
    ensure_report_metadata(report)
    base = report.to_dict()
    base["schema_version"] = SCHEMA_VERSION
    base["run_id"] = report.run_id
    base["generated_at_utc"] = report.generated_at_utc
    base["comparison_policy"] = COMPARISON_POLICY
    base["profiles"] = [_serialize_profile(p) for p in report.profiles]
    repro = _powershell_repro_bundle(report)
    base["_meta"] = {
        "status_precedence": STATUS_PRECEDENCE_DOC,
        "resource_limits_doc": RESOURCE_LIMITS_DOC,
        "reproduction": repro,
        "reproduction_powershell_text": "\n".join(reproduction_powershell_lines(report)),
    }
    return base


def render_text_report(report: SuiteReport) -> str:
    ensure_report_metadata(report)
    payload = build_json_payload(report)
    interp = payload.get("interpretation") or {}
    parts = [
        "CompilerCheck — Suite Report",
        f"schema_version: {payload.get('schema_version')}",
        f"run_id: {payload.get('run_id')}",
        f"generated_at_utc: {payload.get('generated_at_utc')}",
        f"Platform: {platform.platform()}",
        f"Comparison policy: {payload.get('comparison_policy')}",
        f"Overall verdict: {interp.get('overall_verdict', 'N/A')}",
        f"Executed coverage: {interp.get('coverage', 'N/A')}",
        f"Requested coverage: {interp.get('requested_coverage', 'N/A')}",
        "",
        "Resource limits:",
        json.dumps(payload["resource_limits"], indent=2),
        "",
        "Issues (not collapsed):",
    ]
    for iss in interp.get("issues") or []:
        parts.append(f"  - [{iss['flag']}] {iss['message']} ({iss.get('case_name')})")

    parts.extend(["", "PowerShell reproduction:", *reproduction_powershell_lines(report)])
    return "\n".join(parts) + "\n"


def write_report(report: SuiteReport, json_path: Path, text_path: Path | None = None) -> None:
    ensure_report_metadata(report)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_json_payload(report)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    txt = text_path or json_path.with_suffix(".txt")
    txt.write_text(render_text_report(report), encoding="utf-8")
