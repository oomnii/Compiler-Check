"""Orchestrate compile-once / run-many, UBSan diagnostics, and interpretation."""

from __future__ import annotations

from pathlib import Path

from mctk.compile import compile_source
from mctk.deadline import Deadline
from mctk.interpretation import Issue, IssueFlag, interpret_suite
from mctk.limits import ResourceLimits
from mctk.models import BuildProfile, CompilerConfig, ProfileReport, SuiteReport
from mctk.oracles import get_oracle
from mctk.runner import run_case, skipped_run
from mctk.status import Status
from mctk.toolchain import discover_toolchains
from mctk.ubsan import finding_from_run, probe_ubsan


def _oracle_fn(profile: BuildProfile):
    if not profile.oracle_id:
        return None
    return get_oracle(profile.oracle_id)


def execute_profile(
    profile: BuildProfile,
    limits: ResourceLimits,
    work_dir: Path,
    deadline: Deadline | None = None,
    *,
    session_cache: dict | None = None,
) -> ProfileReport:
    source_text = profile.source_path.read_text(encoding="utf-8")
    compile_result = compile_source(
        profile.source_path,
        source_text,
        profile.config,
        limits,
        work_dir,
        deadline,
        session_cache=session_cache,
    )

    oracle = _oracle_fn(profile)
    runs = []
    if compile_result.status != Status.OK or compile_result.binary_path is None:
        for case in profile.cases:
            runs.append(skipped_run(case, compile_result.status))
    else:
        assert compile_result.binary_path is not None
        for case in profile.cases:
            runs.append(
                run_case(
                    compile_result.binary_path,
                    case,
                    limits,
                    deadline,
                    oracle_fn=oracle,
                )
            )

    return ProfileReport(
        source_path=profile.source_path,
        source_text=source_text,
        config=profile.config,
        compile=compile_result,
        runs=runs,
        oracle_id=profile.oracle_id,
        template_name=profile.template_name,
    )


def _ubsan_profiles_for_release(
    release_profiles: list[BuildProfile],
    supported_ids: set[str],
) -> list[BuildProfile]:
    extra: list[BuildProfile] = []
    seen: set[tuple] = set()
    for p in release_profiles:
        if p.config.toolchain_id not in supported_ids:
            continue
        key = (p.source_path, p.config.toolchain_id, p.config.optimization)
        if key in seen:
            continue
        seen.add(key)
        ubsan_cfg = CompilerConfig(
            toolchain_id=p.config.toolchain_id,
            compiler_executable=p.config.compiler_executable,
            family=p.config.family,
            version_line=p.config.version_line,
            optimization=p.config.optimization,
            flags=p.config.flags,
            build_kind="ubsan_diagnostic",
            language_std=p.config.language_std,
        )
        extra.append(
            BuildProfile(
                source_path=p.source_path,
                config=ubsan_cfg,
                cases=p.cases,
                oracle_id=p.oracle_id,
                template_name=p.template_name,
            )
        )
    return extra


def execute_suite(
    profiles: list[BuildProfile],
    limits: ResourceLimits,
    work_dir: Path | None = None,
    *,
    cache_dir: Path | None = None,
    suite_path: Path | None = None,
    expected_release_by_source: dict[str, int] | None = None,
    requested_release_by_source: dict[str, int] | None = None,
    unfulfilled_requested: list[dict[str, str]] | None = None,
    enable_ubsan: bool = True,
    skipped_toolchains: list[dict[str, str]] | None = None,
) -> SuiteReport:
    limits.validate()
    wd = work_dir or cache_dir
    if wd is None:
        raise ValueError("work_dir (or cache_dir) is required")
    wd.mkdir(parents=True, exist_ok=True)
    deadline = Deadline.start(limits.overall_deadline_sec)
    session_cache: dict = {}
    toolchains = discover_toolchains(smoke_cache_dir=wd / "_smoke")

    release_profiles = [p for p in profiles if p.config.build_kind == "release"]
    report = SuiteReport(
        resource_limits=limits,
        toolchains=toolchains,
        suite_path=suite_path,
        expected_release_by_source=expected_release_by_source or {},
        requested_release_by_source=requested_release_by_source or {},
        skipped_toolchains=list(skipped_toolchains or []),
        unfulfilled_requested=list(unfulfilled_requested or []),
    )

    ubsan_supported: set[str] = set()
    if enable_ubsan:
        for tc in toolchains:
            probe = probe_ubsan(tc, limits, wd)
            report.ubsan_probe.append(probe)
            if probe.supported:
                ubsan_supported.add(tc.id)

    for profile in release_profiles:
        report.profiles.append(
            execute_profile(
                profile, limits, wd, deadline, session_cache=session_cache
            )
        )

    ubsan_issues: list[Issue] = []
    if enable_ubsan and ubsan_supported:
        for uprof in _ubsan_profiles_for_release(release_profiles, ubsan_supported):
            preport = execute_profile(
                uprof, limits, wd, deadline, session_cache=session_cache
            )
            report.profiles.append(preport)
            if preport.compile.status != Status.OK:
                ubsan_issues.append(
                    Issue(
                        IssueFlag.COMPILE_ERROR,
                        f"UBSan diagnostic build failed ({preport.compile.status.label})",
                        str(preport.source_path),
                        configs=[
                            f"{preport.config.toolchain_id}_{preport.config.optimization}_ubsan"
                        ],
                    )
                )
                continue
            for run in preport.runs:
                finding = finding_from_run(
                    source_path=str(preport.source_path),
                    toolchain_id=preport.config.toolchain_id,
                    optimization=preport.config.optimization,
                    case_name=run.case_name,
                    stdin=run.stdin,
                    stderr=run.stderr,
                    stdout=run.stdout,
                )
                if finding:
                    report.ubsan_findings.append(finding)
                    ubsan_issues.append(
                        Issue(
                            IssueFlag.UBSAN_FINDING,
                            finding.message,
                            str(preport.source_path),
                            case_name=run.case_name,
                            configs=[
                                f"{preport.config.toolchain_id}_{preport.config.optimization}_ubsan"
                            ],
                        )
                    )

    report.interpretation = interpret_suite(
        report.profiles,
        expected_release_by_source=report.expected_release_by_source,
        requested_release_by_source=report.requested_release_by_source,
        unfulfilled_requested=report.unfulfilled_requested,
        ubsan_issues=ubsan_issues,
    )
    return report
