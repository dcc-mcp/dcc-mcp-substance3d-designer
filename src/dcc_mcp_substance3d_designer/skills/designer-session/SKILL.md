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
    version: "0.6.1" # x-release-please-version
    layer: bootstrap
    stage: bootstrap
    search-hint: "substance designer typed graph nodes connections parameters outputs package sbs sbsar render maps inspect"
    tags: "substance, designer, package, graph, node, connection, parameter, output, sbsar, render, inspect"
    tools: tools.yaml
---

# Designer Session

Read the active Designer session and graph before mutating it. The public tools
create built-in `sbs::` nodes or explicit open-package resource instances, address native node and
property identifiers, and accept an allowlisted set of scalar and vector value
types. They do not expose an eval, script, shell, or generic action surface.

Use `export_graph_state` after each authoring sequence to verify node count,
type URLs, positions, parameters, topology, and output usages. A typical graph
sequence is `create_graph` → `create_node` → `connect_nodes` →
`set_parameter` → `add_output`/`set_output_usage` →
`save_package_as` → `export_graph_state`.

Package tools use Designer's package manager. Bitmap and SVG imports validate
the declared resource kind and use linked resources unless `embed=true` is
explicitly requested. `export_sbsar` uses Designer's official SBSAR exporter
and requires a fresh, nonempty artifact. `export_maps` compiles the current package
to SBSAR in a new run directory, then invokes only the
official `sbsrender` executable discovered by the host environment and always
requires explicit format, bit depth, and color-space settings; it fails closed
when that executable is unavailable.

Parameter exposure is not implemented for the inspected public SDK. The tool
returns `EXPOSE_API_UNAVAILABLE`; a verified function-graph binding is still needed.
Host API calls remain on the
Designer main thread through the adapter's Core execution bridge.

Start with `list_nodes` and `list_node_types`, then `describe_node` or
`describe_node_type` to inspect supported parameter and port types. Reuse returned
native IDs; `create_node.node_id` sets a display label, not the SDK handle.
Pass the observed `graph_uid` as `expected_graph_uid` on supported mutations.
Use `validate_connection` before connecting and `disconnect_nodes` for exact-edge
removal. Open package resources can be inspected, selected or instanced through
`list_resources`, `select_graph` and `instance_resource`; `create_subgraph` creates
a same-package composition graph. Recursive instances are rejected.

`evaluate_graph` checks a node-count budget and computed output texture metadata.
Compute remains synchronous with no hard cancellation deadline. Exported file
hashes prove fresh bytes, not image-header validity or visual material accuracy.
Save before closing a modified package; opening an already-open package preserves
its in-memory edits. Use a new path to export SBSAR or save another package.

The higher-level procedural and imported-PBR tools remain available for common
material recipes. Use the granular tools when the graph topology or package
lifecycle must be controlled and verified step by step.
