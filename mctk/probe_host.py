"""Record toolchain / UBSan capability on the current machine (for verification logs)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from mctk.limits import ResourceLimits
from mctk.toolchain import discover_toolchains, resolve_toolchain
from mctk.ubsan import probe_ubsan


def main() -> int:
    cache = Path(".mctk_probe_cache")
    limits = ResourceLimits()
    discovered = discover_toolchains()
    clang = resolve_toolchain("clang++", discovered)

    payload = {
        "implemented_in_toolkit": {
            "clang_family_detection": True,
            "ubsan_probe_and_diagnostic_builds": True,
            "note": "Implementation exists regardless of host success below.",
        },
        "host_discovered_toolchains": [t.to_dict() for t in discovered],
        "clang++_resolve": None
        if clang is None
        else {"found": True, **clang.to_dict()},
        "clang++_missing_reason": None
        if clang
        else "resolve_toolchain('clang++') returned None (not on PATH or probe failed)",
        "ubsan_probe_by_toolchain": [],
    }

    for tc in discovered:
        if tc.id not in ("g++", "clang++"):
            continue
        result = probe_ubsan(tc, limits, cache)
        payload["ubsan_probe_by_toolchain"].append(
            {
                "toolchain_id": tc.id,
                "supported_on_this_machine": result.supported,
                "message": result.message,
            }
        )

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
