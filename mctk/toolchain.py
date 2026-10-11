"""Detect C++ compiler families with C++17 smoke probes."""

from __future__ import annotations

import os
import re
import shutil
import textwrap
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from mctk.bytes_util import normalize_bytes_for_compare
from mctk.subprocess_util import run_captured

_SMOKE_SOURCE = (
    '#include <iostream>\n'
    'int main() { std::cout << "mctk_smoke\\n"; return 0; }\n'
)

_PREFER_ID = {"g++": 0, "clang++": 1, "c++": 2}


class CompilerFamily(str, Enum):
    GCC = "gcc"
    CLANG = "clang"
    MSVC = "msvc"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Toolchain:
    id: str
    executable: str
    family: CompilerFamily
    version_line: str
    cpp17_flags: tuple[str, ...] = ("-std=c++17",)
    smoke_ok: bool = False
    smoke_message: str = ""

    def label(self) -> str:
        return f"{self.id} ({self.family.value})"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "executable": self.executable,
            "family": self.family.value,
            "version_line": self.version_line,
            "cpp17_flags": list(self.cpp17_flags),
            "smoke_ok": self.smoke_ok,
            "smoke_message": self.smoke_message,
        }


def _classify_family(version_line: str, executable: str) -> CompilerFamily:
    low = (version_line + executable).lower()
    if "clang" in low:
        return CompilerFamily.CLANG
    if "gcc" in low or "g++" in low or "mingw" in low:
        return CompilerFamily.GCC
    if "microsoft" in low or "msvc" in low:
        return CompilerFamily.MSVC
    return CompilerFamily.UNKNOWN


def _cpp17_smoke(exe: str, probe_dir: Path) -> tuple[bool, str]:
    probe_dir.mkdir(parents=True, exist_ok=True)
    src = (probe_dir / "smoke.cpp").resolve()
    out = (probe_dir / ("smoke.exe" if os.name == "nt" else "smoke")).resolve()
    src.write_text(_SMOKE_SOURCE, encoding="utf-8")
    comp = run_captured(
        [exe, "-std=c++17", str(src), "-o", str(out)],
        timeout_sec=20.0,
        max_stdout_bytes=8192,
        max_stderr_bytes=8192,
    )
    if comp.timed_out or comp.returncode != 0 or not out.is_file():
        detail = (comp.stderr or comp.stdout or "compile failed").strip()
        return False, detail[:500]
    run = run_captured(
        [str(out)],
        timeout_sec=10.0,
        max_stdout_bytes=256,
        max_stderr_bytes=256,
    )
    if run.timed_out or run.returncode != 0:
        return False, "smoke run failed"
    if normalize_bytes_for_compare(run.stdout_bytes) != b"mctk_smoke\n":
        return False, "smoke output unexpected"
    return True, "C++17 smoke compile/run ok"


def _probe_executable(exe: str, id_hint: str, smoke_dir: Path) -> Toolchain | None:
    captured = run_captured(
        [exe, "--version"],
        timeout_sec=10.0,
        max_stdout_bytes=8192,
        max_stderr_bytes=8192,
    )
    if captured.timed_out:
        return None
    if captured.returncode != 0 and not (captured.stdout or captured.stderr):
        return None
    version_line = (captured.stdout or captured.stderr or "").strip().splitlines()
    version_line = version_line[0] if version_line else "unknown"
    family = _classify_family(version_line, exe)
    tid = id_hint
    if family == CompilerFamily.CLANG and tid == "g++":
        tid = "clang++"
    smoke_ok, smoke_msg = _cpp17_smoke(exe, smoke_dir / id_hint.replace("+", "_"))
    if not smoke_ok:
        return None
    return Toolchain(
        id=tid,
        executable=exe,
        family=family,
        version_line=version_line,
        smoke_ok=smoke_ok,
        smoke_message=smoke_msg,
    )


def discover_toolchains(
    extra_candidates: tuple[str, ...] = (),
    *,
    smoke_cache_dir: Path | None = None,
) -> list[Toolchain]:
    smoke_dir = smoke_cache_dir or Path(".mctk_smoke_cache")
    by_realpath: dict[str, Toolchain] = {}
    prefer: dict[str, int] = {}
    for cid in ("g++", "clang++", "c++", *extra_candidates):
        exe = shutil.which(cid)
        if not exe:
            continue
        key = os.path.realpath(exe).lower()
        tc = _probe_executable(exe, cid, smoke_dir)
        if tc is None:
            continue
        rank = _PREFER_ID.get(cid, 99)
        if key not in by_realpath or rank < prefer.get(key, 99):
            by_realpath[key] = tc
            prefer[key] = rank
    return list(by_realpath.values())


def resolve_toolchain(
    name: str,
    discovered: list[Toolchain],
) -> Toolchain | None:
    for tc in discovered:
        if tc.id == name or tc.executable == name:
            return tc
    exe = shutil.which(name)
    if exe:
        return _probe_executable(exe, name, Path(".mctk_smoke_cache"))
    return None


def gcc_like_opt_flag(optimization: str) -> str:
    opt = optimization.strip()
    if opt.startswith("-") or opt.startswith("/"):
        return opt
    if re.match(r"^[Oo]\d", opt):
        return f"-{opt}" if not opt.startswith("-") else opt
    return f"-{opt}"
