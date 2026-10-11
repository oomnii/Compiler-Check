"""Independent Python reference oracles for stdout verification."""

from __future__ import annotations

from typing import Callable

OracleFn = Callable[[str], str]

ORACLE_IDS = ("arithmetic_sum", "sort_array", "string_reverse")


def oracle_arithmetic_sum(stdin: str) -> str:
    parts = stdin.split()
    if len(parts) < 2:
        raise ValueError("arithmetic_sum expects two integers on stdin")
    return f"{int(parts[0]) + int(parts[1])}\n"


def oracle_sort_array(stdin: str) -> str:
    lines = [ln for ln in stdin.strip().split("\n") if ln.strip()]
    if not lines:
        raise ValueError("sort_array expects n then n integers")
    n = int(lines[0].strip())
    if n == 0:
        return "\n"
    nums = list(map(int, lines[1].split()))
    if len(nums) != n:
        raise ValueError("sort_array length mismatch")
    nums.sort()
    return " ".join(map(str, nums)) + "\n"


def oracle_string_reverse(stdin: str) -> str:
    return stdin.strip()[::-1] + "\n"


_REGISTRY: dict[str, OracleFn] = {
    "arithmetic_sum": oracle_arithmetic_sum,
    "sort_array": oracle_sort_array,
    "string_reverse": oracle_string_reverse,
}


def get_oracle(oracle_id: str) -> OracleFn:
    if oracle_id not in _REGISTRY:
        raise KeyError(f"unknown oracle: {oracle_id}")
    return _REGISTRY[oracle_id]
