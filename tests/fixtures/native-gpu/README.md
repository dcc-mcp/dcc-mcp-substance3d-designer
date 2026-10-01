# Native renderer validation

An installed Substance 3D Designer/SAT 16.0.0 build 10849 rendered an editable
native 3D Perlin skin graph through the typed offline MCP tool on Windows.
The native log selected **NVIDIA GeForce RTX 5080**. This validates the selected
engine and output generation; the input atlas had a separate failed coverage
audit and is **not** an accepted final material or rendered showcase.

- Renderer SHA256: `2ce15e22ad38e6988d549ba8678ae6101b6ef51df732c0836ae39e255ab7265c`.
- Selected `d3d11` library SHA256: `03ef015585264325257b2a869079181325bea3f6601667963d4b1efcde43d0fe`.
- Authored SBS SHA256: `6c55bce6578f1d1f116066c879036bc9ccd6928ea1fbb7571d115ee4b5af6094`.
- Compiled SBSAR SHA256: `f23f906268e2c5c9d2bc2d710bdb7f5093e151e6c7504edbbc775fb516741e80`.
- Actual native normalized Position EXR input SHA256: `18fa5ada028162c5c786f15d3bbbe8be30aa30fe283dccfdd2b38836c872ae2a`.
- Graph identifier: `OctopusArtistRegionSkinBody`; input declared `Raw`.
- Render size: 4096 by 4096. Native archive defaults were used; the graph did
  not expose a randomseed override. All eight native PNG files were byte
  identical on two actual renders, with no native warnings or raster changes.

| Channel | Native precision | Full readback range |
| --- | --- | --- |
| BaseColor | 8-bit RGB, sRGB | 3–186 |
| Roughness | 8-bit grayscale, Raw | 86–118 |
| Normal | 8-bit RGB(A), Raw | 117–255 |
| Height | 16-bit grayscale, Raw | 30474–35061 |
| Coat | 8-bit grayscale, Raw | 25–56 |
| CoatRoughness | 8-bit grayscale, Raw | 54–82 |
| Metallic | 8-bit grayscale, Raw | constant 0 |
| SSSMask | 8-bit grayscale, Raw | constant 166 |

The six spatial outputs were independently checked for nonzero variation.
The normal length error at the 99.9th percentile was `0.001306336285238574`.
The pixel ranges are this graph's native output, not general adapter limits.
Actual material geometry, units, UV coverage, region assignment and final
shader/render acceptance remain the caller's responsibility.

This record does not bundle the model or the large case-owned output atlas.
Native hardware validation is separate from the portable unit tests.
