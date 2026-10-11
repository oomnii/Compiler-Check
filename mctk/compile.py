"""Compile-once per suite invocation (session cache only, no disk reuse)."""

from __future__ import annotations

import hashlib
import os
from copy import copy
from pathlib import Path
from typing import MutableMapping

from mctk.deadline import Deadline
from mctk.limits import ResourceLimits
from mctk.models import CompileResult, CompilerConfig
from mctk.status import Status
from mctk.subprocess_util import run_captured
from mctk.toolchain import gcc_like_opt_flag
from mctk.ubsan import ubsan_compile_flags, ubsan_link_flags


def source_digest(source_path: Path, source_text: str) -> str:
    h = hashlib.sha256()
    h.update(source_text.encode("utf-8"))
    return h.hexdigest()[:16]


def build_output_path(work_dir: Path, source_path: Path, digest: str, config: CompilerConfig) -> Path:
    src_tag = hashlib.sha256(str(source_path.resolve()).encode("utf-8")).hexdigest()[:10]
    sub = work_dir / digest / src_tag / config.configuration_id()
    sub.mkdir(parents=True, exist_ok=True)
    name = "a.exe" if os.name == "nt" else "a.out"
    return sub / name


def build_compile_command(
    source_path: Path,
    out_path: Path,
    config: CompilerConfig,
) -> list[str]:
    from mctk.toolchain import Toolchain, CompilerFamily

    opt_flag = gcc_like_opt_flag(config.optimization)
    cmd = [
        config.compiler_executable,
        *config.language_std,
        opt_flag,
        *config.flags,
    ]
    if config.build_kind == "ubsan_diagnostic":
        tc = Toolchain(
            id=config.toolchain_id,
            executable=config.compiler_executable,
            family=CompilerFamily(config.family),
            version_line=config.version_line,
            cpp17_flags=config.language_std,
        )
        cmd.extend(ubsan_compile_flags(tc))
    cmd.extend([str(source_path), "-o", str(out_path)])
    if config.build_kind == "ubsan_diagnostic":
        tc = Toolchain(
            id=config.toolchain_id,
            executable=config.compiler_executable,
            family=CompilerFamily(config.family),
            version_line=config.version_line,
            cpp17_flags=config.language_std,
        )
        cmd.extend(ubsan_link_flags(tc))
    return cmd


def _session_key(source_path: Path, digest: str, config: CompilerConfig) -> str:
    """Include resolved source path so identical text in different dirs never shares binaries."""
    return f"{source_path.resolve()}:{digest}:{config.configuration_id()}"


def compile_source(
    source_path: Path,
    source_text: str,
    config: CompilerConfig,
    limits: ResourceLimits,
    work_dir: Path,
    deadline: Deadline | None = None,
    *,
    session_cache: MutableMapping[str, CompileResult] | None = None,
) -> CompileResult:
    digest = source_digest(source_path, source_text)
    out_path = build_output_path(work_dir, source_path, digest, config)
    cmd = build_compile_command(source_path, out_path, config)
    skey = _session_key(source_path, digest, config)

    if session_cache is not None and skey in session_cache:
        cached = copy(session_cache[skey])
        if cached.binary_path and Path(cached.binary_path).resolve() == out_path.resolve():
            cached.cache_hit = True
            cached.duration_sec = None
            return cached

    if deadline and deadline.expired():
        return CompileResult(
            status=Status.DEADLINE_EXCEEDED,
            binary_path=None,
            stdout="",
            stderr="",
            command=cmd,
        )

    timeout = limits.compile_timeout_sec
    deadline_mono = None
    if deadline:
        timeout = deadline.cap_timeout(timeout)
        deadline_mono = deadline.started_at + deadline.overall_sec
        if timeout <= 0:
            return CompileResult(
                status=Status.DEADLINE_EXCEEDED,
                binary_path=None,
                stdout="",
                stderr="",
                command=cmd,
            )

    captured = run_captured(
        cmd,
        timeout_sec=timeout,
        max_stdout_bytes=limits.max_stdout_bytes,
        max_stderr_bytes=limits.max_stderr_bytes,
        cwd=str(source_path.parent),
        deadline_mono=deadline_mono,
    )

    if captured.spawn_failed:
        result = CompileResult(
            status=Status.SPAWN_ERROR,
            binary_path=None,
            stdout=captured.stdout,
            stderr=captured.stderr,
            command=cmd,
            stdout_bytes=captured.stdout_bytes,
            stderr_bytes=captured.stderr_bytes,
            stdout_truncated=captured.stdout_truncated,
            stderr_truncated=captured.stderr_truncated,
            duration_sec=captured.duration_sec,
            cache_hit=False,
        )
        if session_cache is not None:
            session_cache[skey] = copy(result)
        return result

    if captured.timed_out:
        result = CompileResult(
            status=Status.TIMEOUT,
            binary_path=None,
            stdout=captured.stdout,
            stderr=captured.stderr,
            command=cmd,
            stdout_bytes=captured.stdout_bytes,
            stderr_bytes=captured.stderr_bytes,
            stdout_truncated=captured.stdout_truncated,
            stderr_truncated=captured.stderr_truncated,
            timed_out=True,
            process_reaped=captured.process_reaped,
            duration_sec=captured.duration_sec,
            cache_hit=False,
        )
        if session_cache is not None:
            session_cache[skey] = copy(result)
        return result

    if captured.returncode != 0 or not out_path.is_file():
        result = CompileResult(
            status=Status.COMPILE_ERROR,
            binary_path=None,
            stdout=captured.stdout,
            stderr=captured.stderr,
            command=cmd,
            stdout_bytes=captured.stdout_bytes,
            stderr_bytes=captured.stderr_bytes,
            stdout_truncated=captured.stdout_truncated,
            stderr_truncated=captured.stderr_truncated,
            process_reaped=captured.process_reaped,
            duration_sec=captured.duration_sec,
            cache_hit=False,
        )
        if session_cache is not None:
            session_cache[skey] = copy(result)
        return result

    result = CompileResult(
        status=Status.OK,
        binary_path=out_path,
        stdout=captured.stdout,
        stderr=captured.stderr,
        command=cmd,
        stdout_bytes=captured.stdout_bytes,
        stderr_bytes=captured.stderr_bytes,
        stdout_truncated=captured.stdout_truncated,
        stderr_truncated=captured.stderr_truncated,
        process_reaped=captured.process_reaped,
        duration_sec=captured.duration_sec,
        cache_hit=False,
    )
    if session_cache is not None:
        session_cache[skey] = copy(result)
    return result
