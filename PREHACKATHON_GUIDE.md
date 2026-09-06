# TractFigure Studio Hackathon Guide

Welcome!

TractFigure Studio is a cross-platform Python application for loading,
inspecting, rendering, registering, and exporting tractography figures. The
starter repository already includes a working Trame/PyVista viewer, automated
coordinate normalization, scene recipes, affine-registration utilities,
demonstration data scripts, and a few tests.

This guide covers the workflow from cloning the repository through
submitting a pull request.

## 1. Supported systems

The validated environment uses CPython 3.12 and supports:

- Windows 10/11 through local MobaXTerm (my preferred method)
- macOS 15 on Apple Silicon
- macOS 15 on Intel
- Ubuntu Linux

## 2. Clone the starter repository

### Repository collaborator

```bash
git clone https://github.com/gabtaylor1/tractfigure-studio.git
cd tractfigure-studio
```

### Fork contributor

Fork `gabtaylor1/tractfigure-studio` in GitHub, then clone your fork and retain
the original repository as `upstream`:

```bash
git clone https://github.com/<YOUR_GITHUB_USERNAME>/tractfigure-studio.git
cd tractfigure-studio
git remote add upstream https://github.com/gabtaylor1/tractfigure-studio.git
git remote -v
```

Confirm that you are starting from the current validated branch or tag specified
by the hackathon organizers:

```bash
git status
git log -1 --oneline
```

Create a branch for one issue:

```bash
git switch -c issue-<NUMBER>-<SHORT-NAME>
```

Example:

```bash
git switch -c issue-24-glass-brain
```

Keep each branch focused on one GitHub issue. Please coordinate with teammates before
editing the same modules!

## 3. Install uv and create the environment

Use the committed `uv.lock`. All commands after activation use ordinary
`python`; the project workflow does not require `uv run`.

### Windows with local MobaXTerm

Install uv from the MobaXTerm terminal through PowerShell:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
```

Restart MobaXTerm and verify:

```bash
uv.exe --version
git --version
```

If `uv.exe` is unavailable after restarting:

```bash
export PATH="/drives/c/Users/<WINDOWS_USERNAME>/.local/bin:$PATH"
```

From the repository root, use a native Windows temporary directory:

```bash
TF_TEMP='C:/Users/<WINDOWS_USERNAME>/AppData/Local/Temp'

UV_NO_PROGRESS=1 \
TEMP="$TF_TEMP" TMP="$TF_TEMP" TMPDIR="$TF_TEMP" \
uv sync --frozen --all-extras

source .venv/Scripts/activate
```

Windows virtual environments use `.venv/Scripts`.

### macOS

Install the Apple command-line tools when required:

```bash
xcode-select --install
```

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart Terminal. If uv is not yet available:

```bash
source "$HOME/.local/bin/env"
```

Create and activate the environment:

```bash
uv sync --frozen --all-extras
source .venv/bin/activate
```

### Linux

On Ubuntu/Debian, install Git and the OpenGL runtime libraries:

```bash
sudo apt-get update
sudo apt-get install -y git libegl1 libgl1 libopengl0
```

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal. If uv is not yet available:

```bash
source "$HOME/.local/bin/env"
```

Create and activate the environment:

```bash
uv sync --frozen --all-extras
source .venv/bin/activate
```

For headless Linux rendering tests, install Xvfb:

```bash
sudo apt-get install -y xvfb
```

## 4. Verify the environment

Run from the repository root:

```bash
python --version
python -c "import sys; print(sys.executable)"
python -c "import dipy, fury, nibabel, numpy, pyvista, scipy, trame, vtk; print('Imports passed')"
python -c "import vtk; print('VTK', vtk.vtkVersion.GetVTKVersion())"
```

Expected results:

- Python reports version 3.12.x.
- VTK reports version 9.3.x.
- Windows uses `.venv\Scripts\python.exe`.
- macOS and Linux use `.venv/bin/python`.

## 5. Prepare the demonstration data

Run:

```bash
python scripts/fetch_demo_data.py
python scripts/verify_demo_data.py
python scripts/create_demo_recipe.py
```

The fetcher prepares:

- five tractography formats: TRK, TCK, FIB, VTK, and DPY
- the HCP842 atlas
- an MNI ICBM 2009a T1 image

The HCP842 distribution contains 79 tractogram files representing 80 anatomical
bundles (left and right fornix are stored together; learned that the hard way!).

Downloaded files are placed under `demo_data/cache/`. They are excluded from
Git (on purpose).

## 6. Launch the validated starter scene

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8080
```

Open the following address if the browser does not open automatically:

```text
http://localhost:8080
```

Use another port if 8080 is occupied:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8081
```

The starter viewer provides:

- global and individual tract visibility
- sagittal, coronal, and axial slice visibility
- line and tube tract rendering settings
- tract color and opacity settings
- width, radius, and slice controls
- anatomical camera views
- ruler and bounding-box tools
- background-color control settings
- reset-active-tract and reset-all buttons
- scene recipe saving option
- PNG export option

## 7. Understand the scientific contracts

All contributions must preserve the following:

### Coordinates

- Internal streamline coordinates are RAS+ world millimeters (`RASMM`).
- Images retain their NIfTI voxel data and affine.
- Ambiguous tract formats are scored against the supplied reference image.
- Detection decisions, confidence, transforms, bounds, and warnings remain
  inspectable.
- Original input tractograms and images remain immutable.

The implementation is in `src/tractfigure/io.py` and summarized in
`docs/ARCHITECTURE.md`.

### Registration direction

Every public registration matrix maps:

```text
moving RASMM -> fixed RASMM
```

Please preserve this direction in functions, UI labels, saved metadata, tests, and
documentation.

### Scene state

`src/tractfigure/scene_state_v1_20260730.py` is the serialization contract.

### Rendering

`src/tractfigure/renderer_trame_v1_20260730.py` owns the actors, camera state, and
PNG output. `src/tractfigure/gui/app_trame_v1_20260730.py` binds the browser UI to
renderer operations. Coordinate conversion belongs in the scientific I/O layer and nowhere else.

## 8. Repository map

| Path | Responsibility |
| --- | --- |
| `src/tractfigure/io.py` | Loading, coordinate detection, RASMM normalization, inspection |
| `src/tractfigure/vtk_conversion.py` | PyVista/VTK geometry conversion |
| `src/tractfigure/scene_state_v1_20260730.py` | Validated scene models and recipe contract |
| `src/tractfigure/renderer_trame_v1_20260730.py` | Actors, appearance, camera, save, and export |
| `src/tractfigure/gui/app_trame_v1_20260730.py` | Trame controls and application entry point |
| `src/tractfigure/registration.py` | Affine registration, transforms, resampling, and QC |
| `scripts/` | Data, fixture, verification, and rendering workflows |
| `tests/` | Unit, controller, rendering, registration, and integration tests |
| `examples/recipes/` | Portable validated scenes, or "recipes" |
| `docs/reference_renders/` | Human-reviewed visual references |

## 9. Select an issue

Choose an open issue that matches your experience (and/or your interests).

### `neuro`: anatomical presets and tract-palette design

**Goal.** Make anatomically meaningful figures fast and consistent for users
who understand neuroanatomy but do not want to configure every visual parameter themselves.

**Starting point.** The scene model stores tract colors, camera, slice state,
canvas, and active tract. The viewer supports left/right sagittal,
anterior/posterior coronal, and superior/inferior axial views.

**Work.** Define named anatomical presentation presets and a documented tract
palette. (Examples: Orthographic Atlas, Four-view Clinical). Specify tract and slice visibility,
camera orientation, projection, background, opacity, and palette behavior. Add
a preset selector while preserving the source data.

**Relevant files.** `src/tractfigure/scene_state_v1_20260730.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/gui/app_trame_v1_20260730.py`, and
`scripts/render_reference_scenes.py`.

**Acceptance criteria.** Presets are deterministic; laterality is correct;
palette names and HEX values are documented; applying a preset preserves layer
IDs; scene save/reload preserves the result; reference PNGs show the expected
views.

### `registration`: rigid/affine controls and QC overlays

**Goal.** Turn the exisitng registration backend into a safe and inspectable
workflow.

**Starting point.** `src/tractfigure/registration.py` estimates an affine,
resamples images, transforms RASMM streamlines, and creates QC figures.
`scripts/generate_registration_demo.py` supplies deterministic identity, rigid,
and affine cases using the moving-to-fixed transform mentioned in the contract.

**Work.** Add new rigid and full-affine actions, progress and error feedback,
a transform preview, apply/cancel behavior, and before/after slice overlays.

**Relevant files.** `src/tractfigure/registration.py`, the 
scene/renderer/app modules, `scripts/generate_registration_demo.py`, and
`tests/test_registration.py`.

**Acceptance criteria.** Identity leaves coordinates unchanged; rigid mode
performs rigid registration; full-affine mode performs affine registration in 
the moving-RASMM-to-fixed-RASMM direction; cancelling an operation leaves the 
scene unchanged; QC images can be exported.

### `rendering`: glass brain, depth peeling, lighting, and gradients

**Goal.** Add publication-quality rendering while keeping tract identity and
anatomical context legible.

**Starting point.** The renderer owns separate tract and slice actors, supports
line and tube geometry, and exports PNGs.

**Work.** Implement a glass-brain surface option, robust translucent
composition, controllable lighting, and tract gradients.
Add only controls with a visible and testable effect.

**Relevant files.** `src/tractfigure/vtk_conversion.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/scene_state_v1_20260730.py`,
`scripts/render_reference_scenes.py`, and renderer tests.

**Acceptance criteria.** Tracts remain legible during camera rotation;
glass-brain opacity and lighting work in all scene recipes; gradients
stay associated with the correct tract; exports retain requested dimensions on
all CI platforms.

### `ui`: layer cards, linked controls, and global settings

**Goal.** Make large multi-tract scenes manageable while retaining the compact
controls already validated in the starter.

**Starting point.** The viewer has independent tract and slice visibility,
active-layer controls, editable numeric values, tract color/opacity, reset
controls, background color, ruler, bounding box, render-mode controls, and menu
collapse.

**Work.** Build scalable layer cards, filtering or search features, selection,
multi-select/linking, and explicit global-versus-active-layer operations.

**Relevant files.** `src/tractfigure/gui/app_trame_v1_20260730.py`,
`src/tractfigure/scene_state_v1_20260730.py`, and
`tests/test_app_trame_v1_20260730.py`.

**Acceptance criteria.** Scenes with at least 70 layers remain navigable;
single-layer edits affect exactly one layer ID; linked edits affect exactly the
selected IDs; controls do not overlap or clip at normal laptop sizes.

### `api`: deterministic recipe-based rendering

**Goal.** Generate the same figure from a browser, script, or CI job using one
portable scene recipe.

**Starting point.** The starter includes a Pydantic scene contract, portable
path resolution, a renderer, and PNG export.

**Work.** Add a supported headless CLI/API that loads a recipe, validates its
data root, renders requested views, reports provenance, and returns useful exit
codes. Define overwrite and output-naming behavior. Every rendered setting must
come from the recipe or a documented command-line argument.

**Relevant files.** `src/tractfigure/scene_state_v1_20260730.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/gui/app_trame_v1_20260730.py`, and
`scripts/render_reference_scenes.py`.

**Acceptance criteria.** Repeated rendering of the same recipe preserves actor
state, camera, layer order, colors, opacity, canvas size, and output names;
relative paths resolve through a configurable data root; invalid recipes fail
before rendering; a manifest records software versions and input provenance.

### `stretch`: video, nonlinear registration, or DSI `.tt.gz`

**Goal.** These are the really "out-there" features! 
If most or all core issues are resolved quickly, we can start to focus on these.

**Starting point.** Camera state, deterministic frames, affine-transform
direction, multiple tract formats, and recipe export are established.

**Work.** Choose one extension: deterministic turntable/video export; a smooth
nonlinear-registration prototype with deformation provenance; or a documented
DSI Studio `.tt.gz` adapter that converts coordinates into RASMM.

**Relevant files.** Renderer and scene state for video; registration modules
and fixtures for nonlinear work; `src/tractfigure/io.py` and I/O tests for
`.tt.gz`.

**Status.** The `.tt.gz` adapter and a glass-brain mesh layer are implemented;
see "Validate the DSI Studio TinyTrack and glass-brain demo" in section 13.

## 10. Develop within the existing architecture

Before coding:

1. Read the complete GitHub issue.
2. Identify its acceptance criteria and relevant files.
3. Run the existing targeted tests.
4. Capture a baseline screenshot.
5. Agree on file ownership within the team (sounds boring, but it's very important!)

Check changes frequently:

```bash
git status --short
git diff --check
git diff
```

Commit your checkpoints:

```bash
git add <RELEVANT_FILES>
git commit -m "Describe the implemented behavior"
```

## 11. Run targeted tests

Examples:

```bash
python -m pytest tests/test_io.py
python -m pytest tests/test_scene_state_v1_20260730.py
python -m pytest tests/test_app_trame_v1_20260730.py
python -m pytest tests/test_renderer_trame_v1_20260730.py
python -m pytest tests/test_registration.py -m "not integration"
```

Run Ruff on all maintained Python files:

```bash
python -m ruff check src tests scripts
```

If Ruff reports an auto-fixable formatting/import issue:

```bash
python -m ruff check src tests scripts --fix
python -m ruff check src tests scripts
```

Make sure to review the resulting diff.

## 12. Run the full local test gates

Windows, macOS, and Linux desktop:

```bash
python -m pytest -m "not integration"
python -m pytest -m integration
```

Headless Linux:

```bash
xvfb-run -a python -m pytest -m "not integration"
xvfb-run -a python -m pytest -m integration
```

The integration suite requires downloaded data, a verification report, and
registration fixtures. Prepare them with:

```bash
python scripts/verify_demo_data.py
python scripts/generate_registration_demo.py
```

The complete local gate is:

```bash
python scripts/preflight.py
```

On headless Linux:

```bash
xvfb-run -a python scripts/preflight.py
```

## 13. Verify visual changes

Generate the reference-render set when renderer behavior changes:

```bash
python scripts/render_reference_scenes.py
```

On headless Linux:

```bash
xvfb-run -a python scripts/render_reference_scenes.py
```

### Validate the DSI Studio TinyTrack and glass-brain demo

The repository ships a DSI Studio `.tt.gz` bundle, an MNI152 T1, and an MNI152
cortical surface (GIFTI) in `demo_data/dsi/`; no download step is needed. The
`.tt.gz` adapter lives in `src/tractfigure/io.py` (`load_tinytrack`); the
surface is drawn as an optional `mesh` layer with a NiiVue-style `outline`
shader.

Automated checks:

```bash
python -m pytest tests/test_io.py -k tinytrack
python -m pytest tests/test_renderer_trame_v1_20260730.py -k mesh
```

Coordinate check. The bundle is `TR_S_R`, the right superior thalamic
radiation. Loading it against the MNI152 reference must report `embedded
trans_to_mni`, no warnings, and every point inside the image:

```bash
python -c "from tractfigure.io import load_tract_layer; i = load_tract_layer('demo_data/dsi/TR_S_R.tt.gz', 'demo_data/dsi/mni152.nii.gz').inspection; print(i.coordinate_detection, i.point_fraction_inside_reference, i.warnings)"
```

Visual check:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/dsi_tinytrack.json --output-dir outputs
```

- Choose **Coronal A/P**. The bundle must sit in the right hemisphere (viewer's
  left in the anterior view) and fan from thalamus to the superior cortex.
- The **Brain mesh shader** and **Brain mesh opacity** controls appear only when
  a recipe or `--mesh` supplies a surface. With `outline` at opacity 1 the
  cortex renders as opaque silhouette bands with the tracts visible between
  them and no translucency sorting artifacts. Switch to `phong` and lower the
  opacity to compare against the conventional translucent glass brain.
- Cross-check against NiiVue by loading the same three files there with the
  `outline` mesh shader; the bundle location and silhouette pattern should
  match.

### Validate the manual registration demo

`examples/recipes/manual_register.json` shows the DSI Studio bundle and glass
brain over the MNI152 T1 with the "Manual registration" sliders enabled. The
sliders translate (mm), rotate (deg, Euler XYZ) and scale the reference image
about its centre while the tracts and mesh stay fixed, so a deliberately
misaligned image can be dialled back into place by eye. The resulting matrix
maps moving (native) RASMM to fixed (displayed) RASMM, matching the
registration contract, and the nine parameters are stored in the saved scene
under `image.translation_mm`, `image.rotation_deg` and `image.scale`.

Automated check (the matrix is identity by default and pivots on the centre):

```bash
python -m pytest tests/test_renderer_trame_v1_20260730.py -k image_transform
```

Visual check:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/manual_register.json --output-dir outputs
```

- Set **Translate (mm) X** to 30: the slices shift toward the subject's right
  while the red bundle and grey cortex do not move.
- Set **Rotate (deg) Z** to 25: the slices turn about the vertical axis
  through the image centre, so the centre point stays put.
- Set **Scale Y** to 1.3: the slices stretch anterior-posterior from the centre.
- **Reset all settings** returns every slider to identity and the slices to
  their original position. **Save scene** writes the parameters to the recipe.
- Only the reference image is transformed; tracts loaded against that image
  are not re-registered. Use `src/tractfigure/registration.py` to apply the
  same matrix to streamlines when that is needed.

### Validate the independent lighting rigs

The **Lighting** section of the drawer carries two rigs: one for the glass
brain and one for every tract. VTK lights belong to the whole renderer, so a
shared light kit cannot light two groups differently; instead each preset is
compiled into a per-actor fragment shader (`lighting_fragment_shader` in
`src/tractfigure/renderer_trame_v1_20260730.py`) that replaces
`//VTK::Light::Impl` on that group's actors only.

Presets, all defined in view space so they follow the camera:

| Preset | Rig |
| --- | --- |
| `default` | VTK's shared light kit; no shader is injected |
| `headlight` | one lamp on the camera axis - even and shadowless |
| `three_point` | key, dim fill and back light - the standard figure rig |
| `rim` | two back lights against a token key - bright edges, dark body |
| `soft` | a broad, near-matte pair that keeps shading off the layer colours |
| `flat` | unlit; the layer colour, flat |

**Intensity** scales every light in the rig. **Ambient** and **Specular** are
hidden for `default` (VTK is in charge) and for `flat` (unlit), and the whole
glass-brain group is hidden until a recipe or `--mesh` supplies a surface. The
two rigs are saved under `lighting.mesh` and `lighting.tracts` in the recipe,
and **Reset all settings** returns both to `default`.

Automated check:

```bash
python -m pytest tests/test_renderer_trame_v1_20260730.py -k lighting
python -m pytest tests/test_app_trame_v1_20260730.py -k lighting
```

Visual check:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/dsi_tinytrack.json --output-dir outputs
```

- Set **Glass brain lighting -> Preset** to `three_point` and leave the tracts
  on `default`: the cortex gains a key highlight on the upper left and a back
  edge, while the bundle's shading does not change. That is the independence
  the two rigs are for.
- Set **Tract lighting -> Preset** to `flat`: the bundle becomes an unshaded
  block of its own colour, useful when tube shading is competing with a
  colour-coded figure legend. The cortex keeps its three-point rig.
- Set the tracts to `rim` and raise **Intensity**: the tubes darken except at
  their silhouettes, which reads well against a light background.
- `outline` composes with the glass brain's rig: the silhouette test still
  discards the front and back faces, and the surviving band is shaded by the
  chosen preset rather than by the fixed NiiVue lighting.

## 14. Push and open a pull request

Push the issue branch:

```bash
git push -u origin issue-<NUMBER>-<SHORT-NAME>
```

Open a pull request into `main`. Include:

- a concise summary of behavior changes
- files or architectural components affected
- tests run locally
- Windows/macOS/Linux compatibility considerations, if applicable
- a screenshot to two for UI or rendering work

## 15. Common problems

### `.venv/Scripts/activate` is missing on Windows

Confirm the current directory is the repository root:

```bash
pwd
ls .venv/Scripts/python.exe
source .venv/Scripts/activate
```

### `.venv/bin/activate` is missing on macOS/Linux

```bash
pwd
ls .venv/bin/python
source .venv/bin/activate
```

### uv reports a mismatched `VIRTUAL_ENV`

```bash
deactivate 2>/dev/null || true
unset VIRTUAL_ENV
```

Activate the repository environment again using the command for the current
platform.

### A legacy VTK/FIB tract reports low relative confidence

Read the complete inspection report. The verifier requires the selected
candidate to be highest scoring, have an absolute reference-support score of at
least 0.80, produce RASMM coordinates, overlap the reference bounds, and place
tract points inside the reference. Relative ambiguity remains visible as a
warning.

### MobaXTerm prints "weird" or garbled characters

Set:

```bash
export UV_NO_PROGRESS=1
```

## 16. Official references

- uv installation: <https://docs.astral.sh/uv/getting-started/installation/>
- uv project synchronization: <https://docs.astral.sh/uv/concepts/projects/sync/>
- uv GitHub Actions integration: <https://docs.astral.sh/uv/guides/integration/github/>
- DIPY tractography formats: <https://docs.dipy.org/stable/examples_built/file_formats/streamline_formats.html>
- DIPY data interface: <https://docs.dipy.org/stable/reference/dipy.data.html>
- DIPY affine registration: <https://docs.dipy.org/stable/examples_built/registration/affine_registration_3d.html>
- PyVista installation and headless rendering: <https://docs.pyvista.org/getting-started/installation.html>
- Trame application guide: <https://kitware.github.io/trame/guide/tutorial/application.html>
- GitHub pull requests: <https://docs.github.com/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/about-pull-requests>
- GitHub-hosted runners: <https://docs.github.com/actions/using-jobs/choosing-the-runner-for-a-job>
