"""Resource limits applied to compile and run steps."""

from __future__ import annotations

import math
from dataclasses import dataclass


MEMORY_LIMIT_ENFORCEMENT = "NOT_ENFORCED"


@dataclass(frozen=True)
class ResourceLimits:
    """Bounded resources for compile/run subprocesses."""

    compile_timeout_sec: float = 30.0
    run_timeout_sec: float = 5.0
    max_stdout_bytes: int = 1_048_576
    max_stderr_bytes: int = 1_048_576
    overall_deadline_sec: float = 600.0
    memory_limit_mb: int | None = None

    def validate(self) -> None:
        for name, val in (
            ("compile_timeout_sec", self.compile_timeout_sec),
            ("run_timeout_sec", self.run_timeout_sec),
            ("overall_deadline_sec", self.overall_deadline_sec),
        ):
            if not math.isfinite(val) or val <= 0:
                raise ValueError(f"{name} must be a positive finite number")
        if self.max_stdout_bytes <= 0 or self.max_stderr_bytes <= 0:
            raise ValueError("output byte limits must be positive")
        if self.memory_limit_mb is not None and self.memory_limit_mb <= 0:
            raise ValueError("memory_limit_mb must be positive when set")

    def to_dict(self) -> dict:
        return {
            "compile_timeout_sec": self.compile_timeout_sec,
            "run_timeout_sec": self.run_timeout_sec,
            "max_stdout_bytes": self.max_stdout_bytes,
            "max_stderr_bytes": self.max_stderr_bytes,
            "overall_deadline_sec": self.overall_deadline_sec,
            "memory_limit_mb": self.memory_limit_mb,
            "memory_limit_enforcement": MEMORY_LIMIT_ENFORCEMENT,
        }


RESOURCE_LIMITS_DOC = """
Resource limits:
  compile_timeout_sec — wall clock per compiler invocation
  run_timeout_sec — wall clock per test input run
  overall_deadline_sec — suite-wide monotonic budget (remaining time caps each step)
  max_stdout_bytes / max_stderr_bytes — enforced during stream capture ( excess discarded )
  memory_limit_mb — reserved; enforcement is NOT_ENFORCED (never implies protection)
""".strip()
