from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import nibabel as nib
import numpy as np
from PIL import Image

import tractfigure.gui.app_trame_v1_20260730 as app_module
from tractfigure.gui.app_trame_v1_20260730 import (
    SURFACE_MORPH_LIMIT_MM,
    TractFigureController,
    color_with_alpha,
    load_recipe,
    scene_from_cli,
    scene_from_inputs,
    split_color_and_alpha,
)
from tractfigure.morphology_niimath_v1_20260905 import NiimathError
from tractfigure.scene_state_v1_20260730 import (
    CameraState,
    ImageLayerState,
    LightingState,
    MeshLayerState,
    SceneState,
    TractLayerState,
)


class FakeState(SimpleNamespace):
    def change(self, *_names: str):
        def register(callback: Any) -> Any:
            return callback

        return register

    def flush(self) -> None:
        self.flush_count = getattr(self, "flush_count", 0) + 1


class FakeServer:
    def __init__(self) -> None:
        self.state = FakeState()
        self.controller = SimpleNamespace()


class FakeRenderer:
    def __init__(self, scene: SceneState) -> None:
        self.scene = scene
        self.image_shape = (8, 9, 10)
        self.view_calls: list[tuple[str, str]] = []
        self.lighting_calls: list[tuple[str, dict[str, Any]]] = []
        self.added_tracts: list[str] = []
        self.removed_tracts: list[str] = []
        self.reference_loads: list[Path] = []

    def _require_scene(self) -> SceneState:
        return self.scene

    def set_tract_visible(self, layer_id: str, visible: bool) -> None:
        self.scene.tract_by_id(layer_id).visible = bool(visible)

    def set_all_tracts_visible(self, visible: bool) -> None:
        for tract in self.scene.tracts:
            tract.visible = bool(visible)

    def add_tract(self, tract: TractLayerState) -> None:
        self.added_tracts.append(tract.id)

    def remove_tract(self, layer_id: str) -> None:
        self.scene.tract_by_id(layer_id)
        self.removed_tracts.append(layer_id)
        self.scene.tracts = [tract for tract in self.scene.tracts if tract.id != layer_id]
        if self.scene.active_layer_id == layer_id:
            self.scene.active_layer_id = self.scene.tracts[0].id if self.scene.tracts else None

    def load_reference(self, image: ImageLayerState) -> None:
        self.reference_loads.append(Path(image.path))
        loaded = nib.load(str(image.path))
        self.image_shape = tuple(int(value) for value in loaded.shape)

    def set_slice_indices(self, sagittal: int, coronal: int, axial: int) -> None:
        self.scene.image.sagittal_index = int(sagittal)
        self.scene.image.coronal_index = int(coronal)
        self.scene.image.axial_index = int(axial)
        self.load_reference(self.scene.image)

    def set_tract_appearance(self, layer_id: str, color: str, opacity: float) -> None:
        tract = self.scene.tract_by_id(layer_id)
        tract.color = color
        tract.opacity = opacity

    def set_line_width(self, layer_id: str, width: float) -> None:
        self.scene.tract_by_id(layer_id).line_width = width

    def set_mesh_lighting(self, **changes: Any) -> LightingState:
        if self.scene.mesh is None:
            raise RuntimeError("No glass brain mesh is loaded")

        return self._set_lighting("mesh", changes)

    def set_tract_lighting(self, **changes: Any) -> LightingState:
        return self._set_lighting("tracts", changes)

    def _set_lighting(self, attribute: str, changes: dict[str, Any]) -> LightingState:
        current = getattr(self.scene.lighting, attribute)
        updated = LightingState.model_validate({**current.model_dump(), **changes})
        setattr(self.scene.lighting, attribute, updated)
        self.lighting_calls.append((attribute, changes))
        return updated

    def set_mesh_surface(self, mesh_path: Path) -> MeshLayerState:
        if self.scene.mesh is None:
            self.scene.mesh = MeshLayerState(path=mesh_path)
        else:
            self.scene.mesh.path = mesh_path

        return self.scene.mesh

    def set_anatomical_view(self, plane: str, side: str) -> CameraState:
        self.view_calls.append((plane, side))
        return self.capture_camera()

    def set_perspective_view(self) -> CameraState:
        return self.capture_camera()

    def reset_camera(self) -> CameraState:
        return self.capture_camera()

    def restore_scene_settings(self, initial: SceneState) -> SceneState:
        self.scene = initial.model_copy(deep=True)
        return self.scene

    def capture_camera(self) -> CameraState:
        camera = CameraState(
            position=(10.0, 20.0, 30.0),
            focal_point=(0.0, 0.0, 0.0),
            view_up=(0.0, 0.0, 1.0),
            parallel_scale=10.0,
            clipping_range=(0.1, 1000.0),
        )
        self.scene.camera = camera
        return camera

    def save_scene(self, output_path: Path) -> Path:
        self.capture_camera()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.scene.model_dump_json(indent=2), encoding="utf-8")
        return output_path

    def export_png(self, output_path: Path, width: int, height: int) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (width, height), "white").save(output_path)
        return output_path

    def screenshot_png(self, width: int, height: int) -> bytes:
        stream = io.BytesIO()
        Image.new("RGB", (width, height), "white").save(stream, format="PNG")
        return stream.getvalue()


def make_scene(reference: Path, tracts: list[Path]) -> SceneState:
    return SceneState(
        image=ImageLayerState(path=reference),
        tracts=[
            TractLayerState(
                id=f"tract-{index}",
                name=path.stem,
                path=path,
                color="#112233" if index == 0 else "#445566",
            )
            for index, path in enumerate(tracts)
        ],
        active_layer_id="tract-0",
    )


def write_nifti(path: Path, shape: tuple[int, int, int]) -> None:
    nib.save(nib.Nifti1Image(np.zeros(shape, dtype=np.float32), np.eye(4)), path)


def test_cli_recipe_and_color_helpers(tmp_path: Path) -> None:
    reference = tmp_path / "reference.nii.gz"
    tracts = [tmp_path / "bundle.trk", tmp_path / "bundle.tck"]
    reference.touch()
    for tract in tracts:
        tract.touch()

    scene = scene_from_inputs(reference, tracts)
    assert [tract.name for tract in scene.tracts] == ["bundle", "bundle (2)"]
    assert len({tract.id for tract in scene.tracts}) == 2

    cli_scene = scene_from_cli(
        SimpleNamespace(recipe=None, reference=reference, tractogram=tracts, mesh=None)
    )
    assert len(cli_scene.tracts) == 2

    recipe_path = tmp_path / "scene.json"
    recipe_path.write_text(scene.model_dump_json(indent=2), encoding="utf-8")
    assert load_recipe(recipe_path).model_dump(mode="json") == scene.model_dump(mode="json")

    assert color_with_alpha("#112233", 0.5) == "#11223380"
    color, opacity = split_color_and_alpha("#11223380")
    assert color == "#112233"
    assert opacity is not None and abs(opacity - 128 / 255) < 1e-9


def test_load_recipe_resolves_portable_relative_paths(tmp_path: Path) -> None:
    data_directory = tmp_path / "data"
    recipe_directory = tmp_path / "examples" / "recipes"
    data_directory.mkdir()
    recipe_directory.mkdir(parents=True)

    reference = data_directory / "reference.nii.gz"
    tractogram = data_directory / "bundle.trk"
    reference.touch()
    tractogram.touch()

    portable_scene = SceneState(
        image=ImageLayerState(path=Path("../../data/reference.nii.gz")),
        tracts=[
            TractLayerState(
                id="portable-tract",
                name="Portable tract",
                path=Path("../../data/bundle.trk"),
                color="#112233",
            )
        ],
        active_layer_id="portable-tract",
    )
    recipe_path = recipe_directory / "portable.json"
    recipe_path.write_text(portable_scene.model_dump_json(indent=2), encoding="utf-8")

    loaded = load_recipe(recipe_path)
    assert loaded.image.path == reference.resolve()
    assert loaded.tracts[0].path == tractogram.resolve()


def test_controller_independent_controls_resets_and_outputs(tmp_path: Path) -> None:
    reference = tmp_path / "reference.nii.gz"
    tracts = [tmp_path / "a.trk", tmp_path / "b.trk"]
    scene = make_scene(reference, tracts)
    renderer = FakeRenderer(scene)
    controller = TractFigureController(
        FakeServer(),
        renderer,
        tmp_path / "outputs",
    )

    controller.toggle_layer_visibility("tract-0")
    assert not controller.scene.tract_by_id("tract-0").visible
    assert controller.scene.tract_by_id("tract-1").visible

    controller.state.active_layer_id = "tract-0"
    controller._on_active_color(active_color="#AABBCC80")
    active = controller.scene.tract_by_id("tract-0")
    assert active.color == "#AABBCC"
    assert abs(active.opacity - 128 / 255) < 1e-9

    old_width = active.line_width
    controller.state.active_line_width_input = ""
    controller._commit_numeric_input("active_line_width")
    assert active.line_width == old_width
    assert controller.state.active_line_width_input == f"{old_width:g}"

    controller.state.active_line_width_input = "3.25"
    controller._commit_numeric_input("active_line_width")
    controller._on_active_line_width(active_line_width=3.25)
    assert active.line_width == 3.25

    controller.view_sagittal()
    controller.view_sagittal()
    assert renderer.view_calls == [
        ("sagittal", "left"),
        ("sagittal", "right"),
    ]

    controller.reset_all_settings()
    assert controller.scene.model_dump(mode="json") == controller.initial_scene.model_dump(
        mode="json"
    )

    scene_path = controller.save_scene()
    assert SceneState.model_validate_json(scene_path.read_text(encoding="utf-8"))
    png_path = controller.export_png()
    with Image.open(png_path) as image:
        assert image.size == (1400, 1000)

    with Image.open(io.BytesIO(controller.download_png())) as image:
        assert image.size == (1400, 1000)


def test_dynamic_linked_layers_propagate_visibility_and_appearance(
    tmp_path: Path,
) -> None:
    scene = make_scene(
        tmp_path / "reference.nii.gz",
        [tmp_path / "a.trk", tmp_path / "b.trk"],
    )
    renderer = FakeRenderer(scene)
    controller = TractFigureController(FakeServer(), renderer, tmp_path / "outputs")
    first, second = controller.scene.tracts

    controller.toggle_layer_link(first.id)
    controller.toggle_layer_link(second.id)
    controller.toggle_layer_visibility(first.id)

    assert not first.visible
    assert not second.visible
    assert all(item["linked"] for item in controller.state.layer_items)

    controller.state.active_layer_id = first.id
    controller._on_active_color(active_color="#AABBCC80")

    assert second.color == "#AABBCC"
    assert abs(second.opacity - 128 / 255) < 1e-9

    controller.remove_tract(first.id)
    assert controller.state.linked_layer_ids == [second.id]
    assert controller.state.layer_items[0]["linked"]


def test_change_image_reloads_reference_and_resets_manual_transform(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    old_reference = tmp_path / "old.nii.gz"
    new_reference = tmp_path / "new.nii.gz"
    write_nifti(old_reference, (8, 9, 10))
    write_nifti(new_reference, (10, 12, 14))

    scene = make_scene(old_reference, [tmp_path / "a.trk"])
    scene.image.translation_mm = (1.0, 2.0, 3.0)
    scene.image.rotation_deg = (4.0, 5.0, 6.0)
    scene.image.scale = (1.1, 1.2, 1.3)
    renderer = FakeRenderer(scene)
    controller = TractFigureController(FakeServer(), renderer, tmp_path / "outputs")
    tract_ids = [tract.id for tract in scene.tracts]

    monkeypatch.setattr(app_module, "choose_image", lambda _current: new_reference)
    controller.change_image()

    assert controller.scene.image.path == new_reference
    assert (
        controller.scene.image.sagittal_index,
        controller.scene.image.coronal_index,
        controller.scene.image.axial_index,
    ) == (5, 6, 7)
    assert controller.scene.image.translation_mm == (0.0, 0.0, 0.0)
    assert controller.scene.image.rotation_deg == (0.0, 0.0, 0.0)
    assert controller.scene.image.scale == (1.0, 1.0, 1.0)
    assert [tract.id for tract in controller.scene.tracts] == tract_ids
    maxima = (
        controller.state.sagittal_max,
        controller.state.coronal_max,
        controller.state.axial_max,
    )
    assert maxima == (
        9,
        11,
        13,
    )
    assert controller.initial_scene.image.path == new_reference


def test_change_image_rolls_back_when_renderer_rejects_it(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    old_reference = tmp_path / "old.nii.gz"
    new_reference = tmp_path / "new.nii.gz"
    write_nifti(old_reference, (8, 9, 10))
    write_nifti(new_reference, (10, 12, 14))

    scene = make_scene(old_reference, [tmp_path / "a.trk"])
    renderer = FakeRenderer(scene)
    controller = TractFigureController(FakeServer(), renderer, tmp_path / "outputs")
    original = controller.scene.image.model_copy(deep=True)

    monkeypatch.setattr(app_module, "choose_image", lambda _current: new_reference)
    monkeypatch.setattr(
        renderer,
        "set_slice_indices",
        lambda *_indices: (_ for _ in ()).throw(RuntimeError("render failure")),
    )
    controller.change_image()

    assert controller.scene.image == original
    assert renderer.reference_loads == [old_reference]
    assert "Image unchanged" in controller.state.status_message


def test_runtime_tract_addition_deduplicates_folder_and_removal_updates_list(
    tmp_path: Path,
) -> None:
    reference = tmp_path / "reference.nii.gz"
    write_nifti(reference, (8, 9, 10))
    existing = tmp_path / "a.trk"
    existing.touch()
    tract_folder = tmp_path / "tracts"
    tract_folder.mkdir()
    tck = tract_folder / "b.tck"
    tinytrack = tract_folder / "c.tt.gz"
    ignored = tract_folder / "notes.txt"
    for path in (tck, tinytrack, ignored):
        path.touch()

    scene = make_scene(reference, [existing])
    renderer = FakeRenderer(scene)
    controller = TractFigureController(FakeServer(), renderer, tmp_path / "outputs")

    controller.add_tract_entries([tck, tract_folder])

    assert [tract.path for tract in controller.scene.tracts] == [
        existing,
        tck,
        tinytrack,
    ]
    assert len(renderer.added_tracts) == 2
    assert [item["name"] for item in controller.state.layer_items] == ["a", "b", "c.tt"]

    controller.add_tract_entries([tract_folder])
    assert len(controller.scene.tracts) == 3
    assert "skipped 2 duplicates" in controller.state.status_message

    removed_id = controller.scene.tracts[0].id
    controller.remove_tract(removed_id)
    assert renderer.removed_tracts == [removed_id]
    assert [tract.path for tract in controller.scene.tracts] == [tck, tinytrack]
    assert controller.scene.active_layer_id == controller.scene.tracts[0].id
    assert [item["name"] for item in controller.state.layer_items] == ["b", "c.tt"]
    assert [tract.path for tract in controller.initial_scene.tracts] == [tck, tinytrack]


class FakeMorpher:
    def __init__(self, tmp_path: Path) -> None:
        self.directory = tmp_path / "surfaces"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.requests: list[int] = []
        self.error: Exception | None = None

    def mesh_for_offset(self, millimeters: int) -> Path:
        if self.error is not None:
            raise self.error

        self.requests.append(millimeters)
        surface = self.directory / f"surface_{millimeters}.gii"
        surface.touch()
        return surface


def test_erode_and_diffuse_track_a_signed_millimeter_offset(tmp_path: Path) -> None:
    reference = tmp_path / "reference.nii.gz"
    scene = make_scene(reference, [tmp_path / "a.trk"])
    renderer = FakeRenderer(scene)
    controller = TractFigureController(
        FakeServer(),
        renderer,
        tmp_path / "outputs",
    )

    morpher = FakeMorpher(tmp_path)
    controller.surface_morpher = morpher

    assert controller.state.surface_offset_mm == 0
    assert controller.state.surface_offset_label == "Brain surface: unmodified"
    assert not controller.state.mesh_present

    controller.erode_surface()
    controller.erode_surface()
    controller.diffuse_surface()

    assert morpher.requests == [1, 2, 1]
    assert controller.state.surface_offset_mm == 1
    assert controller.state.surface_offset_label == "Brain surface: eroded 1 mm"
    assert controller.state.mesh_present
    assert controller.scene.mesh is not None
    assert controller.scene.mesh.path == morpher.directory / "surface_1.gii"

    # Walk past the lower bound: the last press is refused rather than applied.
    for _ in range(SURFACE_MORPH_LIMIT_MM + 2):
        controller.diffuse_surface()

    assert controller.state.surface_offset_mm == -SURFACE_MORPH_LIMIT_MM
    assert "limited" in controller.state.status_message

    morpher.error = NiimathError("niimath was not found")
    controller.erode_surface()
    assert controller.state.surface_offset_mm == -SURFACE_MORPH_LIMIT_MM
    assert controller.state.status_message == "niimath was not found"

    morpher.error = None
    controller.reset_all_settings()
    assert controller.state.surface_offset_mm == 0
    assert not controller.state.mesh_present


def test_lighting_controls_drive_the_two_rigs_independently(tmp_path: Path) -> None:
    reference = tmp_path / "reference.nii.gz"
    mesh_path = tmp_path / "brain.gii"
    scene = make_scene(reference, [tmp_path / "a.trk"])
    scene.mesh = MeshLayerState(path=mesh_path)
    renderer = FakeRenderer(scene)
    controller = TractFigureController(
        FakeServer(),
        renderer,
        tmp_path / "outputs",
    )

    assert controller.state.mesh_lighting_preset == "default"
    assert controller.state.tract_lighting_preset == "default"
    assert controller.state.tract_lighting_intensity == 1.0
    assert controller.state.mesh_lighting_ambient_input == "0.15"

    mesh_preset = controller._make_lighting_callback("mesh", "preset", "mesh_lighting_preset")
    mesh_preset(mesh_lighting_preset="three_point")
    assert controller.scene.lighting.mesh.preset == "three_point"
    # Lighting the glass brain must leave the tracts alone.
    assert controller.scene.lighting.tracts.preset == "default"

    tract_preset = controller._make_lighting_callback("tracts", "preset", "tract_lighting_preset")
    tract_preset(tract_lighting_preset="rim")
    assert controller.scene.lighting.tracts.preset == "rim"
    assert controller.scene.lighting.mesh.preset == "three_point"

    tract_intensity = controller._make_lighting_callback(
        "tracts", "intensity", "tract_lighting_intensity"
    )
    tract_intensity(tract_lighting_intensity=1.75)
    assert controller.scene.lighting.tracts.intensity == 1.75
    assert controller.state.tract_lighting_intensity_input == "1.75"

    # Out-of-range and non-numeric entries clamp or revert rather than raising.
    tract_intensity(tract_lighting_intensity=99.0)
    assert controller.scene.lighting.tracts.intensity == 3.0
    tract_intensity(tract_lighting_intensity="not a number")
    assert controller.scene.lighting.tracts.intensity == 3.0

    # A repeated value is a no-op, so the renderer is not re-invoked.
    calls = len(renderer.lighting_calls)
    tract_preset(tract_lighting_preset="rim")
    assert len(renderer.lighting_calls) == calls

    controller.reset_all_settings()
    assert controller.scene.lighting.mesh.preset == "default"
    assert controller.scene.lighting.tracts.preset == "default"
    assert controller.state.mesh_lighting_preset == "default"
    assert controller.state.tract_lighting_intensity_input == "1"


def test_mesh_lighting_controls_are_inert_without_a_glass_brain(tmp_path: Path) -> None:
    reference = tmp_path / "reference.nii.gz"
    scene = make_scene(reference, [tmp_path / "a.trk"])
    renderer = FakeRenderer(scene)
    controller = TractFigureController(
        FakeServer(),
        renderer,
        tmp_path / "outputs",
    )

    assert not controller.state.mesh_present

    callback = controller._make_lighting_callback("mesh", "preset", "mesh_lighting_preset")
    callback(mesh_lighting_preset="three_point")

    assert controller.scene.lighting.mesh.preset == "default"
    assert renderer.lighting_calls == []
