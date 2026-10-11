"""Bounded validation for suites and generated cases."""

from __future__ import annotations

MAX_GENERATED_CASES = 30
MAX_SOURCE_BYTES = 256_000
MAX_STDIN_BYTES = 64_000
MAX_SUITE_SOURCES = 32


def validate_case_count(count: int) -> int:
    if count <= 0:
        raise ValueError("case count must be positive")
    if count > MAX_GENERATED_CASES:
        raise ValueError(f"case count exceeds maximum ({MAX_GENERATED_CASES})")
    return count


def validate_source_bytes(data: bytes) -> None:
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError(f"source exceeds {MAX_SOURCE_BYTES} bytes")


def validate_stdin_bytes(data: bytes) -> None:
    if len(data) > MAX_STDIN_BYTES:
        raise ValueError(f"stdin exceeds {MAX_STDIN_BYTES} bytes")


def validate_unique_case_names(cases: tuple, *, context: str) -> None:
    seen: set[str] = set()
    for case in cases:
        name = getattr(case, "name", None)
        if name in seen:
            raise ValueError(f"duplicate case name {name!r} in {context}")
        seen.add(name)
