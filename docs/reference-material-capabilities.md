# Reference-material capability matrix

The reference is an olive-painted wood crate. Editable wood grain, chipped paint,
roughness/height and steel/rust are required; geometry and a matched-camera render
remain separate acceptance gates. This document records adapter contracts, not a
claim that the reference material has been reconstructed.

The Designer 16 public Python SDK was inspected locally. Designer and Painter
crash in nvcuda64.dll before adapter registration; Designer also fails in the
requested THM environment. No new real-host graph, project or render is verified.

| Capability | Implemented contract | Remaining / live acceptance |
| --- | --- | --- |
| Graph creation/selection | Create graphs; select an explicit open-package resource and verify graph UID | Live graph selection and package ownership |
| Node creation | Built-in SDK type IDs; labels separate from native, read-only node IDs; cleanup on setup failure | Live built-in definitions and reference-specific node choices |
| Enumeration | Paginated nodes, node definitions and package resources; graph UID on graph inspection | Pagination bounds response size, not total SDK enumeration cost |
| Properties/ports | All SDK supported type IDs/modifiers, input/output direction, read-only/connectable/variadic metadata | Live definitions; automatic type conversion is deliberately unsupported |
| Parameters | Typed finite numeric inputs, SDK type match, read-only/connection/function guards, value readback | Unsupported SDK value classes still fail explicitly |
| Connect | Type/modifier compatibility, occupied input and cycle checks, exact SDK readback, idempotence | Live SDK connection semantics |
| Disconnect | Exact edge only, preserve fan-out, reacquire after invalidation, verify absence | Live handle invalidation |
| Delete/stale IDs | Re-resolve native IDs, optional expected graph UID, verify removal | Callers must supply graph UID to protect legacy optional-context tools |
| Resource import/embed | Existing bitmap/SVG and embedded PBR import; explicit resource inventory/instancing | Import/reopen with moved source images in live host |
| Subgraphs | Same-package child composition graph; explicit open-package instance; recursive graph references rejected | Function graphs lack a verified identity/binding route |
| Outputs | Native output node identity; output usage node-type validation and SDK readback; evaluation inspects textures | Duplicate identifiers rejected; setup failures remove only the new output; live channels remain unverified |
| Parameter exposure | Returns EXPOSE_API_UNAVAILABLE; removed reliance on nonexistent exposeProperty | Public function graph binding must be implemented and verified; not supported yet |
| Evaluate/errors | Node-count preflight, required outputs, synchronous compute and texture size/pixel format readback; typed SDK errors redact details | No cancellable compute deadline, resolution budget or detailed node diagnostics yet |
| Save/reopen | Preserve already-open dirty package; refuse dirty close/unrelated overwrite; save checks path, modified flag and nonempty file | Reopen/hash and graph equivalence in real host |
| PBR export | Compile current package to fresh SBSAR; official sbsrender with format/depth checks and per-output color spaces; fresh directory and required file hashes | SAT executable required; image header/depth validation and visual channel correctness remain unverified |
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

Next dependency order: finish function/property graph and exposure contracts;
complete output/evaluation bounds and image header validation; recover host startup;
then author and save the reference-specific graph, Painter layers and matched render.
