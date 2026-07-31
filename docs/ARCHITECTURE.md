# Architecture contract

## Coordinates

- Images retain their NIfTI voxel data and affine.
- Loaded streamlines are normalized to RAS+ world coordinates in millimeters
  (`RASMM`).
- Ambiguous source conventions are detected by scoring plausible transforms
  against the supplied reference image; the selected convention, score,
  confidence, bounds, and warnings are retained in the layer inspection report.

## Transform direction

Every public registration matrix maps:

```text
moving RASMM -> fixed RASMM
```

Image resampling internally computes the inverse sampling relationship required
to populate the fixed output grid.

## Scene state

`src/tractfigure/scene_state_v1_20260730.py` is the serialization contract.
Layer order and stable layer IDs associate visibility, color, opacity, render
mode, and geometry settings with the correct tract.

## Rendering

`src/tractfigure/renderer_trame_v1_20260730.py` owns the VTK/PyVista actors and
camera state.

## Platform boundary

Scientific behavior is platform-neutral, but environment activation and
headless display setup differ slightly:

- Windows: `.venv/Scripts/activate`
- macOS/Linux: `.venv/bin/activate`
- headless Linux rendering (just in case we need it): Xvfb
