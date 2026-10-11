from mctk.toolchain import _SMOKE_SOURCE, discover_toolchains

from tests.conftest import REAL, require_smoke_toolchain


def test_smoke_probe_source_keeps_cout_literal():
    assert '<< "mctk_smoke\\n"' in _SMOKE_SOURCE


@REAL
def test_discovers_gxx_cpp17():
    tc = require_smoke_toolchain()
    assert tc.smoke_ok
    assert "-std=c++17" in tc.cpp17_flags
    toolchains = discover_toolchains()
    assert len(toolchains) >= 1
