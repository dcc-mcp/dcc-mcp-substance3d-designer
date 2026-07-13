# dcc-mcp-substance3d-designer

Substance 3D Designer adapter for the DCC Model Context Protocol (MCP).

The package runs an embedded Streamable HTTP MCP server inside Designer, so
tools execute through Designer's Qt main thread instead of a separate process.

## Install and load

Install this package with the Python environment used by Substance 3D Designer:

```bash
python -m pip install dcc-mcp-substance3d-designer
```

In Designer, open **Tools > Plugin Manager**, browse to the installed
`dcc_mcp_substance3d_designer/designer_plugin.py`, then load the plugin. The
MCP endpoint defaults to `http://127.0.0.1:8765/mcp`.

Set `DCC_MCP_SUBSTANCE3D_DESIGNER_PORT` before launching Designer to choose a
different port. Standard `DCC_MCP_GATEWAY_PORT` and `DCC_MCP_REGISTRY_DIR`
settings are also honoured.

## Bundled skills

`designer-session` provides read-only typed tools for inspecting the active
Designer session and its loaded packages. Host APIs are imported only while a
tool runs, so metadata discovery remains safe outside Designer.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
ruff check src tests tools
python -m build
```

Releases use release-please. The `release.yml` workflow publishes through the
`pypi` environment using PyPI Trusted Publishing.
