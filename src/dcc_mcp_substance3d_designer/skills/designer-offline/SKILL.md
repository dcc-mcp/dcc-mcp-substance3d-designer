---
name: designer-offline
description: >-
  Offline artifact skill - cook hash-pinned SBS sources and render compiled
  SBSAR maps and bake pinned UV0 mesh positions and FBX colour IDs with installed official
  Substance tools without a Designer GUI.
license: MIT
compatibility: "Installed sbscooker/sbsrender; optional substance3d_baker/FFmpeg for positions; dcc-mcp-core 0.20.15+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.8.1" # x-release-please-version
    layer: task
    stage: production
    search-hint: "offline substance designer cook SBS SBSAR render CLI GPU engine d3d11 Vulkan maps headless mesh baker color material vertex IDs position artifacts"
    tags: "substance,designer,offline,cook,render,gpu,engine,baker,color-id,position,artifacts"
    tools: tools.yaml
---

# Designer Offline Artifacts

Use the standalone service for an existing SBS or SBSAR when no Designer SDK
session is needed. The operator configures `DCC_MCP_SUBSTANCE3D_DESIGNER_BIN` to
the installed official CLI directory. Tools cannot select another executable,
pass shell commands, install software or control a GUI.

1. Hash the actual input bytes and choose a fresh output directory.
2. `cook_package` cooks one SBS source and records the source, archive and tool
   hashes. The cooker reads a pinned temporary SBS beside the original input;
   that directory must be writable. Relative dependency paths keep that directory,
   but their hashes are **not** independently collected.
3. `render_archive` requires the exact complete output set (one to eight
   channels), each channel's bit depth and color space and expected resolution.
   Optional image inputs require their actual SHA256 and color space.
   `engine` defaults to `sse2`; documented identifiers `neon`, `d3d11`, `vk`,
   `ogl3` and `mtl` are available when exactly one matching installed library
   exists. The adapter resolves and hashes that fixed library before execution,
   passes its exact path to the renderer, verifies the hash afterwards, and
   preserves warnings. There is no automatic CPU fallback or caller-selected
   DLL path. GPU-only nodes such as 3D Perlin require an actual GPU render.
   `inspect_renderer` reads fixed native render help and installed engine
   identities. Library availability alone does not prove GPU execution.
4. `bake_position_map` requires a self-contained, triangulated OBJ with positive
   UV0 indices and one normalized UV tile. It uses installed
   `substance3d_baker` to bake bbox-normalized XYZ/Raw EXR twice. Configure the
   installed decoder through `DCC_MCP_SUBSTANCE3D_DESIGNER_FFMPEG`; every RGB
   float sample must be finite and between zero and one. Native padding is
   explicit, mip diffusion is disabled, and native warnings/argv are retained.
5. Read the returned manifest. Every PNG has complete chunk/checksum/scanline
   validation. Two official renders must have identical actual bytes before
   the output directory is published.
6. `inspect_mesh_baker` returns the installed, hash-pinned Color or Position
   baker's bounded help. `bake_color_map` accepts one hash-pinned FBX with
   caller-authored vertex or material colours. It uses that exact owned scene
   as both low and high geometry, records fixed UV0/projection settings, and
   requires byte-identical native PNG rerenders. Random mesh/UV-island ID
   generators are deliberately outside this explicit colour contract.
   Native PNG precision is read from the actual file (8-bit or 16-bit),
   completely validated, and recorded without quantizing pixels. Missing
   requested native colour attributes reject publication even when the baker
   writes a complete blank image.

Colour baking establishes native files and their provenance; callers still
validate region assignment, packing, coverage and UV correspondence against
actual indexed geometry. The adapter does not parse FBX topology or recognize
anatomy. Vertex colour interpolation and native ray projection can introduce
boundary pixels; keep native warnings and verify the intended region palette.
For material colours, the installed native baker requires FBX. See Adobe's
[official baker options](https://adobedocs.github.io/substance-automation-toolkit/pysbs/sat_commandlines/substance3d_baker_options.html).
Engine identifiers follow Adobe's
[official renderer options](https://adobedocs.github.io/substance-automation-toolkit/pysbs/sat_commandlines/sbsrender_options.html).

Raw covers linear data such as roughness, height and normals; declare sRGB for
color only when that is the source graph's intended encoding. Tangent normal
conventions are caller declarations, not inferred from RGB samples. This tool
does not assign displacement units, identify anatomy or validate a downstream
shader. Constant channels are legal. Never call offline success a live Designer
SDK/session acceptance or claim independently pinned source dependencies.

EXR image inputs are restricted to normalized position data with explicit Raw
color space and complete float readback. Position baking does not establish
mesh/UV correspondence or complete UV coverage: the caller must audit these
against its actual indexed artist geometry. Native warnings are evidence, not
automatically ignored diagnostics. No input mesh or UV coordinates are edited.

Seed overrides are optional and require an exposed `$randomseed` input in the
compiled interface. Unknown image inputs are rejected. Fixed compiled defaults
remain unchanged; output dimensions must match the requested resolution.

Native processes use the adapter's existing owned process-tree supervisor;
timeouts and cleanup failures reject the artifact. Output publication never
overwrites an existing directory. Windows sharing violations while reading an
atomic process receipt retry for at most 0.5 seconds within the existing
deadline; malformed receipts and other file errors remain failures. CLI log
cleanup shares that same deadline and retains native diagnostics before removal.
Graph authoring through the Designer SDK
continues to use `designer-session` on a running GUI instance.
