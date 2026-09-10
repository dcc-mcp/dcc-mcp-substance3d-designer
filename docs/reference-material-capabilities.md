# Reference-material capability matrix

The reference is an olive-painted wood crate. Editable wood grain, chipped paint,
roughness/height and steel/rust are required; geometry and a matched-camera render
remain separate acceptance gates. This document records adapter contracts, not a
claim that the reference material has been reconstructed.

The Designer 16 public Python SDK was inspected locally. Earlier startup crashes
are historical: a live Designer 16 instance now supports typed SDK calls. The
painted-wood review copy has been saved/reopened and exported in that host. Current
DCC-CUA viewport capture is blocked by InteractiveDesktopUnavailable; no matched
crate render or Painter project has been accepted.

| Capability | Implemented contract | Remaining / live acceptance |
| --- | --- | --- |
| Graph creation/selection | Create graphs; select an explicit open-package resource and verify graph UID | Live graph selection and package ownership |
| Node creation | Built-in SDK type IDs; labels separate from native, read-only node IDs; cleanup on setup failure | Live built-in definitions and reference-specific node choices |
| Enumeration | Paginated nodes, node definitions and package resources; graph UID on graph inspection | Pagination bounds response size, not total SDK enumeration cost |
| Properties/ports | All SDK supported type IDs/modifiers, input/output direction, read-only/connectable/variadic metadata | Live definitions; automatic type conversion is deliberately unsupported |
| Parameters | Finite scalar/vector/ColorRGBA inputs, SDK type match and readback; graph-input setter | ColorRGBA and float graph input verified live; other classes need live coverage |
| Connect | Type/modifier compatibility, occupied input and cycle checks, exact SDK readback, idempotence | Live SDK connection semantics |
| Disconnect | Exact edge only, preserve fan-out, reacquire after invalidation, verify absence | Live handle invalidation |
| Delete/stale IDs | Re-resolve native IDs, optional expected graph UID, verify removal | Callers must supply graph UID to protect legacy optional-context tools |
| Resource import/embed | Existing bitmap/SVG and embedded PBR import; explicit resource inventory/instancing | Import/reopen with moved source images in live host |
| Subgraphs | Same-package child composition graph; explicit open-package instance; recursive graph references rejected | Function graphs lack a verified identity/binding route |
| Outputs | Native output node identity; output usage node-type validation and SDK readback; evaluation inspects textures | Duplicate identifiers rejected; setup failures remove only the new output; live channels remain unverified |
| Parameter exposure | Public graph input plus property function graph, runtime-discovered variable port, preserved default and rollback | Float paint_coverage binding saved/reopened and changes rendered pixels; other advertised reader types need live checks |
| Evaluate/errors | Node and static resolution budgets, reject dynamic/unproven amplification; texture readback; per-node input/function/connection diagnostics and interop error | Live 1024 evaluation/export passes; SDK compute has no cancel method, and interop errors are not compiler logs |
| Save/reopen | Dirty-edit protection, expected graph guard on save-as, file readback; review copy closed/reopened in real host | Input binding survives; rendered pixels differ slightly after reopening, so byte-identical reproducibility is not claimed |
| PBR export | Fresh SBSAR compile; SAT process-tree ownership/timeout cleanup; bounded PNG/TGA/TIFF/EXR header/depth validation; native PNG export with SDK dimensions and actual precision | Live 1024 native maps: baseColor/roughness/metallic 8-bit, height/normal 16-bit; SBSAR compiled. SAT executable unavailable here; image headers do not prove full decoding or visual correctness |
| Preview/reference comparison | No final host render delivered | Matched camera/light/scale, wood/paint/rust detail review, editable .sbs/.spp and final maps |

SDK contract tests cover connection failures, stale IDs, parameter validation,
SDK exceptions inheriting BaseException, missing/stale exports, renderer failure
and timeout, dirty package preservation, recursion and graph selection readback.
They do not establish visual quality or live SDK execution. Installer probe tests
can fail transiently when spawning a target interpreter on this Windows host;
report full-suite and rerun results separately.

The export command follows the official [SAT sbsrender options](https://adobedocs.github.io/substance-automation-toolkit/pysbs/sat_commandlines/sbsrender_options.html).
SDK semantics should be checked against the installed SDK and the official
[Designer scripting reference](https://experienceleague.adobe.com/en/docs/substance-3d-designer/using/scripting/scripting-api-reference).

Remaining acceptance: restore access to the interactive desktop; add reference-specific
board/edge/metal segmentation and independent detail scales; verify the crate under
matched geometry, camera and lighting; complete Painter handoff if required. Current
wood/steel graphs remain planar material approximations, not a full crate reconstruction.

Installer diagnostic checkpoint: 100 direct probes and four full suites initially
passed. A later new-code full suite reproduced one unclassified preflight failure.
Stable redacted failure categories were then added; five subsequent full runs each
passed 231 tests with 2 skips. The intermittent failure root cause is still unknown;
these passes are not evidence that it was fixed. Ruff, Skill lint, build, wheel
metadata and Twine validation passed.

The final candidate module snapshot was also loaded under a separate live namespace
and completed native export with the same graph UID and verified image headers.
Budget scope: top-level nodes and statically known output-size inheritance. This is
not a proof of maximum memory used by internal buffers of shipped subgraphs.

SDK evidence: Adobe sample_sbs_graph_inputs.py documents newProperty;
sample_sbs_parameter_function.py documents newPropertyGraph and setOutputNode.
SDGraph.compute is synchronous and has no public cancel method; cancellation on
SDSBSGraphThumbnailGenerator applies only to thumbnail generation. The SAT renderer
uses an owned process tree instead; a real Windows timeout test verifies its child
process is gone. Full host compute cannot be terminated safely without risking the
user's application, so no hard in-process cancellation claim is made.
