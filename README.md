# TractFigure Studio

Figure-oriented tractography visualization and registration starter for Vanderbilt BrainHack 2026.

The validated runtime is CPython 3.12. The committed `uv.lock` resolves native
wheels for Windows, macOS Apple Silicon, macOS Intel, and Linux.

## Start here

To begin, please follow the instructions in `PREHACKATHON_GUIDE.md` from beginning to end.

The stable coordinate, transform-direction, scene-state, and rendering rules are
summarized in `docs/ARCHITECTURE.md`.

## After installing and activating the environment

Launch the tool with one command — no arguments, no downloads. It opens the
bundled quickstart scene (MNI152 T1, DSI Studio bundle, glass brain):

```bash
tractfigure-gui
```

Point it at your own data instead, or load it in the browser with the image and
tract open controls:

```bash
tractfigure-gui --reference t1.nii.gz --tractogram bundle.tck --tractogram bundles/ --mesh surf.gii
tractfigure-gui --recipe examples/recipes/five_bundle_trame_v1_20260730.json
```

Open `http://localhost:8080` if the browser does not open automatically.

For the full demonstration datasets and the validated five-bundle scene:

```bash
python scripts/fetch_demo_data.py
python scripts/verify_demo_data.py
python scripts/create_demo_recipe.py
python scripts/generate_registration_demo.py
python scripts/preflight.py
```

Launch the validated five-bundle scene:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8080
```

Open `http://localhost:8080` if the browser does not open automatically.

## DSI Studio TinyTrack and glass brain demo

Loads a DSI Studio `.tt.gz` bundle over a translucent MNI152 cortical mesh:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/dsi_tinytrack.json \
  --output-dir outputs
```

Data is committed in `demo_data/dsi/` (not fetched by `scripts/fetch_demo_data.py`);
licenses in `DATA_LICENSES.md`. Validation steps: `PREHACKATHON_GUIDE.md`, section 13,
"Validate the DSI Studio TinyTrack and glass-brain demo".

## Erode and diffuse the brain surface

The `+1mm Erode` and `-1mm Diffuse` buttons below the slice opacity slider
regenerate the glass-brain surface from the reference volume with
[niimath](https://github.com/rordenlab/niimath), which ships with the `viz`
extra:

```bash
niimath <reference> -erode <isolevel> <mm> -mesh -i <isolevel> -b 1 <surface.gii>
```

Each press moves a signed millimeter counter by one and re-renders; positive
offsets erode, negative offsets dilate, and the range is clamped to ±10 mm. Both
morphology operators binarize at a threshold, so the threshold is pinned to the
isosurface niimath extracts the unmodified volume at — a threshold below it
would shave background voxels without moving the visible surface. Generated
surfaces are cached under `<output-dir>/surface_cache/`, keyed by the contents
of the reference volume, so revisiting an offset is instant.

Set `TRACTFIGURE_NIIMATH` to use a niimath executable that is not installed
beside the interpreter or on `PATH`.

## Manual registration demo

Translate, rotate and scale the reference image against fixed tracts and glass
brain with the "Manual registration" sliders:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/manual_register.json \
  --output-dir outputs
```

The nine parameters are saved with the scene. Validation steps:
`PREHACKATHON_GUIDE.md`, section 13, "Validate the manual registration demo".
