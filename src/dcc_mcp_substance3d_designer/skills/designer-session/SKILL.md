---
name: designer-session
description: >-
  Host skill - inspect, author, save, and export a Substance 3D Designer graph.
  Use when an Agent needs bounded node, connection, parameter, output, package,
  resource, map, or SBSAR operations instead of arbitrary Python execution.
license: MIT
compatibility: "Substance 3D Designer Python 3.9+; dcc-mcp-core 0.20.15+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.6.0" # x-release-please-version
    layer: bootstrap
    stage: bootstrap
    search-hint: "substance designer typed graph nodes connections parameters outputs package sbs sbsar render maps inspect"
    tags: "substance, designer, package, graph, node, connection, parameter, output, sbsar, render, inspect"
    tools: tools.yaml
---

# Designer Session

Read the active Designer session and graph before mutating it. The public tools
create only bounded built-in `sbs::` node types, address explicit node and
property identifiers, and accept an allowlisted set of scalar and vector value
types. They do not expose an eval, script, shell, or generic action surface.

Use `export_graph_state` after each authoring sequence to verify node count,
type URLs, positions, parameters, topology, and output usages. A typical graph
sequence is `create_graph` → `create_node` → `connect_nodes` →
`set_parameter`/`expose_parameter` → `add_output`/`set_output_usage` →
`save_package_as` → `export_graph_state`.

Package tools use Designer's package manager. Bitmap and SVG imports validate
the declared resource kind and use linked resources unless `embed=true` is
explicitly requested. `export_sbsar` uses Designer's official SBSAR exporter
and verifies that the requested artifact exists. `export_maps` invokes only the
official `sbsrender` executable discovered by the host environment and always
requires explicit format, bit depth, and color-space settings; it fails closed
when that executable is unavailable.

Parameter exposure is capability-gated. If the running Designer build does not
provide the supported binding API, the tool returns `EXPOSE_API_UNAVAILABLE`
instead of creating an unbound graph property. Host API calls remain on the
Designer main thread through the adapter's Core execution bridge.

The higher-level procedural and imported-PBR tools remain available for common
material recipes. Use the granular tools when the graph topology or package
lifecycle must be controlled and verified step by step.
