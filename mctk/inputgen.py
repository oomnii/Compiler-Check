"""Deterministic input generation for template suites."""

from __future__ import annotations

import random

from mctk.models import InputCase
from mctk.validation import validate_case_count


def _boundary_cases(template: str) -> list[InputCase]:
    if template == "arithmetic":
        return [
            InputCase(name="boundary_zero", stdin="0 0\n"),
            InputCase(name="boundary_negative", stdin="-1 1\n"),
        ]
    if template == "sort_array":
        return [
            InputCase(name="boundary_empty", stdin="0\n"),
            InputCase(name="boundary_one", stdin="1\n42\n"),
        ]
    if template == "string":
        return [
            InputCase(name="boundary_empty", stdin="\n"),
            InputCase(name="boundary_single", stdin="a\n"),
        ]
    return []


def generate_cases(template: str, seed: int, count: int) -> tuple[InputCase, ...]:
    count = validate_case_count(count)
    rng = random.Random(seed)
    boundaries = _boundary_cases(template)
    remaining = max(0, count - len(boundaries))
    cases: list[InputCase] = list(boundaries)

    if template == "arithmetic":
        for i in range(remaining):
            a, b = rng.randint(-1000, 1000), rng.randint(-1000, 1000)
            cases.append(InputCase(name=f"arith_{i}", stdin=f"{a} {b}\n"))
        return tuple(cases[:count])

    if template == "sort_array":
        for i in range(remaining):
            n = rng.randint(0, 32)
            nums = [rng.randint(-1000, 1000) for _ in range(n)]
            stdin = f"{n}\n" + (" ".join(map(str, nums)) + "\n" if n else "")
            cases.append(InputCase(name=f"sort_{i}", stdin=stdin))
        return tuple(cases[:count])

    if template == "string":
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
        for i in range(remaining):
            length = rng.randint(0, 40)
            s = "".join(rng.choice(alphabet) for _ in range(length))
            cases.append(InputCase(name=f"str_{i}", stdin=s + "\n"))
        return tuple(cases[:count])

    raise ValueError(f"unknown template for input generation: {template}")
