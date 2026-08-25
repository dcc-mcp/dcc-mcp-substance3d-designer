"""Prove that Designer can execute a typed host-main-thread probe."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import dcc_mcp_core
from dcc_mcp_core.skill import skill_entry, skill_success

import dcc_mcp_substance3d_designer as adapter
from dcc_mcp_substance3d_designer._install_process import observe_process_identity
from dcc_mcp_substance3d_designer.server import get_server


@skill_entry
def main(**_kwargs):
    import sd  # Lazy import: requires Designer's embedded Python.

    application = sd.getContext().getSDApplication()
    identity = observe_process_identity(os.getpid())
    bootstrap = sys.modules.get("dcc_mcp_substance3d_designer_plugin")
    server = get_server()
    if identity is None or bootstrap is None or not getattr(bootstrap, "__file__", None) or server is None:
        raise RuntimeError("Designer runtime identity is unavailable")
    mcp_url = server.mcp_url
    if not mcp_url:
        raise RuntimeError("Designer endpoint identity is unavailable")
    return skill_success(
        "Substance 3D Designer main-thread dispatch is ready",
        host_dispatch_ready=True,
        host="substance3d_designer",
        version=str(application.getVersion()),
        host_pid=os.getpid(),
        host_executable=identity["executable"],
        process_start_identity=identity["start_identity"],
        adapter_version=adapter.__version__,
        core_version=dcc_mcp_core.__version__,
        adapter_module_path=str(Path(adapter.__file__).resolve()),
        core_module_path=str(Path(dcc_mcp_core.__file__).resolve()),
        bootstrap_module_path=str(Path(bootstrap.__file__).resolve()),
        instance_id=server.instance_id,
        mcp_url=mcp_url,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
