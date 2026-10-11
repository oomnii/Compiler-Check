from mctk.status import Status, worst_status


def test_worst_status_precedence_order():
    assert worst_status(Status.OK, Status.WRONG_OUTPUT) == Status.WRONG_OUTPUT
    assert worst_status(Status.WRONG_OUTPUT, Status.TIMEOUT) == Status.TIMEOUT
    assert worst_status(Status.TIMEOUT, Status.RUNTIME_ERROR) == Status.RUNTIME_ERROR
    assert worst_status(Status.RUNTIME_ERROR, Status.COMPILE_ERROR) == Status.COMPILE_ERROR
    assert worst_status(Status.ORACLE_DISAGREEMENT, Status.WRONG_OUTPUT) == Status.ORACLE_DISAGREEMENT


def test_severity_matches_documented_chain():
    assert Status.COMPILE_ERROR.severity > Status.DEADLINE_EXCEEDED.severity
    assert Status.DEADLINE_EXCEEDED.severity > Status.INTERNAL_ERROR.severity
    assert Status.INTERNAL_ERROR.severity > Status.RUNTIME_ERROR.severity
    assert Status.RUNTIME_ERROR.severity > Status.TIMEOUT.severity
    assert Status.UBSAN.severity > Status.ORACLE_DISAGREEMENT.severity
