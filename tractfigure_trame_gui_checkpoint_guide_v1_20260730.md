# TractFigure Studio: Trame GUI and Scene-State Checkpoint

This guide adds the next development checkpoint to the working TractFigure
Studio viewer:

- A browser-based Trame interface
- A serializable Pydantic scene model
- Global and per-tract visibility controls
- Active-layer display controls
- Line and tube rendering controls
- Camera capture and restoration
- Scene-recipe save/load
- Exact-size PNG export

The instructions are written for a local Windows installation operated through
MobaXTerm. They create new, versioned modules and leave the working loader,
viewer, and affine-slice modules unchanged. They include no GitHub operations.

## 1. Preserve the working baseline

Use these existing modules as dependencies:

```text
src/tractfigure/io.py
src/tractfigure/vtk_conversion.py
src/tractfigure/viewer.py
```

The GUI must continue to use:

- `load_tract_layer()` for automatic tract coordinate detection
- `nifti_to_orthogonal_slices()` for affine-exact anatomical slices
- `streamlines_to_polydata()` for PyVista conversion

Do not duplicate coordinate detection, apply a global tract translation, or
construct anatomical slices through `ImageData.slice()`.

Create new files for this checkpoint:

```text
src/tractfigure/
├── scene_state_v1_20260730.py
├── renderer_trame_v1_20260730.py
└── gui/
    ├── __init__.py
    └── app_trame_v1_20260730.py

tests/
├── test_scene_state_v1_20260730.py
└── test_renderer_trame_v1_20260730.py

examples/
└── recipes/
    └── five_bundle_trame_v1_20260730.json
```

Run the new application as:

```bash
python -m tractfigure.gui.app_trame_v1_20260730
```

## 2. Enter the Windows project environment

Open the local MobaXTerm terminal:

```bash
cd /drives/c/Users/gabta/Desktop/tractfigure-studio
source .venv/Scripts/activate
```

Verify that MobaXTerm is using the project’s Windows Python:

```bash
python -c "import sys; print(sys.executable)"
```

The result should end with:

```text
tractfigure-studio\.venv\Scripts\python.exe
```

Set Windows temporary directories before using uv. This avoids MobaXTerm’s
emulated `/tmp` path and the earlier `uv-trampoline-*.exe` cleanup error:

```bash
TRACTFIGURE_WIN_TEMP='C:/Users/gabta/AppData/Local/Temp'
export TEMP="$TRACTFIGURE_WIN_TEMP"
export TMP="$TRACTFIGURE_WIN_TEMP"
export TMPDIR="$TRACTFIGURE_WIN_TEMP"
```

Synchronize the existing dependency groups:

```bash
uv sync --all-extras
```

The visualization extra should already contain:

```toml
trame
trame-vtk
trame-vuetify
```

If any are absent from `pyproject.toml`, add them to the existing `viz` extra:

```bash
uv add --optional viz trame trame-vtk trame-vuetify --no-sync
uv sync --all-extras
```

uv dependency and optional-group management is documented here:

<https://docs.astral.sh/uv/concepts/projects/dependencies/>

Verify the required packages:

```bash
python -c "from importlib.metadata import version; print({p: version(p) for p in ['pyvista', 'vtk', 'trame', 'trame-vtk', 'trame-vuetify', 'pydantic']})"
```

Trame’s official Python installation requires `trame`, `trame-vuetify`, and
`trame-vtk`:

<https://kitware.github.io/trame/guide/deployment/pypi.html>

## 3. Create the new module locations

```bash
mkdir -p src/tractfigure/gui
mkdir -p examples/recipes

touch src/tractfigure/gui/__init__.py
touch src/tractfigure/scene_state_v1_20260730.py
touch src/tractfigure/renderer_trame_v1_20260730.py
touch src/tractfigure/gui/app_trame_v1_20260730.py
touch tests/test_scene_state_v1_20260730.py
touch tests/test_renderer_trame_v1_20260730.py
```

Do not rename or replace the working modules during this checkpoint.

## 4. Implement the scene-state contract

Implement the following Pydantic models in
`scene_state_v1_20260730.py`.

### `TractLayerState`

Required fields:

```text
id                  str
name                str
path                Path
visible             bool = True
color               str
opacity             float = 1.0
render_mode         Literal["line", "tube"] = "tube"
line_width          float = 2.0
tube_radius         float = 0.35
tube_sides          int = 8
max_streamlines     int = 5000
coordinate_report   dict[str, JSON-compatible value]
```

Validation:

- `opacity`: 0.0–1.0
- `line_width`: greater than zero
- `tube_radius`: greater than zero
- `tube_sides`: at least 3
- `max_streamlines`: at least 1
- `color`: hexadecimal `#RRGGBB`
- Reject unrecognized fields with `ConfigDict(extra="forbid")`

Generate the layer ID once when the layer is loaded. Store the ID in the recipe
so it remains stable after a save/load cycle. Do not use actor names or list
positions as persistent IDs.

### `ImageLayerState`

Required fields:

```text
path              Path
visible           bool = True
opacity           float = 1.0
sagittal_index    int | None = None
coronal_index     int | None = None
axial_index       int | None = None
```

An index of `None` means `dimension // 2`, matching the affine-slice module.

### `CameraState`

Required fields:

```text
position          tuple[float, float, float]
focal_point       tuple[float, float, float]
view_up           tuple[float, float, float]
parallel_projection  bool
parallel_scale    float
clipping_range    tuple[float, float]
```

### `CanvasState`

Defaults:

```text
width             1400
height            1000
background        "#FFFFFF"
```

### `SceneState`

Required fields:

```text
schema_version    Literal["1.0"] = "1.0"
image             ImageLayerState
tracts            list[TractLayerState]
active_layer_id   str | None
camera            CameraState | None
canvas            CanvasState
```

Add model-level validation:

- Tract IDs must be unique.
- `active_layer_id` must identify an existing tract or be `None`.
- Tract order must remain unchanged during serialization.

Use:

```python
scene.model_dump_json(indent=2)
SceneState.model_validate_json(json_text)
```

Pydantic documents JSON serialization through `model_dump_json()`:

<https://docs.pydantic.dev/latest/concepts/serialization/>

## 5. Separate runtime objects from saved scene state

Implement `renderer_trame_v1_20260730.py` around a `SceneRenderer` class.

Pydantic state should contain configuration and paths. The renderer should own
the large and non-serializable runtime objects:

```text
PyVista Plotter
TractLayer objects
Streamline arrays
Line PolyData
Tube PolyData cache
VTK/PyVista actors
Anatomical slice actors
```

Use registries keyed by the persistent layer ID:

```python
self.layers_by_id
self.line_meshes_by_id
self.tube_meshes_by_key
self.actors_by_id
```

Recommended tube-cache key:

```text
(layer_id, tube_radius, tube_sides)
```

### Required renderer methods

```text
load_scene(scene)
load_reference(image_state)
add_tract(tract_state)
remove_tract(layer_id)
set_all_tracts_visible(visible)
set_tract_visible(layer_id, visible)
set_tract_color(layer_id, color)
set_tract_opacity(layer_id, opacity)
set_render_mode(layer_id, mode)
set_line_width(layer_id, width)
set_tube_radius(layer_id, radius)
set_tube_sides(layer_id, sides)
set_image_visible(visible)
set_image_opacity(opacity)
set_slice_indices(sagittal, coronal, axial)
capture_camera()
apply_camera(camera_state)
reset_camera()
export_png(path, width, height)
```

### Loading rules

For every tract:

1. Call `load_tract_layer()`.
2. Preserve the returned inspection report in `coordinate_report`.
3. Convert `layer.streamlines` with `streamlines_to_polydata()`.
4. Store the line PolyData.
5. Build tube geometry only when tube rendering is requested.
6. Register exactly one visible actor for the layer.

Automatic coordinate detection remains entirely inside `io.py`. The GUI must
not expose source-space or origin fields.

### Actor update rules

These changes should update the current actor property:

- Visibility
- Color
- Opacity
- Line width

These changes require geometry replacement:

- Line ↔ tube
- Tube radius
- Tube sides

When replacing geometry:

1. Remove the old actor.
2. Add the replacement actor under the same persistent layer ID.
3. Preserve visibility, color, and opacity.
4. Replace the actor entry in `actors_by_id`.
5. Keep the total tract actor count unchanged.

After each update:

```python
plotter.reset_camera_clipping_range()
plotter.render()
```

### Anatomical slices

Call:

```python
nifti_to_orthogonal_slices(image, indices)
```

Keep:

```text
Background       #FFFFFF
Image opacity    1.0
Scalar bar       hidden
Colormap         gray
Intensity limits 2nd–98th finite percentiles
```

Rebuild the three slice actors after a slice-index change. Preserve the NIfTI
affine-generated `StructuredGrid` coordinates.

### PNG export

Before screenshot capture:

1. Save the current render-window size.
2. Set the requested canvas dimensions.
3. Render.
4. Call `plotter.screenshot()`.
5. Restore the interactive window size.

The output image dimensions must exactly equal `CanvasState.width ×
CanvasState.height`.

PyVista screenshot documentation:

<https://docs.pyvista.org/api/plotting/_autosummary/pyvista.Plotter.screenshot.html>

## 6. Build the Trame application

Implement `gui/app_trame_v1_20260730.py`.

### Server and rendering initialization

Use Vue 3 consistently:

```python
server = get_server(client_type="vue3")
state = server.state
ctrl = server.controller
```

Use:

```python
pv.OFF_SCREEN = True
plotter = pv.Plotter(off_screen=True, window_size=(1400, 1000))
```

Windows will use its native VTK/OpenGL installation. MobaXTerm’s X server does
not require configuration.

Create the view with PyVista’s Trame helper:

```python
view = plotter_ui(
    plotter,
    mode="trame",
    default_server_rendering=True,
)
ctrl.view_update = view.update
ctrl.view_reset_camera = view.reset_camera
```

Server rendering should be the initial mode because it reproduces the VTK tube
geometry, shading, and actor properties already validated in the desktop
viewer.

PyVista’s Trame integration is documented here:

<https://docs.pyvista.org/api/plotting/trame.html>

### Initial input method

Load the reference and tractograms from command-line paths during this first
GUI checkpoint. This avoids transmitting large tractograms through a browser
upload field and keeps the GUI focused on scene control.

Arguments:

```text
--reference PATH
--tractogram PATH        repeatable
--recipe PATH
--output-dir PATH        default: outputs
--port INTEGER           default: 8080
```

Require either:

- `--recipe`, or
- one `--reference` plus at least one `--tractogram`

Resolve all paths with `Path.expanduser().resolve()` before loading.

Register these arguments through `server.cli.add_argument()` and obtain them
with:

```python
args = server.cli.parse_known_args()[0]
```

Start the server at the end of `main()`:

```python
server.start(
    port=args.port,
    open_browser=True,
    show_connection_info=True,
)
```

Trame documents both `server.cli` and the `server.start()` parameters:

<https://kitware.github.io/trame/guide/intro/getting_started.html>

### Shared Trame state

Initialize these state keys:

```text
layer_items
active_layer_id
all_tracts_visible
reference_visible
slice_opacity
active_color
active_opacity
active_render_mode
active_line_width
active_tube_radius
active_tube_sides
status_message
export_path
```

Each item in `layer_items` should contain:

```text
id
name
color
visible
warning_count
```

Do not place streamline arrays, meshes, actors, or complete inspection objects
in Trame shared state.

Trame synchronizes shared state between Python and the browser:

<https://kitware.github.io/trame/guide/intro/getting_started.html>

### Interface layout

Use:

```python
SinglePageWithDrawerLayout
```

Toolbar:

- Application title
- Reset camera
- Save scene
- Export PNG

Drawer:

1. Reference image section
   - Visibility
   - Slice opacity
   - Sagittal index
   - Coronal index
   - Axial index
2. Tract layers section
   - All-tract visibility
   - Color-coded visibility switch for every tract
   - Active-layer selector
3. Active-layer section
   - Color
   - Opacity
   - Line/tube mode
   - Line width
   - Tube radius
   - Tube sides
   - Coordinate-detection status and warnings
4. Status section
   - Last operation
   - Export path

Main content:

- PyVista/Trame viewport

Keep controls in the drawer so no visibility column can be clipped by the VTK
viewport.

Trame’s official application tutorial uses a drawer layout, reactive
components, callbacks, and a VTK view:

<https://kitware.github.io/trame/guide/tutorial/application.html>

## 7. Implement callbacks

Assign callbacks through `server.controller`.

### Global visibility

`set_all_tracts_visible(value)`:

1. Update every tract actor.
2. Update every per-layer visibility state.
3. Update the Pydantic scene.
4. Refresh the view once after the batch.

### Per-layer visibility

`set_tract_visible(layer_id, value)`:

1. Update the actor.
2. Update the corresponding `TractLayerState`.
3. Recalculate `all_tracts_visible`.
4. Refresh the view.

### Active-layer selection

`select_active_layer(layer_id)`:

1. Set `scene.active_layer_id`.
2. Populate all `active_*` controls from that layer.
3. Display its coordinate-detection confidence and warnings.

Selection alone should not reload or recreate the actor.

### Display controls

The active-layer controls should call the corresponding renderer method and
then update the Pydantic model.

Use a guard such as `updating_active_controls` while populating controls after
selection. This prevents selection changes from triggering redundant renderer
updates.

### Camera

`reset_camera()`:

```text
Reset camera
Reset clipping range
Refresh Trame view
Capture updated CameraState
```

Capture the camera immediately before saving a recipe or exporting a PNG.

### Save scene

Write:

```text
outputs/tractfigure_scene_<timestamp>.json
```

Use:

```python
scene.model_dump_json(indent=2)
```

Paths may be stored relative to a configurable data root. Preserve tract order.

### Load scene

1. Read the JSON.
2. Validate it with `SceneState.model_validate_json()`.
3. Resolve its paths.
4. Clear the renderer registries and current actors.
5. Load the image and tracts.
6. Apply the saved camera after all actors exist.
7. Populate all shared UI state.

### Export PNG

Write:

```text
outputs/tractfigure_render_<timestamp>.png
```

Use the dimensions stored in `CanvasState`.

## 8. Add model tests

Implement `test_scene_state_v1_20260730.py`.

Required tests:

```text
test_scene_json_round_trip
test_layer_order_is_preserved
test_active_layer_must_exist
test_duplicate_layer_ids_are_rejected
test_invalid_opacity_is_rejected
test_invalid_color_is_rejected
test_camera_round_trip_is_exact
test_unknown_fields_are_rejected
```

The round-trip assertion should compare two model instances:

```python
restored = SceneState.model_validate_json(scene.model_dump_json())
assert restored == scene
```

## 9. Add renderer tests

Implement `test_renderer_trame_v1_20260730.py`.

Use small synthetic streamlines and a synthetic NIfTI for unit tests. Reserve
the downloaded five-format dataset for integration tests.

Required tests:

```text
test_reference_creates_three_slice_actors
test_each_tract_creates_one_actor
test_global_visibility_updates_all_actors
test_individual_visibility_updates_one_actor
test_color_and_opacity_update_in_place
test_line_width_updates_in_place
test_line_to_tube_replacement_preserves_actor_count
test_tube_radius_change_preserves_layer_properties
test_camera_capture_and_apply_round_trip
test_export_dimensions_are_exact
```

Mark tests that need the downloaded dataset with:

```python
@pytest.mark.integration
```

The GUI module must place `server.start()` inside `main()` and protect it with:

```python
if __name__ == "__main__":
    main()
```

This allows tests to import the GUI module without starting a server.

## 10. Run validation

From the activated MobaXTerm environment:

```bash
python -m ruff check \
    src/tractfigure/scene_state_v1_20260730.py \
    src/tractfigure/renderer_trame_v1_20260730.py \
    src/tractfigure/gui/app_trame_v1_20260730.py \
    tests/test_scene_state_v1_20260730.py \
    tests/test_renderer_trame_v1_20260730.py
```

Run the new unit tests:

```bash
python -m pytest \
    tests/test_scene_state_v1_20260730.py \
    tests/test_renderer_trame_v1_20260730.py
```

Run the complete suite:

```bash
python -m pytest
```

## 11. Launch the five-format GUI

```bash
DEMO="demo_data/cache/bundle_file_formats_example"

python -m tractfigure.gui.app_trame_v1_20260730 \
    --reference "$DEMO/template0.nii.gz" \
    --tractogram "$DEMO/cc_m_sub.trk" \
    --tractogram "$DEMO/laf_m_sub.tck" \
    --tractogram "$DEMO/lpt_m_sub.fib" \
    --tractogram "$DEMO/raf_m_sub.vtk" \
    --tractogram "$DEMO/rpt_m_sub.dpy" \
    --output-dir outputs \
    --port 8080
```

The application should open the default Windows browser. If the browser does
not open automatically, navigate to:

```text
http://127.0.0.1:8080
```

Stop the server from MobaXTerm with:

```text
Ctrl+C
```

If port 8080 is occupied:

```bash
netstat.exe -ano | findstr.exe :8080
```

Then launch the app with another port:

```bash
--port 8081
```

## 12. Manual acceptance test

Verify all of the following:

1. The browser displays the same affine-aligned anatomy and tracts as the
   working desktop viewer.
2. The reference image starts visible at opacity 1.0.
3. The background is white.
4. No color legend appears in the viewport.
5. Every tract appears in the drawer with its assigned color.
6. Global visibility updates every tract and every tract switch.
7. An individual tract switch changes only that tract.
8. Active-layer selection does not change visibility.
9. Color changes preserve actor geometry and camera.
10. Opacity changes preserve actor geometry and camera.
11. Line/tube switching preserves layer identity and settings.
12. Line width updates line rendering.
13. Tube radius and sides update tube rendering.
14. Slice sliders keep anatomy and tracts spatially aligned.
15. Reset camera shows the complete scene.
16. Saved JSON reloads with the same layer order, colors, visibility, camera,
    and canvas dimensions.
17. Exported PNG is exactly 1400 × 1000 pixels.
18. Coordinate reports remain automatic and contain no required source-space
    input.

## 13. Checkpoint completion criteria

Proceed after:

- All existing loader and affine-slice tests still pass.
- All new model and renderer tests pass.
- Trame starts from the local Windows environment.
- The GUI reproduces the working PyVista scene.
- Actor count remains stable during display changes.
- Scene JSON round-trips exactly.
- PNG dimensions are deterministic.
- The working baseline modules remain unchanged.

The following checkpoint should add polished scene presets and deterministic
recipe-driven command-line rendering. Registration fixtures and affine
registration follow after recipe-based rendering is stable.
