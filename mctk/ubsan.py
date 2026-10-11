"""UBSan capability probe and finding extraction."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

from mctk.limits import ResourceLimits
from mctk.models import UbsanFinding, UbsanProbeResult
from mctk.subprocess_util import run_captured
from mctk.toolchain import Toolchain

_PROBE_SOURCE = textwrap.dedent(
    """
    #include <cstdint>
    int main() {
        volatile int x = 1;
        x <<= 31;
        x <<= 1;
        return 0;
    }
    """
).strip()

_UBSAN_MARKERS = (
    "UndefinedBehaviorSanitizer",
    "runtime error:",
    "ubsan:",
)


def ubsan_compile_flags(tc: Toolchain) -> tuple[str, ...]:
    if tc.family.value == "gcc":
        return ("-fsanitize=undefined", "-g", "-fno-omit-frame-pointer")
    if tc.family.value == "clang":
        return ("-fsanitize=undefined", "-g")
    return ("-fsanitize=undefined",)


def ubsan_link_flags(tc: Toolchain) -> tuple[str, ...]:
    if os.name == "nt" and tc.family.value == "gcc":
        return ("-fsanitize=undefined",)
    return ()


def probe_ubsan(tc: Toolchain, limits: ResourceLimits, cache_dir: Path) -> UbsanProbeResult:
    probe_dir = cache_dir / "_ubsan_probe" / tc.id
    probe_dir.mkdir(parents=True, exist_ok=True)
    src = probe_dir / "probe.cpp"
    out = probe_dir / ("probe.exe" if os.name == "nt" else "probe")
    src.write_text(_PROBE_SOURCE, encoding="utf-8")
    src_abs = src.resolve()
    out_abs = out.resolve()

    cmd = [
        tc.executable,
        *tc.cpp17_flags,
        *ubsan_compile_flags(tc),
        str(src_abs),
        "-o",
        str(out_abs),
        *ubsan_link_flags(tc),
    ]
    comp = run_captured(
        cmd,
        timeout_sec=limits.compile_timeout_sec,
        max_stdout_bytes=limits.max_stdout_bytes,
        max_stderr_bytes=limits.max_stderr_bytes,
        cwd=str(probe_dir.resolve()),
    )
    if comp.timed_out or comp.returncode != 0 or not out_abs.is_file():
        detail = comp.stderr or comp.stdout or "compile/link failed"
        return UbsanProbeResult(False, detail.strip()[:500], tc.id)

    run = run_captured(
        [str(out_abs)],
        timeout_sec=limits.run_timeout_sec,
        max_stdout_bytes=limits.max_stdout_bytes,
        max_stderr_bytes=limits.max_stderr_bytes,
    )
    blob = (run.stderr + run.stdout).lower()
    if any(m.lower() in blob for m in _UBSAN_MARKERS):
        return UbsanProbeResult(True, "probe build detected UBSan output", tc.id)
    return UbsanProbeResult(
        False,
        "probe compiled but no UBSan diagnostic output (toolchain may lack UBSan)",
        tc.id,
    )


def extract_ubsan_finding(stderr: str, stdout: str) -> str | None:
    blob = stderr + stdout
    for line in blob.splitlines():
        low = line.lower()
        if any(m.lower() in low for m in _UBSAN_MARKERS):
            return line.strip()
    return None


def finding_from_run(
    *,
    source_path: str,
    toolchain_id: str,
    optimization: str,
    case_name: str,
    stdin: str,
    stderr: str,
    stdout: str,
) -> UbsanFinding | None:
    msg = extract_ubsan_finding(stderr, stdout)
    if not msg:
        return None
    excerpt = (stderr or stdout)[:4000]
    return UbsanFinding(
        source_path=source_path,
        toolchain_id=toolchain_id,
        optimization=optimization,
        case_name=case_name,
        stdin=stdin,
        stderr_excerpt=excerpt,
        message=msg,
    )

