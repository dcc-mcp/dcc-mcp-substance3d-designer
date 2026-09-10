# Native material authoring

Designer compositing nodes expose read-only numeric identifiers. Creation tools
return the actual `node_id`, `requested_node_id`, and `identifier_assigned`.
Always use the returned native ID for connections and parameter changes. A
requested name is not a persistent alias when `identifier_assigned` is false.
Failed node setup removes the newly created node; SDK `APIException` is reported
as a failure even though Adobe derives it directly from `BaseException`.

`create_resource_node` instances an explicitly named graph from a shipped `.sbs`
package under Designer's resource directory. External package paths are rejected.
`select_graph` activates an explicit graph from an already loaded package, so
opening a saved package does not depend on manual editor selection.

`render_graph_maps` computes one to eight explicit source ports at 256, 512, 1024,
or 2048 pixels and writes PNG files to a new output directory. It sets the graph's
output-size inheritance to absolute before computing and checks actual texture
dimensions before saving. Existing export directories are never overwritten.
It reports file paths and SHA-256 values; it does not infer color conversion or
claim model-space material acceptance.

## Live validation

Validated in Designer 16.0 with editable painted-wood and rusted-steel graphs:
shipped resource creation, native ID connections, RGBA parameter values, output
usages, saving, graph selection after reopening, and five-channel 1024-pixel
native exports. The initial relative-resolution render exceeded the intended
size; the absolute-inheritance fix reduced the repeat to the requested size.

Remaining work includes graph property/port discovery, explicit disconnect,
parameter exposure through the supported SDK contract, model-space edge wear,
and reference-matched lighting/UV validation. Library resource dependencies remain
part of the editable packages; this change does not claim self-contained SBSARs.
