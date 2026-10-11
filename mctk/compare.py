"""Byte-level cross-configuration comparison (stdout/stderr/exit)."""

from __future__ import annotations

from mctk.bytes_util import normalize_bytes_for_compare
from mctk.models import ProfileReport, RunResult
from mctk.status import Status


def configuration_label(p: ProfileReport) -> str:
    return p.config.configuration_id()


def run_eligible_for_behavior_compare(run: RunResult) -> bool:
    if run.skipped:
        return False
    if run.timed_out or run.stdout_truncated or run.stderr_truncated:
        return False
    if run.status not in (
        Status.OK,
        Status.RUNTIME_ERROR,
        Status.ORACLE_DISAGREEMENT,
        Status.WRONG_OUTPUT,
    ):
        return False
    if run.exit_code is None:
        return False
    return True


def normalized_stdout_bytes(run: RunResult) -> bytes:
    return normalize_bytes_for_compare(run.stdout_bytes)


def normalized_stderr_bytes(run: RunResult) -> bytes:
    return normalize_bytes_for_compare(run.stderr_bytes)


def cross_config_observations(
    group: list[ProfileReport],
    case_name: str,
) -> dict[str, ProfileReport]:
    eligible: dict[str, ProfileReport] = {}
    for p in group:
        matches = [r for r in p.runs if r.case_name == case_name]
        if len(matches) != 1:
            continue
        run = matches[0]
        if not run_eligible_for_behavior_compare(run):
            continue
        label = configuration_label(p)
        if label in eligible:
            continue
        eligible[label] = p
    return eligible


def stdout_mismatch(eligible: dict[str, ProfileReport], case_name: str) -> bool:
    values: list[bytes] = []
    for p in eligible.values():
        run = next(r for r in p.runs if r.case_name == case_name)
        values.append(normalized_stdout_bytes(run))
    return len(values) >= 2 and len(set(values)) > 1


def stderr_mismatch(eligible: dict[str, ProfileReport], case_name: str) -> bool:
    values: list[bytes] = []
    for p in eligible.values():
        run = next(r for r in p.runs if r.case_name == case_name)
        values.append(normalized_stderr_bytes(run))
    return len(values) >= 2 and len(set(values)) > 1


def exit_code_mismatch(eligible: dict[str, ProfileReport], case_name: str) -> bool:
    codes: list[int] = []
    for p in eligible.values():
        run = next(r for r in p.runs if r.case_name == case_name)
        assert run.exit_code is not None
        codes.append(run.exit_code)
    return len(codes) >= 2 and len(set(codes)) > 1
