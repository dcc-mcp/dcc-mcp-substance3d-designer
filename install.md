# Substance 3D Designer Install SOP

This is the canonical Agent-facing installation path for the Designer adapter. The installer
creates a user-owned launcher and a receipt under `~/.dcc-mcp/substance3d_designer`; it does not
modify a global shell profile, system registry, or the Designer application directory.

## Requirements

- Adobe Substance 3D Designer 12.1 or newer.
- A Python interpreter matching Designer's embedded Python ABI.
- `dcc-mcp-core>=0.20.8` and this adapter installed in that interpreter.
- Permission to write the current user's `~/.dcc-mcp` directory.

Designer 14 and newer embed Python 3.11; Designer 12.1 through 13.x embed Python 3.9. The
installer first inspects `plugins/pythonsdk` and uses this release matrix only when the SDK marker
is unavailable. See Adobe's [Python startup guidance](https://experienceleague.adobe.com/en/docs/substance-3d-designer/using/technical-issues/application-does-not-start).

## Supported versions

| Platform | Host discovery | Supported host/Python |
| --- | --- | --- |
| Windows | Creative Cloud default location or `--dcc-path` | Designer 12.1+; Python 3.9/3.11 as embedded |
| macOS | `/Applications/Adobe Substance 3D Designer.app` or `--dcc-path` | Designer 12.1+; Python 3.9/3.11 as embedded |
| Linux | `/opt/Adobe/...`, `substance3d-designer` on `PATH`, or `--dcc-path` | Designer 12.1+; Python 3.9/3.11 as embedded |

The lifecycle contract is covered on all three platforms in CI. A real Designer launch remains a
local host validation because public CI runners do not contain licensed Designer installations.

## Agent quick path

Install the wheel with the interpreter matching the selected Designer installation:

```bash
python3.11 -m pip install dcc-mcp-substance3d-designer
dcc-mcp-substance3d-designer install --dcc-path "/path/to/Adobe Substance 3D Designer" --python python3.11 --json --dry-run
dcc-mcp-substance3d-designer install --dcc-path "/path/to/Adobe Substance 3D Designer" --python python3.11 --json --yes
```

Omit `--dcc-path` only when exactly one standard installation is discoverable. `install` without
`--yes` is also a zero-write plan. Execute the single machine-readable `next_steps` command from
the result to launch Designer with the receipted plugin and Python paths. For unattended startup,
append Designer's `--config-file <path-to-default_configuration.sbscfg>` argument to that launcher
command so a stale configuration reference cannot open a blocking dialog.

The JSON contract uses exit codes `0` (ok), `10` (preflight), `20` (acquire), `30` (install), `40`
(verify), and `50` (host restart required). `next_steps[]` entries contain one executable `command`
or `file_edit`; a copied file alone is never reported as a usable installation.

Dependency note: Core PR #2320 owns the future shared schema and exit-code symbols. Until its
released Core version is available, this adapter uses an exact, thin compatibility import while
keeping the adapter-owned host discovery, launcher, receipt, and readiness behavior here.

## Manual path

For source development only, install this project into Designer's matching Python environment,
then either:

1. Add `src/dcc_mcp_substance3d_designer/designer/plugins` to
   `SBS_DESIGNER_PYTHON_PATH` before starting Designer; or
2. Open **Tools > Plugin Manager** and load
   `src/dcc_mcp_substance3d_designer/designer_plugin.py`.

The canonical installer-generated launcher preserves any existing `SBS_DESIGNER_PYTHON_PATH` and
`PYTHONPATH` entries. Prefer it for repeatable Agent operation.

## Verify

```bash
dcc-mcp-substance3d-designer status --dcc-path "/path/to/Designer" --python python3.11 --json
dcc-mcp-substance3d-designer verify --dcc-path "/path/to/Designer" --python python3.11 --json
```

`verify` checks the target imports, receipt hashes, captured bootstrap errors, registered sidecar,
and a typed Designer session probe. Only the complete path returns `directly_usable: true`.
Otherwise it fails closed with `failure_stage`, `failure_reason`, and one launch/retry `next_step`.

## Upgrade

```bash
python3.11 -m pip install --upgrade dcc-mcp-substance3d-designer
dcc-mcp-substance3d-designer upgrade --dcc-path "/path/to/Designer" --python python3.11 --json --dry-run
dcc-mcp-substance3d-designer upgrade --dcc-path "/path/to/Designer" --python python3.11 --json --yes
```

Upgrade uses staged replacement. A failed write restores the previous payload, launcher, and
receipt instead of deleting the working installation.

## Uninstall

```bash
dcc-mcp-substance3d-designer uninstall --dcc-path "/path/to/Designer" --python python3.11 --json --dry-run
dcc-mcp-substance3d-designer uninstall --dcc-path "/path/to/Designer" --python python3.11 --json --yes
python3.11 -m pip uninstall dcc-mcp-substance3d-designer
```

Uninstall removes only files whose paths and hashes match the receipt. Modified files are
preserved and reported rather than removed.

## Troubleshooting

- `host_version`: pass the executable (or the `.app` on macOS) with `--dcc-path`; set
  `DCC_MCP_SUBSTANCE3D_DESIGNER_VERSION` only for a vendor build whose metadata has no version.
- `python_compatibility`: select a Python 3.9 or 3.11 interpreter matching the discovered
  `plugins/pythonsdk` marker and install both the adapter and Core there.
- `partial` or `repair`: close Designer and rerun `install --yes`; the staged transaction
  converges without delete-then-copy behavior.
- exit `50`: Designer still holds a receipted file. Close all Designer processes, then execute the
  returned retry command.
- `bootstrap`: inspect the reported bootstrap error directory; secrets and credentials should not
  be placed in plugin paths or diagnostic files.
- `readiness`: start Designer through the generated launcher and wait for the typed sidecar probe.
  A process being open is not sufficient readiness evidence.
- Linux startup errors involving `libffi`: follow Adobe's linked `LD_PRELOAD` guidance for the
  matching `plugins/pythonsdk/lib/python3.x` directory.
