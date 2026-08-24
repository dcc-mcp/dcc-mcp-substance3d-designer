---
name: designer-session
description: >-
  Host skill - inspect and author the active Substance 3D Designer session.
  Use when checking Designer state or creating a rendered procedural or
  texture-imported PBR material package through typed graph operations.
license: MIT
compatibility: "Substance 3D Designer Python 3.9+; dcc-mcp-core 0.20.15+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.5.0"
    layer: bootstrap
    stage: bootstrap
    search-hint: "substance designer session package procedural imported packed rmas pbr graph render textures inspect"
    tags: "substance, designer, package, graph, procedural, import, rmas, pbr, render, textures, inspect"
    tools: tools.yaml
---

# Designer Session

Read the active Designer session and its adapter lifecycle health, then create a typed layered PBR graph that
saves an `.sbs` package and renders BaseColor, Roughness, Metallic, Height, and
Normal maps. The authoring tool uses public Designer graph APIs and never
executes arbitrary code supplied by callers.

For captured game materials, import BaseColor, tangent-space Normal, and packed
RMAS maps. The typed import tool links the source bitmaps, splits RMAS into
Roughness, Metallic, and Ambient Occlusion, and renders five standard PBR maps.
