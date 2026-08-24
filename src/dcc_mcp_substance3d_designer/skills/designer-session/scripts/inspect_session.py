"""Inspect a running Substance 3D Designer session."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from dcc_mcp_core.skill import skill_entry, skill_success


def _value(obj, *names):
    for name in names:
        member = getattr(obj, name, None)
        if member is not None:
            return member() if callable(member) else member
    return None


def _ocio_details(engine):
    config = str(_value(engine, "getOCIOConfigFileName") or "")
    path = Path(config)
    return {
        "mode": str(_value(engine, "getName") or "unknown"),
        "working_space": str(_value(engine, "getWorkingColorSpaceName") or "unknown"),
        "raw_space": str(_value(engine, "getRawColorSpaceName") or "unknown"),
        "config_path": config or None,
        "environment_path": os.environ.get("OCIO") or None,
        "config_sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None,
    }


@skill_entry
def main(**_kwargs):
    import sd  # Lazy import: requires Designer's embedded Python.

    from dcc_mcp_substance3d_designer.plugin import get_lifecycle_status

    app = sd.getContext().getSDApplication()
    ui = _value(app, "getUIMgr")
    graph = _value(ui, "getCurrentGraph") if ui else None
    color_engine = _value(app, "getColorManagementEngine")
    return skill_success(
        "Inspected Substance 3D Designer session",
        version=str(_value(app, "getVersion") or "unknown"),
        active_graph=str(_value(graph, "getIdentifier", "getName") or "none"),
        adapter_lifecycle=get_lifecycle_status(),
        color_management=_ocio_details(color_engine),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
