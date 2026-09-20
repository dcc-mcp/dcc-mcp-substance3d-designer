---
name: designer-plugins
description: >-
  Host plugin skill - inventory the Substance 3D Designer node modules that back
  built-in plugins, and probe which module-manager APIs the running build advertises.
license: MIT
compatibility: "Substance 3D Designer 12.1+; dcc-mcp-core 0.20.15+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.8.1" # x-release-please-version
    layer: domain
    stage: discovery
    search-hint: "substance designer plugins modules node definitions inventory capability probe"
    tags: "substance, designer, plugin, module, node, definition, inventory, read-only"
    tools: tools.yaml
---

# Designer Plugins

## Honest capability boundary

Designer does not expose a general plugin install, load, or unload API through
its Python SDK. This skill is therefore **read-only discovery**: it reports the
node modules that a running Designer build actually provides, and probes which
manager APIs exist. It never installs, loads, unloads, or mutates anything.

The authoritative plugin surface is the graph's node-definition inventory — the
same inventory `create_node` validates against. If a node type is not in that
inventory, `create_node` will reject it.

## Tools

- `list_node_modules` — group every available node definition into its owning
  module namespace (for example `sbs::compositing`, `sbs::filter`) with a count.
  Use it first to learn which plugin families exist.
- `describe_node_module` — list the definitions owned by one module, optionally
  filtered by a case-insensitive query. Fails with `MODULE_NOT_FOUND` when the
  namespace has no matches.
- `module_capabilities` — read-only attribute probe. Reports which application
  manager methods (`getModuleMgr`, `getPackageMgr`, `getAppInteropMgr`,
  `getQtForPythonUIMgr`) and which SDK modules (`sd.api.sdmodule`,
  `sd.api.sddefinition`) this build advertises. A missing API is reported as
  `false`; absence is an expected result, not a failure.

## Module namespace convention

A definition id such as `sbs::compositing::blur` belongs to module
`sbs::compositing` (the first two segments). Definitions without a namespace are
reported under `<root>` rather than being silently dropped.

The module manager, when present, is reported as a supplementary list. Prefer the
definition inventory: it is the surface node creation is validated against.

## See also

`designer-effects` and `designer-lighting` resolve recipe node types against
this same inventory, which is why they fail closed with `RECIPE_UNAVAILABLE`
instead of assuming a type exists.
