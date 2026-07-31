from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
import pyvista as pv
from nibabel.affines import apply_affine
from PIL import Image

from tractfigure.renderer_trame_v1_20260730 import SceneRenderer
from tractfigure.scene_state_v1_20260730 import (
    CanvasState,
    ImageLayerState,
    SceneState,
    TractLayerState,
)

pv.OFF_SCREEN = True


@dataclass(frozen=True)
class FakeInspection:
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class FakeLayer:
    streamlines: tuple[np.ndarray, ...]
    inspection: FakeInspection = FakeInspection()


def make_reference(tmp_path: Path) -> tuple[Path, np.ndarray]:
    data = np.arange(8 * 9 * 10, dtype=np.float32).reshape((8, 9, 10))
    affine = np.diag([2.0, 2.5, 3.0, 1.0])
    affine[:3, 3] = (-12.0, -15.0, -18.0)
    path = tmp_path / "reference.nii.gz"
    nib.save(nib.Nifti1Image(data, affine), path)
    return path, affine


def make_scene(reference: Path) -> SceneState:
    return SceneState(
        image=ImageLayerState(path=reference),
        tracts=[
            TractLayerState(
                id="tract-a",
                name="Tract A",
                path=reference.parent / "a.trk",
                color="#E64B35",
            ),
            TractLayerState(
                id="tract-b",
                name="Tract B",
                path=reference.parent / "b.trk",
                color="#4DBBD5",
            ),
        ],
        active_layer_id="tract-a",
        canvas=CanvasState(width=320, height=240, background="#FFFFFF"),
    )


def test_renderer_controls_camera_reset_and_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference, affine = make_reference(tmp_path)
    streamline = apply_affine(
        affine,
        np.array([[1.0, 2.0, 2.0], [3.0, 4.0, 5.0], [6.0, 7.0, 8.0]]),
    ).astype(np.float32)
    loader_calls: list[Path] = []

    def fake_loader(
        path: str | Path,
        reference_path: str | Path | None = None,
        *,
        name: str | None = None,
    ) -> FakeLayer:
        del reference_path, name
        loader_calls.append(Path(path))
        return FakeLayer((streamline,))

    plotter = pv.Plotter(off_screen=True, window_size=(320, 240))
    renderer = SceneRenderer(plotter, layer_loader=fake_loader)

    try:
        scene = renderer.load_scene(make_scene(reference))
        initial = scene.model_copy(deep=True)
        assert len(loader_calls) == 2
        assert set(renderer.actors_by_id) == {"tract-a", "tract-b"}
        assert set(renderer.image_actors) == {"sagittal", "coronal", "axial"}

        renderer.set_tract_visible("tract-a", False)
        assert not renderer.actors_by_id["tract-a"].GetVisibility()
        assert renderer.actors_by_id["tract-b"].GetVisibility()

        renderer.set_slice_visible("sagittal", False)
        assert not renderer.image_actors["sagittal"].GetVisibility()
        assert renderer.image_actors["coronal"].GetVisibility()
        assert renderer.image_actors["axial"].GetVisibility()

        renderer.set_tract_appearance("tract-a", "#112233", 0.5)
        assert scene.tract_by_id("tract-a").color == "#112233"
        assert scene.tract_by_id("tract-a").opacity == pytest.approx(0.5)
        assert scene.tract_by_id("tract-b").color == "#4DBBD5"

        renderer.set_render_mode("tract-a", "line")
        assert renderer.line_meshes_by_id["tract-a"].n_lines == 1
        assert renderer.line_meshes_by_id["tract-a"].n_verts == 0

        left = renderer.set_anatomical_view("sagittal", "left")
        right = renderer.set_anatomical_view("sagittal", "right")
        left_vector = np.asarray(left.position) - np.asarray(left.focal_point)
        right_vector = np.asarray(right.position) - np.asarray(right.focal_point)
        assert left.parallel_projection
        assert right.parallel_projection
        assert np.dot(left_vector, right_vector) < 0

        renderer.set_perspective_view()
        camera = renderer.reset_camera()
        assert not camera.parallel_projection
        assert np.isfinite(camera.position).all()
        assert camera.clipping_range[0] > 0
        assert camera.clipping_range[1] > camera.clipping_range[0]

        restored = renderer.restore_scene_settings(initial)
        assert len(loader_calls) == 2
        assert restored.model_dump(mode="json") == initial.model_dump(mode="json")

        axes_widgets = renderer._orientation_axes_widgets()
        enabled_before = [enabled for _widget, enabled in axes_widgets]
        enabled_during_capture: list[bool] = []

        def fake_screenshot(**_kwargs: Any) -> np.ndarray:
            enabled_during_capture.extend(
                bool(widget.GetEnabled()) for widget, _enabled in axes_widgets
            )
            return np.full((120, 200, 3), 255, dtype=np.uint8)

        monkeypatch.setattr(renderer.plotter, "screenshot", fake_screenshot)

        scene_path = renderer.save_scene(tmp_path / "outputs" / "scene.json")
        scene_text = scene_path.read_text(encoding="utf-8")
        saved_scene = SceneState.model_validate_json(scene_text)
        saved_payload = json.loads(scene_text)
        assert saved_scene
        assert not Path(saved_payload["image"]["path"]).is_absolute()
        assert "\\" not in saved_payload["image"]["path"]
        assert all("\\" not in tract["path"] for tract in saved_payload["tracts"])

        png_path = renderer.export_png(tmp_path / "outputs" / "render.png", 320, 240)
        with Image.open(png_path) as image:
            assert image.size == (320, 240)

        png_data = renderer.screenshot_png(320, 240)
        with Image.open(io.BytesIO(png_data)) as image:
            assert image.size == (320, 240)

        assert not any(enabled_during_capture)
        assert [bool(widget.GetEnabled()) for widget, _enabled in axes_widgets] == enabled_before
    finally:
        renderer.close()
