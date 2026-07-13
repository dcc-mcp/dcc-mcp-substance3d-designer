"""Inspect a running Substance 3D Designer session."""

from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success


def _value(obj, *names):
    for name in names:
        member = getattr(obj, name, None)
        if member is not None:
            return member() if callable(member) else member
    return None


@skill_entry
def main(**_kwargs):
    import sd  # Lazy import: requires Designer's embedded Python.

    app = sd.getContext().getSDApplication()
    ui = _value(app, "getUIMgr")
    graph = _value(ui, "getCurrentGraph") if ui else None
    return skill_success(
        "Inspected Substance 3D Designer session",
        version=str(_value(app, "getVersion") or "unknown"),
        active_graph=str(_value(graph, "getIdentifier", "getName") or "none"),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
