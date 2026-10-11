"""Validate dashboard API payloads before starting verification."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from mctk.validation import MAX_GENERATED_CASES, validate_case_count, validate_source_bytes, validate_stdin_bytes

ALLOWED_MODES = frozenset({"example", "custom", "generated"})
ALLOWED_OPTIMIZATIONS = frozenset({"O0", "O2"})


def validate_origin(origin: str | None, host: str) -> None:
    if not origin:
        return
    parsed = urlparse(origin)
    if parsed.scheme != "http":
        raise ValueError("Origin must use http on localhost")
    if parsed.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Origin host not allowed")
    if parsed.path not in ("", "/"):
        raise ValueError("Origin path must be empty")
    if parsed.query or parsed.fragment:
        raise ValueError("Origin must not include query or fragment")
    req_host = host.split(":")[0].lower()
    if parsed.hostname == "127.0.0.1" and req_host not in ("127.0.0.1",):
        raise ValueError("Origin does not match request host")
    if parsed.hostname == "localhost" and req_host not in ("localhost",):
        raise ValueError("Origin does not match request host")
    if parsed.port is not None:
        req_port = host.split(":")[1] if ":" in host else "80"
        if str(parsed.port) != req_port:
            raise ValueError("Origin port must match request port")


def _as_str_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} entries must be non-empty strings")
        out.append(item.strip())
    return out


def validate_run_payload(body: dict[str, Any], *, known_toolchains: set[str]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    mode = str(body.get("mode", "example"))
    if mode not in ALLOWED_MODES:
        raise ValueError(f"Unknown mode: {mode}")

    normalized: dict[str, Any] = {"mode": mode}

    if mode == "example":
        normalized["suite_id"] = str(body.get("suite_id", "quick"))
        normalized["enable_ubsan"] = bool(body.get("enable_ubsan", True))
        return normalized

    toolchains = _as_str_list(body.get("toolchains"), "toolchains")
    optimizations = _as_str_list(body.get("optimizations"), "optimizations")
    if not toolchains:
        raise ValueError("Select at least one compiler")
    if not optimizations:
        raise ValueError("Select at least one optimization level")
    for opt in optimizations:
        if opt not in ALLOWED_OPTIMIZATIONS:
            raise ValueError(f"Unsupported optimization: {opt}")
    for tid in toolchains:
        if tid not in known_toolchains:
            raise ValueError(f"Unknown or unavailable toolchain: {tid}")

    normalized["toolchains"] = toolchains
    normalized["optimizations"] = optimizations
    normalized["enable_ubsan"] = bool(body.get("enable_ubsan", True))

    if mode == "custom":
        source = body.get("source_text")
        stdin = body.get("stdin_text")
        if not isinstance(source, str):
            raise ValueError("source_text must be a string")
        if not isinstance(stdin, str):
            raise ValueError("stdin_text must be a string")
        validate_source_bytes(source.encode("utf-8"))
        validate_stdin_bytes(stdin.encode("utf-8"))
        normalized["source_text"] = source
        normalized["stdin_text"] = stdin
        return normalized

    if mode == "generated":
        normalized["program_id"] = str(body.get("program_id", "arithmetic"))
        try:
            seed = int(body.get("seed", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("seed must be an integer") from exc
        try:
            count = validate_case_count(int(body.get("case_count", 4)))
        except (TypeError, ValueError) as exc:
            raise ValueError("case_count must be a positive integer") from exc
        if count > MAX_GENERATED_CASES:
            raise ValueError(f"case_count exceeds {MAX_GENERATED_CASES}")
        normalized["seed"] = seed
        normalized["case_count"] = count
        return normalized

    raise ValueError(f"Unknown mode: {mode}")
