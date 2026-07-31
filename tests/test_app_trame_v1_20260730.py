from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PIL import Image

from tractfigure.gui.app_trame_v1_20260730 import (
    TractFigureController,
    color_with_alpha,
    load_recipe,
    scene_from_cli,
    scene_from_inputs,
    split_color_and_alpha,
)
from tractfigure.scene_state_v1_20260730 import (
    CameraState,
    ImageLayerState,
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

    def _require_scene(self) -> SceneState:
        return self.scene

    def set_tract_visible(self, layer_id: str, visible: bool) -> None:
        self.scene.tract_by_id(layer_id).visible = bool(visible)

    def set_all_tracts_visible(self, visible: bool) -> None:
        for tract in self.scene.tracts:
            tract.visible = bool(visible)

    def set_tract_appearance(self, layer_id: str, color: str, opacity: float) -> None:
        tract = self.scene.tract_by_id(layer_id)
        tract.color = color
        tract.opacity = opacity

    def set_line_width(self, layer_id: str, width: float) -> None:
        self.scene.tract_by_id(layer_id).line_width = width

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


def test_cli_recipe_and_color_helpers(tmp_path: Path) -> None:
    reference = tmp_path / "reference.nii.gz"
    tracts = [tmp_path / "bundle.trk", tmp_path / "bundle.tck"]
    reference.touch()
    for tract in tracts:
        tract.touch()

    scene = scene_from_inputs(reference, tracts)
    assert [tract.name for tract in scene.tracts] == ["bundle", "bundle (2)"]
    assert len({tract.id for tract in scene.tracts}) == 2

    cli_scene = scene_from_cli(SimpleNamespace(recipe=None, reference=reference, tractogram=tracts))
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

    key = controller.visibility_keys["tract-0"]
    callback = controller._make_visibility_callback("tract-0", key)
    callback(**{key: False})
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
