# TractFigure Studio pre-hackathon implementation guide

This is the complete baseline procedure for the weekend hackathon. Paths in
backticks are relative to the root of this bundle and to the root of the Git
repository after you place the files there. The bundle contains complete files,
not patches. It does not alter a repository by itself.

The required student-facing platforms are:

- Windows 10/11, including local MobaXTerm Bash
- macOS 15 on Apple Silicon
- macOS 15 on Intel
- current x86-64 Ubuntu Linux

Use CPython 3.12 everywhere. Do not use `uv run` in the documented workflow.
Synchronize once, activate the virtual environment, and run ordinary `python`
commands.

## 1. Understand what the bundle replaces and adds

Back up the current repository before replacing files. Preserve the bundle's
directory structure and use these exact canonical names.

### Complete replacement files

| Bundle path | Purpose |
| --- | --- |
| `pyproject.toml` | Runtime/dev dependency ranges, Python 3.12, package metadata, test markers, lint configuration |
| `uv.lock` | Frozen, cross-platform dependency solution |
| `.python-version` | Requests Python 3.12 from uv |
| `.gitignore` | Excludes environments, caches, downloaded data, generated registration fixtures, and outputs |
| `.github/workflows/ci.yml` | Ubuntu, Windows, macOS ARM, and macOS Intel validation |
| `README.md` | Short project entry point |
| `IMPLEMENTATION_ORDER.md` | Compact checklist pointing to this guide |
| `DATA_LICENSES.md` | Downloaded-data attribution and redistribution notes |
| `demo_data/manifest.toml` | Dataset DOI, license, and space declarations |
| `docs/ARCHITECTURE.md` | Coordinate, transform-direction, state, rendering, and platform contracts |
| `src/tractfigure/io.py` | Automated tract coordinate detection, RASMM normalization, inspection reports |
| `src/tractfigure/vtk_conversion.py` | Streamline and anatomical-slice conversion for PyVista/VTK |
| `src/tractfigure/scene_state_v1_20260730.py` | Stable Pydantic scene contract |
| `src/tractfigure/renderer_trame_v1_20260730.py` | Rendering, camera, visibility, reset, scene save, and exact-size PNG export |
| `src/tractfigure/gui/app_trame_v1_20260730.py` | Trame application, menus, color/opacity controls, anatomical views, browser downloads |

### New implementation files

| Bundle path | Purpose |
| --- | --- |
| `src/tractfigure/registration.py` | Affine estimation, tract transformation, image resampling, and QC figure generation |
| `scripts/fetch_demo_data.py` | Downloads the five-format example, HCP842 atlas, and MNI2009a T1; writes a portable inventory |
| `scripts/verify_demo_data.py` | Checks files, hashes, image geometry, coordinate detection, RASMM normalization, and tract/reference overlap |
| `scripts/create_demo_recipe.py` | Generates the canonical portable five-bundle recipe |
| `scripts/generate_registration_demo.py` | Creates identity, rigid, and affine ground-truth fixtures |
| `scripts/render_reference_scenes.py` | Produces the controlled reference-render set |
| `scripts/preflight.py` | Runs the combined release gate after data have been fetched |
| `tests/test_io.py` | Coordinate transforms, half-voxel origins, bounds, and automatic LPSMM detection |
| `tests/test_vtk_conversion.py` | PolyData and NIfTI-to-VTK geometry tests |
| `tests/test_scene_state_v1_20260730.py` | Scene validation and JSON round-trip tests |
| `tests/test_renderer_trame_v1_20260730.py` | Actors, independent toggles, views, reset, portable save, and PNG-size tests |
| `tests/test_app_trame_v1_20260730.py` | CLI, controller, color/opacity, numeric input, reset, save, and export tests |
| `tests/test_registration.py` | Identity, known-affine direction, fixed geometry, optimization, and generated-fixture tests |
| `tests/test_demo_data.py` | Five-format, HCP842, and verification-report integration tests |

Keep the internal v1 filenames exactly as shown. The downloadable archive can
have a unique versioned name, but imports and entry points must continue to use
the three canonical v1 modules.

## 2. Install Git and uv on each platform

Run all later commands from the repository root.

### Windows using local MobaXTerm

MobaXTerm is a Bash-like terminal controlling native Windows programs. The
environment therefore uses `.venv/Scripts`, not `.venv/bin`.

Install uv through native PowerShell:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen MobaXTerm, then verify:

```bash
uv.exe --version
git --version
```

Only if `uv.exe` is not found, add its normal Windows install directory for the
current shell:

```bash
export PATH="/drives/c/Users/<WINDOWS_USERNAME>/.local/bin:$PATH"
uv.exe --version
```

Keep the repository in a persistent Windows directory such as:

```text
C:\Users\<WINDOWS_USERNAME>\Desktop\tractfigure-studio
```

In MobaXTerm that path is:

```text
/drives/c/Users/<WINDOWS_USERNAME>/Desktop/tractfigure-studio
```

Do not use MobaXTerm's emulated `/tmp` for uv. Define a native Windows temporary
directory before synchronization:

```bash
TF_TEMP='C:/Users/<WINDOWS_USERNAME>/AppData/Local/Temp'
```

If GitHub authentication is needed from MinTTY, use `winpty gh.exe auth login
--hostname github.com --git-protocol https --web`. That is a Git authentication
concern only; it is not part of running the application.

### macOS

Open Terminal in a logged-in desktop session. Install command-line Git if it is
not already present:

```bash
xcode-select --install
```

If macOS reports that the tools are already installed, continue. Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new Terminal window. If `uv` is not immediately available, load the
installer-created environment file:

```bash
source "$HOME/.local/bin/env"
```

Verify:

```bash
uv --version
git --version
uname -m
```

`uname -m` normally reports `arm64` on Apple Silicon and `x86_64` on an Intel
Mac. Do not run Terminal through Rosetta on Apple Silicon unless there is a
specific compatibility reason; the lockfile contains native ARM wheels.

### Linux

Install Git and basic OpenGL libraries. On Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y git libegl1 libgl1 libopengl0
```

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new shell, or if necessary:

```bash
source "$HOME/.local/bin/env"
```

Verify:

```bash
uv --version
git --version
```

For a headless Linux CI host, also install Xvfb:

```bash
sudo apt-get install -y xvfb
```

Windows and macOS do not use Xvfb.

## 3. Create the frozen environment

The included `pyproject.toml` pins compatible release families and the included
`uv.lock` freezes the exact solution. In particular, FURY 0.12 requires VTK
below 9.4, so this baseline uses VTK 9.3.x. VTK 9.3.1 publishes CPython 3.12
wheels for Windows, Linux, macOS ARM, and macOS Intel.

Do not run `uv lock` during normal setup. That would re-resolve the environment.
Use `--frozen` so an accidental mismatch between `pyproject.toml` and `uv.lock`
fails visibly.

### Windows/MobaXTerm

```bash
TF_TEMP='C:/Users/<WINDOWS_USERNAME>/AppData/Local/Temp'
TEMP="$TF_TEMP" TMP="$TF_TEMP" TMPDIR="$TF_TEMP" uv sync --frozen --all-extras
source .venv/Scripts/activate
```

### macOS

```bash
uv sync --frozen --all-extras
source .venv/bin/activate
```

### Linux

```bash
uv sync --frozen --all-extras
source .venv/bin/activate
```

The activated prompt should show `tractfigure-studio`. Verify the interpreter
and major dependencies on every platform:

```bash
python --version
python -c "import sys; print(sys.executable)"
python -c "import dipy, fury, nibabel, numpy, pyvista, scipy, trame, vtk; print('Imports passed')"
python -c "import vtk; print('VTK', vtk.vtkVersion.GetVTKVersion())"
```

Expected results:

- Python reports 3.12.x.
- Windows shows an executable under `.venv\Scripts\python.exe`.
- macOS/Linux show an executable under `.venv/bin/python`.
- VTK reports 9.3.x.

If the Windows environment is missing `bin`, nothing is wrong: Windows virtual
environments use `Scripts`. If synchronization fails while removing an
`uv-trampoline-*.exe`, close Python/uv processes, keep the native `TF_TEMP`
settings above, and retry. Do not delete a working repository.

## 4. Fetch the complete demonstration data

Run:

```bash
python scripts/fetch_demo_data.py
```

The bundled `scripts/fetch_demo_data.py` calls DIPY's supported fetchers for:

- the five-format tractography example (`.trk`, `.tck`, `.fib`, `.vtk`, `.dpy`)
- the HCP842 80-bundle atlas
- the ICBM 2009a T1 template

It stores downloads below `demo_data/cache/` and writes
`demo_data/data_inventory.json`. Inventory paths use forward slashes and are
relative to the project root, so the inventory is consumable on Windows,
macOS, and Linux.

The first run requires internet access and may be substantial. For the event,
run this before students arrive and preserve the completed cache on a shared
drive or in a documented prebuilt environment. Do not commit third-party data
unless its redistribution terms and repository-size implications have been
reviewed. Keep `demo_data/manifest.toml` and `DATA_LICENSES.md` committed.

Successful output reports five format examples, 79 HCP842 tractogram files
representing 80 anatomical bundles, and the MNI2009a T1. The file count is 79
because the atlas stores the left and right fornix together in one tractogram.

## 5. Verify data and coordinate handling

Run:

```bash
python scripts/verify_demo_data.py
```

The bundled `scripts/verify_demo_data.py` verifies:

- required files exist and are nonempty
- SHA-256 hashes can be computed
- reference NIfTI files are readable, finite, 3D, and have nonsingular affines
- image shape, voxel size, orientation codes, and affine are recorded
- all five tract formats load
- every loaded tract is normalized to RAS+ world millimeters (`RASMM`)
- automatic coordinate detection selects its highest-scoring interpretation
  with adequate absolute reference support
- tract bounds overlap the reference-image world bounds
- at least some tract points fall within the reference volume
- the HCP842 inventory contains exactly 79 tractogram files representing 80
  anatomical bundles

The report is written to `demo_data/verification_report.json`. Inspect the
`source_space`, `source_origin`, `coordinate_detection`, `detection_confidence`,
`point_fraction_inside_reference`, and `warnings` fields for every format.

The implementation in `src/tractfigure/io.py` does not ask students to choose a
source space. For formats with reliable headers, it uses the declared geometry.
For ambiguous legacy formats, it scores plausible RASMM, LPSMM, voxel, and
origin conventions against the supplied NIfTI reference, chooses the strongest
candidate, records the transform, and warns or fails when the result is not
credible. This is general reference-driven detection, not a filename-specific
table for the demonstration data.

Low relative confidence is retained as a warning when two conventions both fit
the reference closely. Verification still requires the selected candidate to be
the highest-scoring interpretation, an absolute reference-support score of at
least 0.80, finite coordinates, RASMM output, world-bounds overlap, and tract
points inside the reference. This handles intrinsically ambiguous, nearly
left-right-symmetric anatomy without discarding the detector's warning.

## 6. Generate and validate the canonical scene recipe

Run:

```bash
python scripts/create_demo_recipe.py
```

The bundled `scripts/create_demo_recipe.py` reads the verified inventory and
writes:

```text
examples/recipes/five_bundle_trame_v1_20260730.json
```

The recipe uses:

- one image layer at full opacity
- five independently identified and colored tract layers
- a 1400 by 1000 canvas
- a white background
- paths relative to the recipe directory, serialized with forward slashes

The portable path rule matters: a recipe produced on Windows can be committed
and read on macOS/Linux, and the reverse is also true. The corresponding model
and validation rules live in `src/tractfigure/scene_state_v1_20260730.py`.

The renderer's Save Scene operation in
`src/tractfigure/renderer_trame_v1_20260730.py` also writes forward-slash paths
relative to the output recipe where possible. On Windows, files on different
drive letters cannot be expressed as a relative path; in that exceptional case
the source computer's absolute path is retained and should be corrected before
sharing the recipe.

## 7. Generate registration fixtures

Run:

```bash
python scripts/generate_registration_demo.py
```

The bundled `scripts/generate_registration_demo.py` creates three deterministic
cases under `demo_data/registration/`:

- `identity`
- `rigid`
- `affine`

Each case contains:

- `fixed.nii.gz`
- `moving.nii.gz`
- fixed-space and moving-space `.trk` copies of every example bundle
- `ground_truth_moving_to_fixed.txt`
- `fixture_metadata.json`
- `registration_qc.png`

All saved matrix metadata uses one explicit direction:

```text
moving RASMM -> fixed RASMM
```

The bundled `src/tractfigure/registration.py` provides the baseline API:

- `register_affine(moving, fixed)`
- `apply_affine_to_streamlines(streamlines, moving_to_fixed)`
- `resample_image_to_fixed(moving, fixed, moving_to_fixed)`
- `registration_qc_figure(...)`

`register_affine` inverts DIPY's returned sampling transform so the public
matrix follows the documented moving-to-fixed direction. Preserve that
contract in all GUI and hackathon work.

Open the three `registration_qc.png` files. The identity case should be
unchanged. The rigid and affine cases should visibly improve after application
of the supplied ground truth. Generated fixtures are excluded from Git because
they are reproducible.

## 8. Run the tests in useful stages

Run lint first:

```bash
python -m ruff check src tests scripts
```

If Ruff reports only auto-fixable import ordering, the safe mechanical command
is:

```bash
python -m ruff check src tests scripts --fix
python -m ruff check src tests scripts
```

Review any changed source before committing.

### Fast unit and renderer gate

Windows/MobaXTerm and macOS:

```bash
python -m pytest -m "not integration"
```

Linux desktop:

```bash
python -m pytest -m "not integration"
```

Headless Linux:

```bash
xvfb-run -a python -m pytest -m "not integration"
```

This exercises the I/O model, scene model, UI controller, VTK conversion,
registration optimization, offscreen rendering, independent tract and slice
visibility, line-mode node suppression, camera reset, anatomical flip views,
scene save, and exact-size PNG export. The renderer test also checks that the
orientation guide is hidden from exported PNGs and restored afterward.

### Integration gate

After data verification and fixture generation:

Windows/MobaXTerm, macOS, and Linux desktop:

```bash
python -m pytest -m integration
```

Headless Linux:

```bash
xvfb-run -a python -m pytest -m integration
```

This gate checks all five demonstration formats, the 80-bundle inventory, the
verification report, and all registration fixture products.

### One-command release gate

After the data have already been fetched, run:

Windows/MobaXTerm and macOS:

```bash
python scripts/preflight.py
```

Linux desktop:

```bash
python scripts/preflight.py
```

Headless Linux must supply its display wrapper because `scripts/preflight.py`
launches rendering tests internally:

```bash
xvfb-run -a python scripts/preflight.py
```

The bundled `scripts/preflight.py` verifies canonical filenames, rejects known
temporary development-name fragments, runs Ruff, runs non-integration tests,
re-verifies data, recreates the recipe and registration fixtures, runs
integration tests, and generates reference scenes. It intentionally does not
fetch data: network download and scientific validation are separate operations.

## 9. Launch and manually verify the application

Use the portable recipe rather than shell variables containing platform-specific
paths:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8080
```

This command is identical in MobaXTerm, macOS Terminal, and Linux Bash. Open:

```text
http://localhost:8080
```

if a browser does not open automatically. If port 8080 is already occupied,
choose another unprivileged port such as `--app-port 8081`.

The browser should show:

- a white scene background
- three fully opaque anatomical slices
- five color-coded tract toggles and one global tract toggle
- independent sagittal, coronal, and axial slice toggles
- one active-tract control area
- tract color with HEX input and opacity in the tract color panel
- line and tube render modes without visible streamline nodes in line mode
- editable numeric values beside applicable sliders
- bounding-box, ruler, local/remote rendering, and menu-collapse controls
- sagittal, coronal, and axial camera buttons that flip side on the second click
- one working reset-camera control
- reset-active-tract and reset-all-settings controls
- background color under scene settings after active-tract settings
- working Save Scene and Export PNG browser downloads

Perform this manual smoke test:

1. Toggle one tract off; verify the other four stay visible.
2. Toggle all tracts off and on.
3. Toggle each anatomical slice independently.
4. Switch the active tract and change its color, opacity, and render mode.
5. Type a numeric width or radius, including clearing and replacing the field.
6. Verify blank/invalid input restores the previous valid value on blur.
7. Click sagittal twice and verify left/right reversal; repeat for coronal and axial.
8. Enter perspective mode, rotate and zoom, then use Reset Camera.
9. Change the background color.
10. Toggle the ruler and bounding box.
11. Reset the active tract; verify other tracts remain unchanged.
12. Change several scene values and use Reset All Settings; verify the reset completes promptly.
13. Save a scene and confirm a JSON download plus a copy under `outputs/`.
14. Export a PNG and confirm it is exactly 1400 by 1000 pixels.
15. Confirm the bottom-right orientation guide is not present in the exported PNG.

Also launch once from explicit inputs to validate CLI parsing:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --reference demo_data/cache/bundle_file_formats_example/template0.nii.gz \
  --tractogram demo_data/cache/bundle_file_formats_example/cc_m_sub.trk \
  --tractogram demo_data/cache/bundle_file_formats_example/laf_m_sub.tck \
  --tractogram demo_data/cache/bundle_file_formats_example/lpt_m_sub.fib \
  --tractogram demo_data/cache/bundle_file_formats_example/raf_m_sub.vtk \
  --tractogram demo_data/cache/bundle_file_formats_example/rpt_m_sub.dpy \
  --output-dir outputs \
  --app-port 8081
```

Do not combine `--recipe` with `--reference` or `--tractogram`. The CLI rejects
that ambiguous combination intentionally.

## 10. Generate and inspect reference renders

Run:

Windows/MobaXTerm and macOS:

```bash
python scripts/render_reference_scenes.py
```

Linux desktop:

```bash
python scripts/render_reference_scenes.py
```

Headless Linux:

```bash
xvfb-run -a python scripts/render_reference_scenes.py
```

The bundled `scripts/render_reference_scenes.py` writes:

- `docs/reference_renders/white_publication.png`
- `docs/reference_renders/black_tracts.png`
- `docs/reference_renders/orthographic_sagittal_left.png`
- `docs/reference_renders/orthographic_coronal_anterior.png`
- `docs/reference_renders/orthographic_axial_superior.png`
- `docs/reference_renders/tract_only_white.png`

Review them for left/right consistency, tract/slice alignment, camera framing,
color identity, background, clipping, and exact canvas dimensions. Human-approved
reference renders may be committed. CI should test dimensions, actor state,
bounds, and visible foreground rather than enforce pixel-perfect equality across
GPU drivers and operating systems.

## 11. Enable four-platform GitHub Actions validation

Use the bundled `.github/workflows/ci.yml`. It runs the non-integration gate on:

| Runner | Architecture/role | Python path |
| --- | --- | --- |
| `ubuntu-latest` | Linux, rendered through Xvfb | `.venv/bin/python` |
| `windows-latest` | Native Windows | `.venv/Scripts/python.exe` |
| `macos-15` | Apple Silicon macOS | `.venv/bin/python` |
| `macos-15-intel` | Intel macOS | `.venv/bin/python` |

The workflow pins `macos-15` instead of `macos-latest` so a hosted-image migration
does not silently change the baseline. It uses the frozen lockfile and invokes
the environment's Python directly.

The uv setup action is pinned to the immutable commit for `setup-uv` v9.0.0.
Current setup-uv releases no longer publish moving major tags such as `@v8`, so
the workflow must retain the complete action commit SHA.

Because no physical Mac is available, require both macOS jobs to pass before
tagging the starter. CI is the compatibility test, not a claim that macOS works
without evidence. If one Mac architecture fails, retain its job, open the full
log, reproduce the exact dependency versions from `uv.lock`, and fix the actual
cross-platform issue. Do not remove the failing platform from the matrix.

Integration tests are intentionally not repeated on every push because the
atlas download is large. Run them locally before the release and optionally add
a manual/nightly workflow with a cache if there is time. The pre-hackathon tag
must not be cut solely from the fast CI result.

## 12. Finalize project documentation

Before release, ensure the repository contains:

- the bundled `README.md`
- this `PREHACKATHON_GUIDE.md`
- `DATA_LICENSES.md`
- `demo_data/manifest.toml`
- at least one validated recipe under `examples/recipes/`
- approved images under `docs/reference_renders/`
- a short architecture note stating that streamlines use RASMM and transforms
  use moving-to-fixed direction
- screenshots or mockups attached to UI/rendering issues

Document the clean-install path exactly as tested. Students should not have to
infer activation commands, data locations, ports, or coordinate conventions.

## 13. Prepare the hackathon issues

Do not move baseline defects into these issues. The installation, data fetch,
coordinate detection, independent visibility, reset, save/export, recipe,
registration fixtures, tests, reference renders, and four-platform CI above must
already work. The issues below are feature work built on that baseline.

Every GitHub issue should contain: motivation, supplied input data, expected
behavior, relevant files, acceptance criteria, dependencies, a screenshot or
mockup, and suggested background level.

### `neuro`: anatomical presets and tract-palette design

**Pitch.** Make anatomically meaningful figures fast and consistent for users
who know neuroanatomy but do not want to tune every visual parameter.

**Starting point.** The scene model already stores colors, camera, slice state,
canvas, and active tract. The viewer already supports left/right sagittal,
anterior/posterior coronal, and superior/inferior axial views.

**Student work.** Define named anatomical presentation presets and a documented
tract color palette. Candidate presets are Black Glass, White Anatomy,
Orthographic Atlas, Transparent Figure, and Four-View Clinical. Specify which
tracts/slices are visible, camera orientation, projection, background, opacity,
and palette behavior. Add a preset selector without overwriting input data.

**Relevant files.** `src/tractfigure/scene_state_v1_20260730.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/gui/app_trame_v1_20260730.py`, and
`scripts/render_reference_scenes.py`.

**Acceptance.** Every preset is deterministic; laterality is correct; palette
names and HEX colors are documented; changing presets preserves layer identity;
save/reload preserves the chosen result; reference PNGs show the expected views.

**Suggested background.** Neuroanatomy, diffusion MRI, scientific illustration,
or visual design. No registration implementation is required.

### `registration`: rigid/affine controls and QC overlays

**Pitch.** Turn the validated registration backend into a safe, interpretable
workflow rather than a black-box transform button.

**Starting point.** `src/tractfigure/registration.py` already estimates an
affine, resamples images, transforms RASMM streamlines, and creates QC figures.
`scripts/generate_registration_demo.py` supplies identity, rigid, and affine
ground-truth cases with an explicit moving-to-fixed contract.

**Student work.** Add rigid and full-affine actions, progress/error feedback,
transform preview, apply/cancel, and before/after slice overlays. Display the
matrix direction and prevent accidental repeated application. Preserve original
inputs and cache transformed derivatives.

**Relevant files.** `src/tractfigure/registration.py`, the three canonical v1
scene/renderer/app modules, `scripts/generate_registration_demo.py`, and
`tests/test_registration.py`.

**Acceptance.** Identity leaves coordinates unchanged; rigid mode does not add
scale/shear; full affine uses the documented direction; resampled images match
fixed geometry; known fixtures improve alignment within a stated tolerance;
cancel leaves the scene untouched; QC images can be exported.

**Suggested background.** Image registration, medical imaging, numerical
optimization, or scientific Python.

### `rendering`: glass brain, depth peeling, lighting, and gradients

**Pitch.** Add publication-quality depth cues while keeping tract identity and
anatomical context legible.

**Starting point.** The renderer owns separate actors for tracts and slices,
supports line/tube rendering and exact-size PNG export, and keeps orientation UI
out of exported figures.

**Student work.** Implement a glass-brain surface option, robust translucent
composition, controllable lighting, and tract gradients. True tube mode should
use 3D geometry; line mode must remain free of point/node markers. Expose only
controls that have a clear visual effect.

**Relevant files.** `src/tractfigure/vtk_conversion.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/scene_state_v1_20260730.py`, and reference-render scripts/tests.

**Acceptance.** Tracts remain visible while the camera rotates; transparent
objects have stable ordering or a documented fallback; glass-brain opacity and
lighting round-trip in a recipe; gradients remain associated with the correct
tract; exports match requested dimensions on all CI platforms.

**Suggested background.** VTK/PyVista, computer graphics, scientific
visualization, or visual design.

### `ui`: layer cards, linked controls, and global settings

**Pitch.** Make large multi-tract scenes manageable without losing the compact
controls that already work.

**Starting point.** Independent tract/slice visibility, active-layer settings,
typed numeric inputs, color/opacity, reset controls, scene background, ruler,
bounding box, render-mode controls, and menu collapse are already present.

**Student work.** Build scalable layer cards, filtering/search, selection,
multi-select/linking, and explicit global-versus-active-layer operations.
Preserve color-coded toggles and prevent component IDs from sharing state.

**Relevant files.** `src/tractfigure/gui/app_trame_v1_20260730.py`,
`src/tractfigure/scene_state_v1_20260730.py`, and
`tests/test_app_trame_v1_20260730.py`.

**Acceptance.** Scenes with at least 80 layers remain navigable; one-layer
changes affect only intended IDs; linked edits affect exactly the selected
layers; the panel does not overlap or clip at normal laptop sizes; keyboard and
color controls are labeled; hide-menu remains available; reset semantics remain
unchanged.

**Suggested background.** Front-end development, Trame/Vue/Vuetify, UX, or
accessibility.

### `api`: deterministic recipe-based rendering

**Pitch.** Let researchers generate the same figure in a browser, script, or CI
job from one portable recipe.

**Starting point.** The Pydantic scene contract, portable path resolution,
renderer, and exact-size export already exist.

**Student work.** Add a supported headless CLI/API that loads a recipe, validates
data roots, renders specified views, reports provenance, and exits with useful
status codes. Avoid hidden GUI defaults. Define overwrite and output-naming
behavior.

**Relevant files.** `src/tractfigure/scene_state_v1_20260730.py`,
`src/tractfigure/renderer_trame_v1_20260730.py`,
`src/tractfigure/gui/app_trame_v1_20260730.py`, and
`scripts/render_reference_scenes.py`.

**Acceptance.** The same recipe produces stable actor state, camera, layer order,
colors, opacity, canvas size, and outputs; relative paths resolve through a
configurable data root; invalid recipes fail before rendering; a manifest records
software versions and inputs.

**Suggested background.** Python API/CLI design, reproducible research, or CI.

### `testing`: coordinate and rendering validation

**Pitch.** Expand confidence from the supplied fixtures to realistic edge cases
without relying on fragile pixel-perfect screenshots.

**Starting point.** The bundle already covers automatic source-space detection,
origin shifts, world bounds, scene/controller state, actor independence,
registration direction, offscreen output, and cross-platform CI.

**Student work.** Add adversarial coordinate fixtures, oblique affines, malformed
files, larger layer counts, camera round trips, transparency cases, and stateful
UI regression cases. Prefer invariant tests over driver-sensitive pixels.

**Relevant files.** All files under `tests/`, `src/tractfigure/io.py`,
`src/tractfigure/vtk_conversion.py`, and the canonical v1 modules.

**Acceptance.** Tests identify errors with actionable messages; fixtures are
small and licensed/generated; deterministic invariants cover coordinate
direction, finite values, bounds, actors, visibility, camera, output size, and
portable recipes; the four-platform CI matrix remains green.

**Suggested background.** Testing, neuroimaging formats, QA, or scientific
software engineering.

### `stretch`: video, nonlinear registration, and DSI `.tt.gz`

**Pitch.** Explore high-value extensions only after a team has completed and
tested a core issue.

**Starting point.** Camera state, deterministic frames, affine transform
direction, multiple tract formats, and recipe export are established.

**Student work.** Choose one bounded extension: deterministic turntable/video
export; a smooth nonlinear registration prototype with deformation provenance;
or a documented DSI Studio `.tt.gz` adapter that converts into the internal
RASMM representation.

**Relevant files.** Depends on the extension: renderer/scene state for video;
registration modules/fixtures for nonlinear work; `src/tractfigure/io.py` and
I/O tests for `.tt.gz`.

**Acceptance.** Video has explicit frame size/rate/camera path and reproducible
ordering; nonlinear registration never confuses forward/inverse deformation and
ships a generated fixture; `.tt.gz` loading validates coordinates, finite
points, reference overlap, and licensing. No stretch implementation may bypass
the scene contract or mutate original inputs.

**Suggested background.** Advanced visualization, image registration, media
encoding, or binary file formats.

## 14. Rehearse a clean installation

Do this in a fresh clone or disposable directory, not by deleting the working
environment. The test is successful only when a new student can go from clone
to viewer without undocumented intervention.

On Windows/MobaXTerm:

```bash
TF_TEMP='C:/Users/<WINDOWS_USERNAME>/AppData/Local/Temp'
TEMP="$TF_TEMP" TMP="$TF_TEMP" TMPDIR="$TF_TEMP" uv sync --frozen --all-extras
source .venv/Scripts/activate
python scripts/fetch_demo_data.py
python scripts/preflight.py
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8080
```

On macOS or Linux desktop:

```bash
uv sync --frozen --all-extras
source .venv/bin/activate
python scripts/fetch_demo_data.py
python scripts/preflight.py
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8080
```

Because no physical Mac is available, run the macOS clean install in both
GitHub-hosted matrix jobs. A CI test cannot replace subjective visual inspection,
so ask one Mac-using organizer or student to run the manual smoke test at the
start of the event, while retaining both automated Mac architecture jobs.

## 15. Commit, protect, and tag the baseline

Only after local checks and all four CI jobs pass:

```bash
git add .
git commit -m "Complete cross-platform pre-hackathon baseline"
git push
```

Configure the default branch to require the four CI results. Then create the
starter tag:

```bash
git tag -a v0.1.0-starter -m "Validated cross-platform hackathon starter"
git push origin v0.1.0-starter
```

Record the tag in the hackathon instructions. Students should create branches
from that tag or from the protected main branch, not from unvalidated local
files.

## 16. Final readiness gate

The baseline is ready only when every item below is true:

- A frozen Python 3.12 environment installs from `uv.lock` on Windows, macOS ARM,
  macOS Intel, and Linux.
- The five-format, HCP842, and MNI datasets fetch and verify.
- Automatic coordinate detection yields credible RASMM tracts without manual
  source-space entry.
- Five tracts align with the anatomical slices and load as separate actors.
- Global and per-tract visibility are independent.
- Each anatomical slice has an independent visibility toggle.
- Camera reset works after perspective interaction.
- Anatomical view buttons flip sides on repeated clicks.
- Numeric slider fields accept replacement typing and restore only invalid/blank
  values on blur.
- Tract color and opacity work in the same color panel.
- Line mode does not show nodes.
- Ruler, bounding box, rendering-mode, and menu-collapse controls are present.
- Scene save and exact-size PNG browser download work.
- Exported PNGs omit the orientation guide.
- Scene paths are portable where the files share a filesystem root.
- Identity, rigid, and affine registration fixtures and QC figures exist.
- Ruff, unit, renderer, registration, and integration tests pass.
- Approved reference renders have been inspected.
- Ubuntu, Windows, macOS ARM, and macOS Intel CI jobs pass.
- Dataset licenses, coordinate direction, install commands, and issue acceptance
  criteria are documented.
- `v0.1.0-starter` identifies the validated baseline.

Only after this gate should hackathon feature branches begin.

## Official technical references

- uv installation: <https://docs.astral.sh/uv/getting-started/installation/>
- uv projects and lockfiles: <https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile>
- uv with GitHub Actions: <https://docs.astral.sh/uv/guides/integration/github/>
- DIPY data API: <https://docs.dipy.org/stable/reference/dipy.data.html>
- DIPY streamline formats: <https://docs.dipy.org/stable/examples_built/file_formats/streamline_formats.html>
- DIPY affine registration: <https://docs.dipy.org/stable/examples_built/registration/affine_registration_3d.html>
- PyVista installation and headless rendering: <https://docs.pyvista.org/getting-started/installation.html>
- VTK 9.3.1 platform wheels: <https://pypi.org/project/vtk/9.3.1/>
- GitHub-hosted runner selection: <https://docs.github.com/actions/using-jobs/choosing-the-runner-for-a-job>
- GitHub Actions billing for public repositories: <https://docs.github.com/billing/managing-billing-for-github-actions/about-billing-for-github-actions>
