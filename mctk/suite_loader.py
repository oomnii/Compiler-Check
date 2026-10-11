"""Load suite definitions from YAML."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from mctk.inputgen import generate_cases
from mctk.limits import ResourceLimits
from mctk.models import BuildProfile, CompilerConfig, InputCase
from mctk.toolchain import discover_toolchains, resolve_toolchain
from mctk.validation import (
    MAX_SUITE_SOURCES,
    validate_case_count,
    validate_source_bytes,
    validate_unique_case_names,
)


@dataclass
class LoadedSuite:
    limits: ResourceLimits
    profiles: list[BuildProfile]
    expected_release_by_source: dict[str, int]
    requested_release_by_source: dict[str, int]
    unfulfilled_requested: list[dict[str, str]]
    enable_ubsan: bool
    skipped_toolchains: list[dict[str, str]]


def _read_stdin_field(raw: Any, suite_dir: Path) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict) and "file" in raw:
        p = Path(raw["file"])
        if not p.is_absolute():
            p = suite_dir / p
        return p.read_text(encoding="utf-8")
    return str(raw)


def _load_shared_cases(src_entry: dict, suite_dir: Path) -> tuple[InputCase, ...]:
    if "generate" in src_entry:
        gen = src_entry["generate"]
        cnt = validate_case_count(int(gen.get("count", 3)))
        return generate_cases(str(gen["template"]), int(gen["seed"]), cnt)
    cases: list[InputCase] = []
    for case in src_entry.get("cases") or []:
        cases.append(
            InputCase(
                name=str(case.get("name", "case")),
                stdin=_read_stdin_field(case.get("stdin"), suite_dir),
                expected_stdout=case.get("expected_stdout"),
                expected_stderr=case.get("expected_stderr"),
            )
        )
    return tuple(cases)


def load_suite(path: Path) -> LoadedSuite:
    suite_dir = path.parent
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("suite root must be a mapping")

    limits_raw = data.get("resource_limits") or {}
    limits = ResourceLimits(
        compile_timeout_sec=float(limits_raw.get("compile_timeout_sec", 30)),
        run_timeout_sec=float(limits_raw.get("run_timeout_sec", 5)),
        max_stdout_bytes=int(limits_raw.get("max_stdout_bytes", 1_048_576)),
        max_stderr_bytes=int(limits_raw.get("max_stderr_bytes", 1_048_576)),
        overall_deadline_sec=float(limits_raw.get("overall_deadline_sec", 600)),
        memory_limit_mb=limits_raw.get("memory_limit_mb"),
    )
    limits.validate()

    sources_raw = data.get("sources") or []
    if not sources_raw:
        raise ValueError("suite must include at least one source")
    if len(sources_raw) > MAX_SUITE_SOURCES:
        raise ValueError(f"suite exceeds {MAX_SUITE_SOURCES} sources")

    enable_ubsan = bool(data.get("ubsan", True))
    discovered = discover_toolchains()
    skipped: list[dict[str, str]] = []
    profiles: list[BuildProfile] = []
    expected_by_source: dict[str, int] = {}
    requested_by_source: dict[str, int] = {}
    unfulfilled: list[dict[str, str]] = []

    for src_entry in sources_raw:
        if "path" not in src_entry:
            raise ValueError("each source requires path")
        src_path = Path(src_entry["path"])
        if not src_path.is_absolute():
            src_path = (suite_dir / src_path).resolve()
        validate_source_bytes(src_path.read_bytes())

        shared_cases = _load_shared_cases(src_entry, suite_dir)
        if not shared_cases:
            raise ValueError(f"no cases for source {src_path}")
        validate_unique_case_names(shared_cases, context=str(src_path))

        oracle_id = src_entry.get("oracle")
        template_name = src_entry.get("template")
        if not template_name and "generate" in src_entry:
            template_name = str(src_entry["generate"]["template"])

        configs = src_entry.get("compiler_configs") or []
        if not configs:
            raise ValueError(f"compiler_configs required for {src_path}")

        src_key = str(src_path.resolve())
        requested_by_source[src_key] = len(configs)
        resolved_count = 0
        for cfg in configs:
            tc_name = str(cfg.get("toolchain", cfg.get("compiler", "g++")))
            optional = bool(cfg.get("optional", False))
            opt = str(cfg.get("optimization", "O0"))
            tc = resolve_toolchain(tc_name, discovered)
            if tc is None:
                msg = f"toolchain not found: {tc_name}"
                if optional:
                    skipped.append({"toolchain": tc_name, "reason": msg})
                    unfulfilled.append(
                        {
                            "source_path": src_key,
                            "toolchain": tc_name,
                            "optimization": opt,
                            "optional": "true",
                            "reason": msg,
                        }
                    )
                    continue
                raise ValueError(msg)

            flags = tuple(str(f) for f in (cfg.get("flags") or ()))
            config = CompilerConfig.from_toolchain(tc, opt, flags=flags, build_kind="release")
            profiles.append(
                BuildProfile(
                    source_path=src_path,
                    config=config,
                    cases=shared_cases,
                    oracle_id=str(oracle_id) if oracle_id else None,
                    template_name=str(template_name) if template_name else None,
                )
            )
            resolved_count += 1

        if resolved_count == 0:
            raise ValueError(f"no usable toolchains for source {src_path}")
        expected_by_source[src_key] = resolved_count

    return LoadedSuite(
        limits=limits,
        profiles=profiles,
        expected_release_by_source=expected_by_source,
        requested_release_by_source=requested_by_source,
        unfulfilled_requested=unfulfilled,
        enable_ubsan=enable_ubsan,
        skipped_toolchains=skipped,
    )
