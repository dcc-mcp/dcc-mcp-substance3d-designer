---
name: designer-offline
description: >-
  Offline artifact skill - cook hash-pinned SBS sources and render compiled
  SBSAR maps with installed official Substance tools without a Designer GUI.
license: MIT
compatibility: "Installed sbscooker/sbsrender; dcc-mcp-core 0.20.15+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.8.1" # x-release-please-version
    layer: task
    stage: production
    search-hint: "offline substance designer cook SBS SBSAR render CLI maps headless artifacts"
    tags: "substance,designer,offline,cook,render,artifacts"
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
4. Read the returned manifest. Every PNG has complete chunk/checksum/scanline
   validation. Two official renders must have identical actual bytes before
   the output directory is published.

Raw covers linear data such as roughness, height and normals; declare sRGB for
color only when that is the source graph's intended encoding. Tangent normal
conventions are caller declarations, not inferred from RGB samples. This tool
does not assign displacement units, identify anatomy or validate a downstream
shader. Constant channels are legal. Never call offline success a live Designer
SDK/session acceptance or claim independently pinned source dependencies.

Seed overrides are optional and require an exposed `$randomseed` input in the
compiled interface. Unknown image inputs are rejected. Fixed compiled defaults
remain unchanged; output dimensions must match the requested resolution.

Native processes use the adapter's existing owned process-tree supervisor;
timeouts and cleanup failures reject the artifact. Output publication never
overwrites an existing directory. Graph authoring through the Designer SDK
continues to use `designer-session` on a running GUI instance.
