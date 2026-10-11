"""Build LoadedSuite instances from dashboard form/API requests."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mctk.inputgen import generate_cases
from mctk.limits import ResourceLimits
from mctk.models import BuildProfile, CompilerConfig, InputCase
from mctk.suite_loader import LoadedSuite, load_suite
from mctk.toolchain import discover_toolchains, resolve_toolchain
from mctk.validation import validate_case_count, validate_source_bytes, validate_stdin_bytes

DEFAULT_LIMITS = ResourceLimits(
    compile_timeout_sec=30.0,
    run_timeout_sec=5.0,
    max_stdout_bytes=65536,
    max_stderr_bytes=65536,
    overall_deadline_sec=300.0,
    memory_limit_mb=512,
)

GENERATED_PROGRAMS: dict[str, dict[str, str]] = {
    "arithmetic": {
        "path": "programs/arithmetic.cpp",
        "oracle": "arithmetic_sum",
        "template": "arithmetic",
        "label": "Arithmetic sum",
        "description": "Reads two integers; oracle checks a+b.",
    },
    "sort_array": {
        "path": "programs/sort.cpp",
        "oracle": "sort_array",
        "template": "sort_array",
        "label": "Sort array",
        "description": "Sorts n integers; includes empty-array boundary.",
    },
    "string": {
        "path": "programs/string_reverse.cpp",
        "oracle": "string_reverse",
        "template": "string",
        "label": "String reverse",
        "description": "Reverses a line of text.",
    },
}

EXAMPLE_SUITES: dict[str, dict[str, str]] = {
    "quick": {
        "label": "Add (fixed cases)",
        "description": (
            "Three shared stdin cases on add.cpp with arithmetic oracle; "
            "g++ O0/O2 plus optional clang++ O2 when installed."
        ),
        "file": "suite.yaml",
    },
    "generated": {
        "label": "Generated multi-program suite",
        "description": (
            "Three C++ templates with deterministic generated inputs "
            "(seed + count); g++ O0/O2 on each source."
        ),
        "file": "generated_suite.yaml",
    },
    "failure": {
        "label": "Compile failure demo",
        "description": "Intentionally invalid C++ to exercise compile_error reporting.",
        "file": "failure_suite.yaml",
    },
}


@dataclass
class RunPlan:
    """Human-readable summary of the next verification run."""

    mode: str
    title: str
    detail: str
    source_preview: str
    config_count: int
    case_count: int
    matrix_label: str


def example_suite_paths(project_root: Path) -> dict[str, Path]:
    examples = (project_root / "examples").resolve()
    out: dict[str, Path] = {}
    for sid, meta in EXAMPLE_SUITES.items():
        p = (examples / meta["file"]).resolve()
        if p.is_file():
            out[sid] = p
    return out


def preview_example_source(project_root: Path, suite_id: str) -> str:
    paths = example_suite_paths(project_root)
    if suite_id not in paths:
        return ""
    loaded = load_suite(paths[suite_id])
    if not loaded.profiles:
        return ""
    return loaded.profiles[0].source_path.read_text(encoding="utf-8")


def _build_profiles_for_source(
    src_path: Path,
    source_text: str,
    cases: tuple[InputCase, ...],
    *,
    oracle_id: str | None,
    template_name: str | None,
    toolchain_ids: list[str],
    optimizations: list[str],
    discovered: list,
) -> tuple[list[BuildProfile], list[dict[str, str]], int, int]:
    validate_source_bytes(source_text.encode("utf-8"))
    profiles: list[BuildProfile] = []
    skipped: list[dict[str, str]] = []
    requested = 0
    resolved = 0
    src_key = str(src_path.resolve())

    for tid in toolchain_ids:
        for opt in optimizations:
            requested += 1
            tc = resolve_toolchain(tid, discovered)
            if tc is None:
                skipped.append({"toolchain": tid, "reason": f"toolchain not found: {tid}"})
                continue
            config = CompilerConfig.from_toolchain(tc, opt, flags=("-Wall",), build_kind="release")
            profiles.append(
                BuildProfile(
                    source_path=src_path,
                    config=config,
                    cases=cases,
                    oracle_id=oracle_id,
                    template_name=template_name,
                )
            )
            resolved += 1

    if resolved == 0:
        raise ValueError("No usable compiler configurations selected.")
    return profiles, skipped, requested, resolved


def build_from_example(
    project_root: Path,
    suite_id: str,
    *,
    enable_ubsan: bool | None = None,
) -> LoadedSuite:
    paths = example_suite_paths(project_root)
    if suite_id not in paths:
        raise ValueError("Unknown example suite.")
    loaded = load_suite(paths[suite_id])
    if enable_ubsan is None:
        return loaded
    return replace(loaded, enable_ubsan=enable_ubsan)


def build_from_custom(
    project_root: Path,
    *,
    source_text: str,
    stdin_text: str,
    toolchain_ids: list[str],
    optimizations: list[str],
    enable_ubsan: bool,
    work_dir: Path,
) -> LoadedSuite:
    validate_stdin_bytes(stdin_text.encode("utf-8"))
    src_dir = work_dir / "custom_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    src_path = (src_dir / "custom.cpp").resolve()
    src_path.write_text(source_text, encoding="utf-8")

    cases = (InputCase(name="custom", stdin=stdin_text),)
    discovered = discover_toolchains(smoke_cache_dir=project_root / ".dashboard_runs" / "_smoke")
    profiles, skipped, requested, resolved = _build_profiles_for_source(
        src_path,
        source_text,
        cases,
        oracle_id=None,
        template_name=None,
        toolchain_ids=toolchain_ids,
        optimizations=optimizations,
        discovered=discovered,
    )
    src_key = str(src_path)
    return LoadedSuite(
        limits=DEFAULT_LIMITS,
        profiles=profiles,
        expected_release_by_source={src_key: resolved},
        requested_release_by_source={src_key: requested},
        unfulfilled_requested=[
            {
                "source_path": src_key,
                "toolchain": s["toolchain"],
                "optimization": "—",
                "reason": s["reason"],
            }
            for s in skipped
        ],
        enable_ubsan=enable_ubsan,
        skipped_toolchains=skipped,
    )


def build_from_generated(
    project_root: Path,
    *,
    program_id: str,
    seed: int,
    case_count: int,
    toolchain_ids: list[str],
    optimizations: list[str],
    enable_ubsan: bool,
) -> LoadedSuite:
    if program_id not in GENERATED_PROGRAMS:
        raise ValueError("Unknown generated program template.")
    meta = GENERATED_PROGRAMS[program_id]
    examples = (project_root / "examples").resolve()
    src_path = (examples / meta["path"]).resolve()
    if not src_path.is_file():
        raise ValueError(f"Missing example source: {meta['path']}")

    count = validate_case_count(case_count)
    cases = generate_cases(meta["template"], int(seed), count)
    discovered = discover_toolchains(smoke_cache_dir=project_root / ".dashboard_runs" / "_smoke")
    profiles, skipped, requested, resolved = _build_profiles_for_source(
        src_path,
        src_path.read_text(encoding="utf-8"),
        cases,
        oracle_id=meta["oracle"],
        template_name=meta["template"],
        toolchain_ids=toolchain_ids,
        optimizations=optimizations,
        discovered=discovered,
    )
    src_key = str(src_path)
    return LoadedSuite(
        limits=DEFAULT_LIMITS,
        profiles=profiles,
        expected_release_by_source={src_key: resolved},
        requested_release_by_source={src_key: requested},
        unfulfilled_requested=[
            {
                "source_path": src_key,
                "toolchain": s["toolchain"],
                "optimization": "—",
                "reason": s["reason"],
            }
            for s in skipped
        ],
        enable_ubsan=enable_ubsan,
        skipped_toolchains=skipped,
    )


def plan_run(payload: dict[str, Any], project_root: Path) -> RunPlan:
    mode = str(payload.get("mode", "example"))
    if mode == "example":
        sid = str(payload.get("suite_id", "quick"))
        meta = EXAMPLE_SUITES.get(sid, {"label": sid, "description": ""})
        preview = preview_example_source(project_root, sid)
        try:
            loaded = build_from_example(project_root, sid)
        except ValueError:
            loaded = None
        cfg = len(loaded.profiles) if loaded else 0
        cases = len(loaded.profiles[0].cases) if loaded and loaded.profiles else 0
        if loaded and sid == "generated":
            sources = len({str(p.source_path) for p in loaded.profiles})
            matrix = (
                f"{cfg} release configs across {sources} sources "
                f"({cases} shared cases per source, not across sources)"
            )
        else:
            matrix = f"{cfg} configurations × {cases} shared cases"
        return RunPlan(
            mode=mode,
            title=meta["label"],
            detail=meta["description"],
            source_preview=preview,
            config_count=cfg,
            case_count=cases,
            matrix_label=matrix,
        )
    if mode == "custom":
        src = str(payload.get("source_text", ""))
        stdin = str(payload.get("stdin_text", ""))
        tids = payload.get("toolchains") or ["g++"]
        opts = payload.get("optimizations") or ["O0", "O2"]
        cfg = len(tids) * len(opts)
        return RunPlan(
            mode=mode,
            title="Custom C++17 snippet",
            detail="Single shared stdin case; cross-config stdout comparison (no oracle).",
            source_preview=src,
            config_count=cfg,
            case_count=1,
            matrix_label=f"{cfg} configurations × 1 shared case",
        )
    if mode == "generated":
        pid = str(payload.get("program_id", "arithmetic"))
        meta = GENERATED_PROGRAMS.get(pid, {})
        count = int(payload.get("case_count", 4))
        tids = payload.get("toolchains") or ["g++"]
        opts = payload.get("optimizations") or ["O0", "O2"]
        cfg = len(tids) * len(opts)
        examples = (project_root / "examples").resolve()
        preview = ""
        p = examples / meta.get("path", "")
        if p.is_file():
            preview = p.read_text(encoding="utf-8")
        return RunPlan(
            mode=mode,
            title=meta.get("label", pid),
            detail=(
                f"Template {meta.get('template')}, seed {payload.get('seed', 0)}, "
                f"{count} generated cases (includes deterministic boundaries)."
            ),
            source_preview=preview,
            config_count=cfg,
            case_count=count,
            matrix_label=f"{cfg} configurations × {count} shared cases",
        )
    raise ValueError(f"Unknown mode: {mode}")


def build_loaded_suite(
    payload: dict[str, Any],
    project_root: Path,
    work_dir: Path,
) -> LoadedSuite:
    mode = str(payload.get("mode", "example"))
    enable_ubsan = bool(payload.get("enable_ubsan", True))
    toolchain_ids = [str(t) for t in (payload.get("toolchains") or []) if t]
    optimizations = [str(o) for o in (payload.get("optimizations") or []) if o]
    if not toolchain_ids:
        toolchain_ids = ["g++"]
    if not optimizations:
        optimizations = ["O0", "O2"]

    if mode == "example":
        return build_from_example(
            project_root,
            str(payload.get("suite_id", "quick")),
            enable_ubsan=enable_ubsan,
        )
    if mode == "custom":
        return build_from_custom(
            project_root,
            source_text=str(payload.get("source_text", "")),
            stdin_text=str(payload.get("stdin_text", "")),
            toolchain_ids=toolchain_ids,
            optimizations=optimizations,
            enable_ubsan=enable_ubsan,
            work_dir=work_dir,
        )
    if mode == "generated":
        return build_from_generated(
            project_root,
            program_id=str(payload.get("program_id", "arithmetic")),
            seed=int(payload.get("seed", 20260101)),
            case_count=int(payload.get("case_count", 4)),
            toolchain_ids=toolchain_ids,
            optimizations=optimizations,
            enable_ubsan=enable_ubsan,
        )
    raise ValueError(f"Unknown mode: {mode}")
