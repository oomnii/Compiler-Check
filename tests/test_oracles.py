import pytest

from mctk.inputgen import generate_cases
from mctk.oracles import get_oracle

MOCK = pytest.mark.mock_subprocess


@MOCK
def test_generated_inputs_deterministic():
    a = generate_cases("arithmetic", 42, 3)
    b = generate_cases("arithmetic", 42, 3)
    assert a == b
    oracle = get_oracle("arithmetic_sum")
    for case in a:
        assert oracle(case.stdin) == oracle(case.stdin)


@MOCK
def test_sort_oracle():
    oracle = get_oracle("sort_array")
    out = oracle("3\n3 1 2\n")
    assert out == "1 2 3\n"
    assert oracle("0\n") == "\n"
