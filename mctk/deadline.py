"""Suite-wide wall-clock deadline."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Deadline:
    """Monotonic deadline for an entire suite run."""

    overall_sec: float
    started_at: float = 0.0

    @classmethod
    def start(cls, overall_sec: float) -> Deadline:
        return cls(overall_sec=overall_sec, started_at=time.monotonic())

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.overall_sec - self.elapsed())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def cap_timeout(self, step_timeout_sec: float) -> float:
        if step_timeout_sec <= 0:
            raise ValueError("step timeout must be positive")
        return min(step_timeout_sec, self.remaining())
