"""List packages loaded in Substance 3D Designer."""

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

    manager = sd.getContext().getSDApplication().getPackageMgr()
    packages = _value(manager, "getPackages") or []
    summary = [
        {"name": str(_value(package, "getName") or package), "path": str(_value(package, "getFilePath") or "")}
        for package in packages
    ]
    return skill_success("Listed loaded Designer packages", package_count=len(summary), packages=summary)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
