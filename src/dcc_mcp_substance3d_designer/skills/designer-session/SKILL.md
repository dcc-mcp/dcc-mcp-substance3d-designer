---
name: designer-session
description: >-
  Host skill - inspect the active Substance 3D Designer session and loaded
  packages. Use when checking Designer state before graph authoring. Not for
  modifying graph content.
license: MIT
compatibility: "Substance 3D Designer Python 3.9+; dcc-mcp-core 0.19+"
allowed-tools: Python
metadata:
  dcc-mcp:
    dcc: substance3d_designer
    version: "0.0.0"
    layer: bootstrap
    stage: bootstrap
    search-hint: "substance designer session packages active graph inspect"
    tags: "substance, designer, package, graph, inspect"
    tools: tools.yaml
---

# Designer Session

Read the active Designer session before choosing graph-authoring operations.
