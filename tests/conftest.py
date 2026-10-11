"""Pytest markers and toolchain capability skips."""

from __future__ import annotations

import pytest

from mctk.toolchain import discover_toolchains

REAL = pytest.mark.real_compiler
MOCK = pytest.mark.mock_subprocess

_pass_real: list[str] = []
_pass_mock: list[str] = []


def pytest_configure(config):
    config.addinivalue_line("markers", "real_compiler: requires host g++/clang++ smoke OK")
    config.addinivalue_line("markers", "mock_subprocess: no real compiler required")


def require_smoke_toolchain():
    toolchains = discover_toolchains()
    if not toolchains:
        pytest.skip("no C++17 toolchain passed smoke probe on this host")
    gcc = next((t for t in toolchains if t.id == "g++"), toolchains[0])
    return gcc


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call" and rep.passed:
        if item.get_closest_marker("real_compiler"):
            _pass_real.append(item.nodeid)
        else:
            _pass_mock.append(item.nodeid)


def pytest_terminal_summary(terminalreporter):
    skipped = terminalreporter.stats.get("skipped", [])
    terminalreporter.write_sep("-", "CompilerCheck test backend summary")
    terminalreporter.write_line(f"Passed with real compiler toolchain: {len(_pass_real)}")
    for nid in _pass_real:
        terminalreporter.write_line(f"  [real] {nid}")
    terminalreporter.write_line(f"Passed with mocks/synthetic only: {len(_pass_mock)}")
    for nid in _pass_mock:
        terminalreporter.write_line(f"  [mock] {nid}")
    if skipped:
        terminalreporter.write_line(f"Skipped: {len(skipped)}")
        for rep in skipped:
            terminalreporter.write_line(f"  [skip] {rep.nodeid}")
