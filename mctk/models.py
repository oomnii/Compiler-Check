"""Suite and result data structures."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mctk.limits import ResourceLimits
from mctk.status import Status
from mctk.toolchain import Toolchain

BuildKind = Literal["release", "ubsan_diagnostic"]


@dataclass(frozen=True)
class CompilerConfig:
    toolchain_id: str
    compiler_executable: str
    family: str
    version_line: str
    optimization: str
    flags: tuple[str, ...] = ()
    build_kind: BuildKind = "release"
    language_std: tuple[str, ...] = ("-std=c++17",)

    def cache_key(self) -> str:
        return self.configuration_id()

    def configuration_id(self) -> str:
        exe = os.path.realpath(self.compiler_executable)
        blob = "|".join(
            (
                exe,
                self.family,
                self.optimization,
                self.build_kind,
                ",".join(self.language_std),
                ",".join(self.flags),
            )
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def from_toolchain(
        cls,
        tc: Toolchain,
        optimization: str,
        *,
        flags: tuple[str, ...] = (),
        build_kind: BuildKind = "release",
    ) -> CompilerConfig:
        return cls(
            toolchain_id=tc.id,
            compiler_executable=tc.executable,
            family=tc.family.value,
            version_line=tc.version_line,
            optimization=optimization,
            flags=flags,
            build_kind=build_kind,
            language_std=tc.cpp17_flags,
        )


@dataclass(frozen=True)
class InputCase:
    name: str
    stdin: str
    expected_stdout: str | None = None
    expected_stderr: str | None = None


@dataclass(frozen=True)
class BuildProfile:
    source_path: Path
    config: CompilerConfig
    cases: tuple[InputCase, ...]
    oracle_id: str | None = None
    template_name: str | None = None


@dataclass
class CompileResult:
    status: Status
    binary_path: Path | None
    stdout: str
    stderr: str
    command: list[str]
    stdout_bytes: bytes = b""
    stderr_bytes: bytes = b""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    timed_out: bool = False
    process_reaped: bool = True
    duration_sec: float | None = None
    cache_hit: bool = False


@dataclass
class RunResult:
    case_name: str
    status: Status
    exit_code: int | None
    stdout: str
    stderr: str
    stdin: str
    stdin_bytes: bytes = b""
    stdout_bytes: bytes = b""
    stderr_bytes: bytes = b""
    timed_out: bool = False
    skipped: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    process_reaped: bool = True
    duration_sec: float = 0.0
    oracle_expected: str | None = None
    oracle_agreement: bool | None = None


@dataclass
class ProfileReport:
    source_path: Path
    source_text: str
    config: CompilerConfig
    compile: CompileResult
    runs: list[RunResult] = field(default_factory=list)
    oracle_id: str | None = None
    template_name: str | None = None

    def observation_summary(self) -> dict[str, Any]:
        from mctk.status import worst_status

        statuses = [self.compile.status, *(r.status for r in self.runs)]
        return {
            "worst_step_status": worst_status(*statuses).label,
            "compile_status": self.compile.status.label,
            "run_statuses": {r.case_name: r.status.label for r in self.runs},
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": str(self.source_path),
            "source_text": self.source_text,
            "template_name": self.template_name,
            "oracle_id": self.oracle_id,
            "observations": {
                "compile": {
                    "status": self.compile.status.label,
                    "command": self.compile.command,
                    "stdout": self.compile.stdout,
                    "stderr": self.compile.stderr,
                    "binary_path": str(self.compile.binary_path)
                    if self.compile.binary_path
                    else None,
                    "timed_out": self.compile.timed_out,
                    "stdout_truncated": self.compile.stdout_truncated,
                    "stderr_truncated": self.compile.stderr_truncated,
                    "process_reaped": self.compile.process_reaped,
                },
                "runs": [
                    {
                        "case_name": r.case_name,
                        "status": r.status.label,
                        "exit_code": r.exit_code,
                        "stdin": r.stdin,
                        "stdout": r.stdout,
                        "stderr": r.stderr,
                        "timed_out": r.timed_out,
                        "skipped": r.skipped,
                        "stdout_truncated": r.stdout_truncated,
                        "stderr_truncated": r.stderr_truncated,
                        "process_reaped": r.process_reaped,
                        "oracle_expected": r.oracle_expected,
                        "oracle_agreement": r.oracle_agreement,
                    }
                    for r in self.runs
                ],
            },
            "observation_summary": self.observation_summary(),
            "compiler_config": {
                "toolchain_id": self.config.toolchain_id,
                "executable": self.config.compiler_executable,
                "family": self.config.family,
                "version_line": self.config.version_line,
                "optimization": self.config.optimization,
                "flags": list(self.config.flags),
                "build_kind": self.config.build_kind,
                "language_std": list(self.config.language_std),
            },
        }


@dataclass
class UbsanProbeResult:
    supported: bool
    message: str
    toolchain_id: str


@dataclass
class UbsanFinding:
    source_path: str
    toolchain_id: str
    optimization: str
    case_name: str
    stdin: str
    stderr_excerpt: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "toolchain_id": self.toolchain_id,
            "optimization": self.optimization,
            "case_name": self.case_name,
            "stdin": self.stdin,
            "stderr_excerpt": self.stderr_excerpt,
            "message": self.message,
        }


@dataclass
class SuiteReport:
    resource_limits: ResourceLimits
    toolchains: list[Toolchain]
    suite_path: Path | None
    run_id: str = ""
    generated_at_utc: str = ""
    profiles: list[ProfileReport] = field(default_factory=list)
    interpretation: dict[str, Any] = field(default_factory=dict)
    ubsan_probe: list[UbsanProbeResult] = field(default_factory=list)
    ubsan_findings: list[UbsanFinding] = field(default_factory=list)
    skipped_toolchains: list[dict[str, str]] = field(default_factory=list)
    expected_release_by_source: dict[str, int] = field(default_factory=dict)
    requested_release_by_source: dict[str, int] = field(default_factory=dict)
    unfulfilled_requested: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_limits": self.resource_limits.to_dict(),
            "toolchains_detected": [t.to_dict() for t in self.toolchains],
            "skipped_toolchains": self.skipped_toolchains,
            "expected_release_by_source": self.expected_release_by_source,
            "requested_release_by_source": self.requested_release_by_source,
            "suite_path": str(self.suite_path) if self.suite_path else None,
            "profiles": [p.to_dict() for p in self.profiles],
            "interpretation": self.interpretation,
            "diagnostics": {
                "ubsan_probe": [
                    {
                        "toolchain_id": p.toolchain_id,
                        "supported": p.supported,
                        "message": p.message,
                    }
                    for p in self.ubsan_probe
                ],
                "ubsan_findings": [f.to_dict() for f in self.ubsan_findings],
                "ubsan_notes": (
                    "UBSan diagnostics use separate ubsan_diagnostic builds and are "
                    "not folded into ordinary cross-config comparisons. "
                    "Clean UBSan runs do not prove absence of undefined behavior."
                ),
            },
        }
