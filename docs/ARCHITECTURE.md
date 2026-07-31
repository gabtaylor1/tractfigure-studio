# Architecture contract

## Coordinates

- Images retain their NIfTI voxel data and affine.
- Loaded streamlines are normalized to RAS+ world coordinates in millimeters
  (`RASMM`).
- Ambiguous source conventions are detected by scoring plausible transforms
  against the supplied reference image; the selected convention, score,
  confidence, bounds, and warnings are retained in the layer inspection report.
- A reference image is required whenever a tract format does not provide enough
  geometry for a reliable world-coordinate interpretation.
- Original inputs are immutable. Converted or transformed streamlines are
  derived products.

## Transform direction

Every public registration matrix maps:

```text
moving RASMM -> fixed RASMM
```

Image resampling internally computes the inverse sampling relationship required
to populate the fixed output grid. That implementation detail must not change
the public matrix direction.

## Scene state

`src/tractfigure/scene_state_v1_20260730.py` is the serialization contract.
Layer order and stable layer IDs associate visibility, color, opacity, render
mode, and geometry settings with the correct tract. Scene recipes use paths
relative to the recipe file and forward slashes whenever possible.

## Rendering

`src/tractfigure/renderer_trame_v1_20260730.py` owns VTK/PyVista actors and
camera state. The Trame module binds UI state to renderer operations; it must not
silently duplicate scientific coordinate conversions. Browser-local UI guides
are excluded from publication PNG exports. Export dimensions come from the
scene canvas and are enforced exactly.

## Platform boundary

Scientific behavior is platform-neutral. Only environment activation and
headless display setup differ:

- Windows: `.venv/Scripts/activate`
- macOS/Linux: `.venv/bin/activate`
- headless Linux rendering: Xvfb

Recipes, inventories, and persisted scene paths must not depend on MobaXTerm
mount syntax or native Windows backslashes.
