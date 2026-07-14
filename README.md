# dcc-mcp-substance3d-designer

Substance 3D Designer adapter for the DCC Model Context Protocol (MCP).

The package runs an embedded Streamable HTTP MCP server inside Designer, so
tools execute through Designer's Qt main thread instead of a separate process.

## Install and load

Install this package with the Python environment used by Substance 3D Designer:

```bash
python -m pip install dcc-mcp-substance3d-designer
```

For unattended startup, append the installed package's
`dcc_mcp_substance3d_designer/designer/plugins` directory to
`SBS_DESIGNER_PYTHON_PATH`. Designer discovers the dedicated
`dcc_mcp_substance3d_designer_plugin` module without scanning the adapter's
implementation modules as plugins.

For an interactive installation, open **Tools > Plugin Manager**, browse to
`dcc_mcp_substance3d_designer/designer_plugin.py`, then load the plugin. The MCP
endpoint defaults to `http://127.0.0.1:8765/mcp`.

Set `DCC_MCP_SUBSTANCE3D_DESIGNER_PORT` before launching Designer to choose a
different port. Standard `DCC_MCP_GATEWAY_PORT` and `DCC_MCP_REGISTRY_DIR`
settings are also honoured.

For unattended launches, pass Designer a persistent configuration with
`--config-file <path-to-default_configuration.sbscfg>`. This prevents a stale
session-specific configuration reference from opening a blocking startup
dialog.

## Bundled skills

`designer-session` provides typed tools for inspecting the active Designer
session and creating a rendered procedural PBR material package. Host APIs are
imported only while a tool runs, so metadata discovery remains safe outside
Designer.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
ruff check src tests tools
python -m build
```

Releases use release-please. The `release.yml` workflow publishes through the
`pypi` environment using PyPI Trusted Publishing.
