"""Standalone CLI artifact service. It is not bound to an optional Designer GUI."""

from __future__ import annotations

import argparse
import json
import os
import threading
from pathlib import Path

from dcc_mcp_core import DccServerOptions
from dcc_mcp_core.server_base import DccServerBase

from .__version__ import __version__
from .offline_artifacts import installed_tool


class DesignerOfflineServer(DccServerBase):
    def __init__(self, port: int | None = None, **kwargs):
        options = DccServerOptions.from_env(
            "substance3d_designer",
            Path(__file__).parent / "skills" / "designer-offline",
            port=port,
            server_name="dcc-mcp-designer-offline",
            server_version=__version__,
            adapter_version=__version__,
            instance_type="standalone",
            **kwargs,
        )
        super().__init__(options=options)

    def register_builtin_actions(self, *, include_bundled=False, **kwargs):
        super().register_builtin_actions(include_bundled=include_bundled, **kwargs)
        if not self.load_skill("designer-offline"):
            raise RuntimeError("Designer offline artifact skill could not be loaded")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--designer-bin", type=Path, required=True)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    os.environ["DCC_MCP_SUBSTANCE3D_DESIGNER_BIN"] = str(args.designer_bin.expanduser().resolve(strict=True))
    installed_tool("sbscooker")
    installed_tool("sbsrender")
    server = DesignerOfflineServer(args.port)
    server.register_builtin_actions()
    server.start()
    print(json.dumps({"instance_id": server.instance_id, "instance_type": "standalone"}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


if __name__ == "__main__":
    main()
