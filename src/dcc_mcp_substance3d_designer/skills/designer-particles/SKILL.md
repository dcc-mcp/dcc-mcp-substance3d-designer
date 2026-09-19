---
name: designer-particles
description: >-
  Host particle skill - bake parameter-driven variation tiles from a Substance 3D
  Designer graph and compose them into a sprite-sheet atlas.
license: MIT
compatibility: "Substance 3D Designer 12.1+; dcc-mcp-core 0.20.15+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.8.0" # x-release-please-version
    layer: domain
    stage: authoring
    search-hint: "substance designer particles variation seed sweep sprite sheet atlas tiles vfx"
    tags: "substance, designer, particles, variation, seed, sprite, atlas, vfx"
    tools: tools.yaml
---

# Designer Particles

## Honest capability boundary

**Substance 3D Designer has no particle system.** There are no emitters, no
particles, no forces, no sprite simulation, and no point-cloud state. Nothing in
this skill simulates particle motion.

What Designer provides is a deterministic graph that can be re-evaluated after a
typed input changes. This skill uses that to author **particle assets**:

- `bake_variation_tiles` sweeps one seed/variation parameter across a bounded
  range and exports a header-verified texture per step, giving a set of
  decorrelated variations of the same procedural source.
- `compose_tile_atlas` packs one named map from that series into a grid sprite
  sheet that a downstream engine (Unreal Niagara, Unity VFX Graph, Houdini POPs)
  can sample per particle.

Treat the output as **textures for a particle system that lives elsewhere**, not
as particles authored inside Designer.

## Bounded and reversible

- Series length is bounded to 64 steps; values must be finite numbers within
  ±1,000,000.
- The output directory must be fresh, so a stale file can never be reported as a
  new result.
- The swept parameter is restored to its original value if any step fails.
- Every exported file is re-read and its header verified against the SDK-reported
  dimensions, so a truncated or stale file cannot be reported as success.

## Atlas composition

`compose_tile_atlas` requires PySide2 `QtGui`, which Designer ships. If it is
unavailable the tool fails closed with `ATLAS_COMPOSER_UNAVAILABLE` instead of
silently skipping the step. Every tile must decode; tiles may differ in size and
are placed on a shared bounding grid. The atlas is written only to a fresh
destination.

## Related

`designer-dynamics` uses the same sweep engine for iterative passes and
`designer-animation` uses it for ordered frames. Those three skills share one
engine because Designer's real capability is the same in all three cases:
re-evaluate a deterministic graph after a typed input changes.
