"""Separate observations, issues, coverage, and overall verdict."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mctk.compare import (
    configuration_label,
    cross_config_observations,
    exit_code_mismatch,
    stderr_mismatch,
    stdout_mismatch,
)
from mctk.models import ProfileReport, RunResult
from mctk.status import Status


class CoverageLevel(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


class OverallVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class IssueFlag(str, Enum):
    COMPILE_ERROR = "compile_error"
    INTERNAL_ERROR = "internal_error"
    SPAWN_ERROR = "spawn_error"
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    WRONG_OUTPUT = "wrong_output"
    OUTPUT_TRUNCATED = "output_truncated"
    OUTPUT_MISMATCH_ACROSS_CONFIGS = "output_mismatch_across_configs"
    STDERR_MISMATCH_ACROSS_CONFIGS = "stderr_mismatch_across_configs"
    EXIT_MISMATCH_ACROSS_CONFIGS = "exit_mismatch_across_configs"
    INSUFFICIENT_COMPARISONS = "insufficient_comparisons"
    DUPLICATE_CASE_NAME = "duplicate_case_name"
    EMPTY_SUITE = "empty_suite"
    ORACLE_DISAGREEMENT = "oracle_disagreement"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    TOOLCHAIN_UNAVAILABLE = "toolchain_unavailable"
    UBSAN_FINDING = "ubsan_finding"


@dataclass
class Issue:
    flag: IssueFlag
    message: str
    source_path: str
    case_name: str | None = None
    configs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag": self.flag.value,
            "message": self.message,
            "source_path": self.source_path,
            "case_name": self.case_name,
            "configs": self.configs,
        }


def _profile_label(p: ProfileReport) -> str:
    return configuration_label(p)


def _run_executed(run: RunResult) -> bool:
    """Counts toward per-source release coverage (case actually completed)."""
    if run.skipped or run.timed_out or run.stdout_truncated or run.stderr_truncated:
        return False
    if run.status in (
        Status.SKIPPED,
        Status.COMPILE_ERROR,
        Status.DEADLINE_EXCEEDED,
        Status.SPAWN_ERROR,
        Status.TIMEOUT,
        Status.INTERNAL_ERROR,
    ):
        return False
    return True


def collect_profile_issues(p: ProfileReport) -> list[Issue]:
    issues: list[Issue] = []
    src = str(p.source_path)
    label = _profile_label(p)
    if p.config.build_kind != "release":
        return issues

    if p.compile.status == Status.COMPILE_ERROR:
        issues.append(
            Issue(IssueFlag.COMPILE_ERROR, "compilation failed", src, configs=[label])
        )
    elif p.compile.status == Status.SPAWN_ERROR:
        issues.append(
            Issue(IssueFlag.SPAWN_ERROR, "compilation spawn failed", src, configs=[label])
        )
    elif p.compile.status == Status.TIMEOUT:
        issues.append(
            Issue(IssueFlag.TIMEOUT, "compilation timed out", src, configs=[label])
        )
    elif p.compile.status == Status.INTERNAL_ERROR:
        issues.append(
            Issue(
                IssueFlag.INTERNAL_ERROR,
                "compilation internal error",
                src,
                configs=[label],
            )
        )
    elif p.compile.status == Status.DEADLINE_EXCEEDED:
        issues.append(
            Issue(
                IssueFlag.DEADLINE_EXCEEDED,
                "compilation skipped (suite deadline)",
                src,
                configs=[label],
            )
        )

    for run in p.runs:
        if run.stdout_truncated or run.stderr_truncated:
            issues.append(
                Issue(
                    IssueFlag.OUTPUT_TRUNCATED,
                    "captured output truncated; not eligible for complete comparison",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        if run.status == Status.SPAWN_ERROR:
            issues.append(
                Issue(
                    IssueFlag.SPAWN_ERROR,
                    "run spawn failed",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        elif run.status == Status.WRONG_OUTPUT:
            issues.append(
                Issue(
                    IssueFlag.WRONG_OUTPUT,
                    "output mismatch vs expected",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        elif run.status == Status.ORACLE_DISAGREEMENT:
            issues.append(
                Issue(
                    IssueFlag.ORACLE_DISAGREEMENT,
                    "output differs from Python oracle",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        elif run.status == Status.TIMEOUT:
            issues.append(
                Issue(
                    IssueFlag.TIMEOUT,
                    "run timed out",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        elif run.status == Status.RUNTIME_ERROR:
            issues.append(
                Issue(
                    IssueFlag.RUNTIME_ERROR,
                    f"run exited {run.exit_code}",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        elif run.status == Status.DEADLINE_EXCEEDED:
            issues.append(
                Issue(
                    IssueFlag.DEADLINE_EXCEEDED,
                    "run skipped (suite deadline)",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
        elif run.status == Status.INTERNAL_ERROR:
            issues.append(
                Issue(
                    IssueFlag.INTERNAL_ERROR,
                    "run internal error",
                    src,
                    case_name=run.case_name,
                    configs=[label],
                )
            )
    return issues


def _duplicate_case_names(group: list[ProfileReport]) -> list[str]:
    dupes: list[str] = []
    for p in group:
        seen: set[str] = set()
        for run in p.runs:
            if run.case_name in seen:
                dupes.append(run.case_name)
            seen.add(run.case_name)
    return sorted(set(dupes))


def _insufficient_single_config(group: list[ProfileReport]) -> bool:
    if len(group) != 1:
        return False
    profile = group[0]
    if profile.oracle_id:
        return False
    return True


def compare_across_configs(profiles: list[ProfileReport]) -> list[Issue]:
    release = [p for p in profiles if p.config.build_kind == "release"]
    by_source: dict[str, list[ProfileReport]] = {}
    for p in release:
        by_source.setdefault(str(p.source_path), []).append(p)

    issues: list[Issue] = []
    for src, group in by_source.items():
        for dup in _duplicate_case_names(group):
            issues.append(
                Issue(
                    IssueFlag.DUPLICATE_CASE_NAME,
                    f"duplicate case name {dup!r} hides per-case results",
                    src,
                    case_name=dup,
                    configs=[_profile_label(p) for p in group],
                )
            )
        if _insufficient_single_config(group):
            case_names = sorted({r.case_name for p in group for r in p.runs})
            for case_name in case_names:
                issues.append(
                    Issue(
                        IssueFlag.INSUFFICIENT_COMPARISONS,
                        "single release configuration without oracle cannot establish cross-config agreement",
                        src,
                        case_name=case_name,
                        configs=[_profile_label(group[0])],
                    )
                )
            continue
        if len(group) < 2:
            continue
        case_names = {r.case_name for p in group for r in p.runs}
        for case_name in sorted(case_names):
            eligible = cross_config_observations(group, case_name)
            labels = sorted(eligible.keys())
            if len(group) >= 2 and len(labels) < 2:
                issues.append(
                    Issue(
                        IssueFlag.INSUFFICIENT_COMPARISONS,
                        "fewer than two eligible configurations for cross-comparison",
                        src,
                        case_name=case_name,
                        configs=labels,
                    )
                )
                continue
            if len(labels) < 2:
                continue
            if stdout_mismatch(eligible, case_name):
                issues.append(
                    Issue(
                        IssueFlag.OUTPUT_MISMATCH_ACROSS_CONFIGS,
                        "release builds disagree on stdout bytes (CRLF-normalized)",
                        src,
                        case_name=case_name,
                        configs=labels,
                    )
                )
            if stderr_mismatch(eligible, case_name):
                issues.append(
                    Issue(
                        IssueFlag.STDERR_MISMATCH_ACROSS_CONFIGS,
                        "release builds disagree on stderr bytes (CRLF-normalized)",
                        src,
                        case_name=case_name,
                        configs=labels,
                    )
                )
            if exit_code_mismatch(eligible, case_name):
                issues.append(
                    Issue(
                        IssueFlag.EXIT_MISMATCH_ACROSS_CONFIGS,
                        "release builds disagree on exit codes",
                        src,
                        case_name=case_name,
                        configs=labels,
                    )
                )
    return issues


def compute_coverage(
    profiles: list[ProfileReport],
    expected_release_by_source: dict[str, int],
) -> CoverageLevel:
    release = [p for p in profiles if p.config.build_kind == "release"]
    by_source: dict[str, list[ProfileReport]] = {}
    for p in release:
        by_source.setdefault(str(p.source_path), []).append(p)

    for src, expected in expected_release_by_source.items():
        group = by_source.get(src, [])
        if len(group) < expected:
            return CoverageLevel.PARTIAL
        case_names = group[0].runs and [r.case_name for r in group[0].runs] or []
        for case_name in case_names:
            executed = 0
            for p in group:
                run = next((r for r in p.runs if r.case_name == case_name), None)
                if run and _run_executed(run):
                    executed += 1
            if executed < expected:
                return CoverageLevel.PARTIAL
    return CoverageLevel.FULL


def _requested_coverage(
    requested_release_by_source: dict[str, int],
    expected_release_by_source: dict[str, int],
    unfulfilled_requested: list[dict[str, str]],
) -> CoverageLevel:
    if unfulfilled_requested:
        return CoverageLevel.PARTIAL
    for src, requested in requested_release_by_source.items():
        fulfilled = expected_release_by_source.get(src, 0)
        if fulfilled < requested:
            return CoverageLevel.PARTIAL
    return CoverageLevel.FULL


def _dedupe_issues(issues: list[Issue]) -> list[Issue]:
    seen: set[tuple] = set()
    unique: list[Issue] = []
    for iss in issues:
        key = (iss.flag, iss.message, iss.source_path, iss.case_name, tuple(iss.configs))
        if key in seen:
            continue
        seen.add(key)
        unique.append(iss)
    return unique


def interpret_suite(
    profiles: list[ProfileReport],
    *,
    expected_release_by_source: dict[str, int],
    requested_release_by_source: dict[str, int] | None = None,
    unfulfilled_requested: list[dict[str, str]] | None = None,
    ubsan_issues: list[Issue] | None = None,
) -> dict[str, Any]:
    issues: list[Issue] = []
    if not profiles:
        issues.append(Issue(IssueFlag.EMPTY_SUITE, "no profiles to execute", ""))

    for p in profiles:
        issues.extend(collect_profile_issues(p))
    issues.extend(compare_across_configs(profiles))
    if ubsan_issues:
        issues.extend(ubsan_issues)

    unique = _dedupe_issues(issues)

    coverage = (
        CoverageLevel.PARTIAL
        if not profiles
        else compute_coverage(profiles, expected_release_by_source)
    )
    requested = requested_release_by_source or dict(expected_release_by_source)
    unfulfilled = list(unfulfilled_requested or [])
    requested_coverage = _requested_coverage(
        requested, expected_release_by_source, unfulfilled
    )

    blocking = {
        IssueFlag.COMPILE_ERROR,
        IssueFlag.RUNTIME_ERROR,
        IssueFlag.WRONG_OUTPUT,
        IssueFlag.INTERNAL_ERROR,
        IssueFlag.SPAWN_ERROR,
        IssueFlag.ORACLE_DISAGREEMENT,
        IssueFlag.OUTPUT_MISMATCH_ACROSS_CONFIGS,
        IssueFlag.STDERR_MISMATCH_ACROSS_CONFIGS,
        IssueFlag.EXIT_MISMATCH_ACROSS_CONFIGS,
        IssueFlag.OUTPUT_TRUNCATED,
        IssueFlag.EMPTY_SUITE,
        IssueFlag.UBSAN_FINDING,
        IssueFlag.DUPLICATE_CASE_NAME,
    }
    has_blocking = any(i.flag in blocking for i in unique)
    has_timeout = any(i.flag == IssueFlag.TIMEOUT for i in unique)
    has_insufficient = any(i.flag == IssueFlag.INSUFFICIENT_COMPARISONS for i in unique)

    if not profiles:
        verdict = OverallVerdict.FAIL
    elif has_blocking:
        verdict = OverallVerdict.FAIL
    elif has_insufficient or coverage == CoverageLevel.PARTIAL:
        verdict = OverallVerdict.INCONCLUSIVE
    elif has_timeout:
        verdict = OverallVerdict.FAIL
    elif unique:
        verdict = OverallVerdict.FAIL
    else:
        verdict = OverallVerdict.PASS

    return {
        "coverage": coverage.value,
        "coverage_executed_note": (
            "FULL when every fulfilled release configuration executed every shared case."
        ),
        "requested_coverage": requested_coverage.value,
        "requested_coverage_note": (
            "PARTIAL when any YAML compiler_configs entry was not fulfilled "
            "(including optional toolchains that were unavailable)."
        ),
        "unfulfilled_requested_configurations": unfulfilled,
        "overall_verdict": verdict.value,
        "pass_meaning": (
            "PASS means eligible release builds were mutually consistent on stdout bytes "
            "(CRLF-normalized), with stderr/exit differences tracked separately. "
            "Truncated, spawn-failed, or skipped runs cannot yield PASS."
        ),
        "issues": [i.to_dict() for i in unique],
        "interpretation_notes": (
            "Observations (per profile runs) are separate from issue flags and this verdict."
        ),
    }
