# TractFigure Studio Hackathon Student Guide

TractFigure Studio is a cross-platform Python application for loading,
inspecting, rendering, registering, and exporting tractography figures. The
starter repository already includes a working Trame/PyVista viewer, automated
coordinate normalization, scene recipes, affine-registration utilities,
demonstration data scripts, tests, and continuous integration.

This guide covers the student workflow from cloning the repository through
submitting a pull request.

## 1. Supported systems

The validated environment uses CPython 3.12 and supports:

- Windows 10/11 through local MobaXTerm
- macOS 15 on Apple Silicon
- macOS 15 on Intel
- Ubuntu Linux

The same scientific code and scene recipes are used on every platform.
Environment activation and Linux display setup are the platform-specific parts.

## 2. Clone the starter repository

Use the workflow specified by the hackathon organizers.

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

Keep each branch focused on one GitHub issue. Coordinate with teammates before
editing the same modules.

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
bundles because the left and right fornix are stored together.

Downloaded files are placed under `demo_data/cache/`. They are excluded from
Git. The generated inventory and verification report describe file paths,
hashes, image geometry, detected coordinates, bounds, and reference overlap.

If the organizers provide a populated data cache, the fetcher will reuse it.

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
- line and tube tract rendering
- tract color and opacity
- numeric width, radius, and slice controls
- anatomical camera views and perspective mode
- ruler and bounding-box tools
- background-color control
- reset-active-tract and reset-all controls
- scene recipe saving
- exact-size PNG export

## 7. Understand the scientific contracts

All contributions must preserve the following contracts.

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

Preserve this direction in functions, UI labels, saved metadata, tests, and
documentation.

### Scene state

`src/tractfigure/scene_state_v1_20260730.py` is the serialization contract.
Layer IDs associate visibility, colors, opacity, rendering options, and order
with the correct tract. Shared recipes use relative paths with forward slashes.

### Rendering

`src/tractfigure/renderer_trame_v1_20260730.py` owns actors, camera state, and
PNG output. `src/tractfigure/gui/app_trame_v1_20260730.py` binds the browser UI to
renderer operations. Coordinate conversion belongs in the scientific I/O layer.

## 8. Repository map

| Path | Responsibility |
| --- | --- |
| `src/tractfigure/io.py` | Loading, coordinate detection, RASMM normalization, inspection |
| `src/tractfigure/vtk_conversion.py` | PyVista/VTK geometry conversion |
| `src/tractfigure/scene_state_v1_20260730.py` | Validated scene models and recipe contract |
| `src/tractfigure/renderer_trame_v1_20260730.py` | Actors, appearance, camera, save, and export |
| `src/tractfigure/gui/app_trame_v1_20260730.py` | Trame controls and application entry point |
| `src/tractfigure/registration.py` | Affine registration, transforms, resampling, and QC |
| `scripts/` | Reproducible data, fixture, verification, and rendering workflows |
| `tests/` | Unit, controller, rendering, registration, and integration tests |
| `examples/recipes/` | Portable validated scenes |
| `docs/reference_renders/` | Human-reviewed visual references |

Keep the three canonical v1 module names unchanged during the hackathon.

## 9. Select an issue

Choose an open issue whose acceptance criteria match your team's experience.
The GitHub issue is the task specification if it narrows the scope below. The
labels and project boundaries below describe the prepared hackathon tracks.

The starter already provides installation, data fetching, automatic coordinate
detection, independent visibility, reset behavior, scene save/export, portable
recipes, registration fixtures, tests, reference renders, and four-platform CI.
Treat failures in those baseline behaviors as regressions and report them to the
maintainers instead of absorbing them into a feature issue.

### `neuro`: anatomical presets and tract-palette design

**Goal.** Make anatomically meaningful figures fast and consistent for users
who understand neuroanatomy but do not want to configure every visual parameter.

**Starting point.** The scene model stores tract colors, camera, slice state,
canvas, and active tract. The viewer supports left/right sagittal,
anterior/posterior coronal, and superior/inferior axial views.

**Work.** Define named anatomical presentation presets and a documented tract
palette. Candidate presets are Black Glass, White Anatomy, Orthographic Atlas,
Transparent Figure, and Four-View Clinical. Specify tract and slice visibility,
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

**Suggested background.** Neuroanatomy, diffusion MRI, scientific
illustration, or visual design. Registration implementation is outside this
issue.

### `registration`: rigid/affine controls and QC overlays

**Goal.** Turn the validated registration backend into a safe and inspectable
workflow.

**Starting point.** `src/tractfigure/registration.py` estimates an affine,
resamples images, transforms RASMM streamlines, and creates QC figures.
`scripts/generate_registration_demo.py` supplies deterministic identity, rigid,
and affine cases using the moving-to-fixed transform contract.

**Work.** Add rigid and full-affine actions, progress and error feedback,
transform preview, apply/cancel behavior, and before/after slice overlays.
Display matrix direction, prevent repeated accidental application, retain the
original inputs, and cache transformed derivatives.

**Relevant files.** `src/tractfigure/registration.py`, the three canonical v1
scene/renderer/app modules, `scripts/generate_registration_demo.py`, and
`tests/test_registration.py`.

**Acceptance criteria.** Identity leaves coordinates unchanged; rigid mode
adds no scale or shear; full affine follows the moving-RASMM-to-fixed-RASMM
direction; resampled images use fixed-image geometry; known fixtures improve
alignment within a documented tolerance; cancel leaves the scene unchanged; QC
images can be exported.

**Suggested background.** Image registration, medical imaging, numerical
optimization, or scientific Python.

### `rendering`: glass brain, depth peeling, lighting, and gradients

**Goal.** Add publication-quality depth cues while keeping tract identity and
anatomical context legible.

**Starting point.** The renderer owns separate tract and slice actors, supports
line and true tube geometry, exports exact-size PNGs, and excludes the
orientation guide from exported figures.

**Work.** Implement a glass-brain surface option, robust translucent
composition, controllable lighting, and tract gradients. Keep line mode free of
point markers. Add only controls with a visible and testable effect.

**Relevant files.** `src/tractfigure/vtk_conversion.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/scene_state_v1_20260730.py`,
`scripts/render_reference_scenes.py`, and renderer tests.

**Acceptance criteria.** Tracts remain legible during camera rotation;
transparent composition has stable ordering or a documented fallback;
glass-brain opacity and lighting round-trip through scene recipes; gradients
stay associated with the correct tract; exports retain requested dimensions on
all CI platforms.

**Suggested background.** VTK/PyVista, computer graphics, scientific
visualization, or visual design.

### `ui`: layer cards, linked controls, and global settings

**Goal.** Make large multi-tract scenes manageable while retaining the compact
controls already validated in the starter.

**Starting point.** The viewer has independent tract and slice visibility,
active-layer controls, editable numeric values, tract color/opacity, reset
controls, background color, ruler, bounding box, render-mode controls, and menu
collapse.

**Work.** Build scalable layer cards, filtering or search, selection,
multi-select/linking, and explicit global-versus-active-layer operations.
Preserve color-coded toggles and ensure component IDs never share unrelated
state.

**Relevant files.** `src/tractfigure/gui/app_trame_v1_20260730.py`,
`src/tractfigure/scene_state_v1_20260730.py`, and
`tests/test_app_trame_v1_20260730.py`.

**Acceptance criteria.** Scenes with at least 80 layers remain navigable;
single-layer edits affect exactly one layer ID; linked edits affect exactly the
selected IDs; controls do not overlap or clip at normal laptop sizes; keyboard
and color controls are labeled; menu collapse remains available; reset
semantics remain unchanged.

**Suggested background.** Front-end development, Trame/Vue/Vuetify, UX, or
accessibility.

### `api`: deterministic recipe-based rendering

**Goal.** Generate the same figure from a browser, script, or CI job using one
portable scene recipe.

**Starting point.** The starter includes a Pydantic scene contract, portable
path resolution, a renderer, and exact-size PNG export.

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

**Suggested background.** Python API/CLI design, reproducible research, or CI.

### `testing`: coordinate and rendering validation

**Goal.** Expand confidence from the supplied fixtures to realistic edge cases
using stable scientific and state invariants.

**Starting point.** The suite covers automatic source-space detection, origin
shifts, world bounds, scene/controller state, independent actors, registration
direction, offscreen output, and four-platform CI.

**Work.** Add adversarial coordinate fixtures, oblique affines, malformed
files, larger layer counts, camera round-trips, transparency cases, and
stateful UI regressions. Keep fixtures small and generate them when practical.

**Relevant files.** `tests/`, `src/tractfigure/io.py`,
`src/tractfigure/vtk_conversion.py`, and the three canonical v1 modules.

**Acceptance criteria.** Failures have actionable messages; fixtures are small
and licensed or generated; deterministic tests cover transform direction,
finite coordinates, bounds, actors, visibility, camera, output dimensions, and
portable recipes; the complete CI matrix remains green. Pixel-perfect equality
across VTK drivers is outside this issue.

**Suggested background.** Testing, neuroimaging formats, QA, or scientific
software engineering.

### `stretch`: video, nonlinear registration, or DSI `.tt.gz`

**Goal.** Complete one bounded advanced extension after your team finishes and
tests a core issue.

**Starting point.** Camera state, deterministic frames, affine-transform
direction, multiple tract formats, and recipe export are established.

**Work.** Choose one extension: deterministic turntable/video export; a smooth
nonlinear-registration prototype with deformation provenance; or a documented
DSI Studio `.tt.gz` adapter that converts coordinates into RASMM.

**Relevant files.** Renderer and scene state for video; registration modules
and fixtures for nonlinear work; `src/tractfigure/io.py` and I/O tests for
`.tt.gz`.

**Acceptance criteria.** Video defines frame size, rate, camera path, and
reproducible frame order; nonlinear registration distinguishes forward and
inverse deformation and includes a generated fixture; `.tt.gz` loading validates
finite coordinates, reference overlap, and licensing. Every extension preserves
the scene contract and original inputs.

**Suggested background.** Advanced visualization, image registration, media
encoding, or binary file formats.

## 10. Develop within the existing architecture

Before coding:

1. Read the complete GitHub issue.
2. Identify its acceptance criteria and relevant files.
3. Run the existing targeted tests.
4. Capture a baseline screenshot or output when visual behavior is changing.
5. Agree on file ownership within the team.

During development:

- Add or update tests with each behavior change.
- Preserve stable layer IDs.
- Keep paths platform-neutral.
- Use `pathlib.Path` for filesystem paths.
- Keep scientific operations outside browser callbacks where practical.
- Avoid modifying input data in place.
- Avoid auxiliary marker files and per-subject logs.
- Keep generated data, environments, caches, and ordinary outputs outside Git.
- Keep commits small and descriptive.

Check changes frequently:

```bash
git status --short
git diff --check
git diff
```

Commit a coherent checkpoint:

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

If Ruff reports an explicitly auto-fixable formatting/import issue:

```bash
python -m ruff check src tests scripts --fix
python -m ruff check src tests scripts
```

Review the resulting diff.

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

For UI or rendering work, confirm the following manually:

1. One tract toggle changes one tract.
2. The global tract toggle changes all tracts.
3. Slice toggles remain independent.
4. Active-tract controls remain associated with the selected tract.
5. Line mode has no visible nodes.
6. Anatomical view buttons preserve laterality and alternate viewing side.
7. Camera reset works after perspective interaction.
8. Reset-active changes one tract.
9. Reset-all restores the complete initial scene promptly.
10. Scene saving produces reloadable JSON.
11. PNG export has the requested dimensions.
12. The orientation guide is absent from exported PNGs.
13. Controls remain usable at ordinary laptop viewport sizes.

Generate the reference-render set when renderer behavior changes:

```bash
python scripts/render_reference_scenes.py
```

On headless Linux:

```bash
xvfb-run -a python scripts/render_reference_scenes.py
```

Discuss intentional reference-image changes with the issue lead before
committing them.

## 14. Push and open a pull request

Push the issue branch:

```bash
git push -u origin issue-<NUMBER>-<SHORT-NAME>
```

Open a pull request into `main`. Include:

- the linked issue number
- a concise summary of behavior changes
- files or architectural components affected
- tests run locally
- Windows/macOS/Linux compatibility considerations
- screenshots for UI or rendering work
- recipe/schema migration details when applicable
- known limitations

GitHub Actions runs the suite on:

- Ubuntu Linux
- Windows
- macOS Apple Silicon
- macOS Intel

All required jobs must pass. Review failed-job logs and update the same branch;
new commits automatically update its pull request.

## 15. Pull-request checklist

- [ ] The issue acceptance criteria are met.
- [ ] Scientific coordinate and transform contracts are preserved.
- [ ] Original data remain unchanged.
- [ ] New behavior has automated coverage.
- [ ] Ruff passes.
- [ ] Non-integration tests pass.
- [ ] Relevant integration tests pass.
- [ ] Manual visual checks pass when applicable.
- [ ] Recipes use portable paths.
- [ ] Generated caches and routine outputs are absent from Git.
- [ ] Documentation describes user-visible behavior.
- [ ] Four-platform GitHub Actions checks pass.

## 16. Common problems

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

### Port 8080 is occupied

Use `--app-port 8081` or another available unprivileged port.

### The verification report is missing

```bash
python scripts/fetch_demo_data.py
python scripts/verify_demo_data.py
```

### A legacy VTK/FIB tract reports low relative confidence

Read the complete inspection report. The verifier requires the selected
candidate to be highest scoring, have an absolute reference-support score of at
least 0.80, produce RASMM coordinates, overlap the reference bounds, and place
tract points inside the reference. Relative ambiguity remains visible as a
warning.

### MobaXTerm prints garbled progress characters

Set:

```bash
export UV_NO_PROGRESS=1
```

This affects terminal display only.

## 17. Official references

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
