"""Run/build step status (per observation). Suite verdict is separate."""

from __future__ import annotations

from enum import IntEnum


class Status(IntEnum):
    """Outcome of a single compile or run observation."""

    OK = 0
    WRONG_OUTPUT = 10
    ORACLE_DISAGREEMENT = 15
    UBSAN = 20
    MEMORY_LIMIT = 30
    TIMEOUT = 40
    RUNTIME_ERROR = 50
    INTERNAL_ERROR = 60
    SPAWN_ERROR = 62
    DEADLINE_EXCEEDED = 65
    COMPILE_ERROR = 70
    SKIPPED = 80

    @property
    def severity(self) -> int:
        return int(self.value)

    @property
    def label(self) -> str:
        return self.name.lower()


def worst_status(*statuses: Status) -> Status:
    if not statuses:
        return Status.OK
    return max(statuses, key=lambda s: s.severity)


STATUS_PRECEDENCE_DOC = """
Per-step status precedence (for a single compile/run observation only):
  compile_error > skipped > deadline_exceeded > internal_error > runtime_error >
  timeout > memory_limit > ubsan > oracle_disagreement > wrong_output > ok

Suite-level overall_verdict (PASS/FAIL/INCONCLUSIVE) and issue flags are computed
separately in mctk.interpretation — they do not replace individual observations.
""".strip()
