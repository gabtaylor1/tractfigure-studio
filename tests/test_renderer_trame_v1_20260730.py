from __future__ import annotations

import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pytest
import pyvista as pv
from nibabel.affines import apply_affine
from PIL import Image

from tractfigure.renderer_trame_v1_20260730 import (
    LIGHT_RIGS,
    LIGHTING_PRESETS,
    OUTLINE_DISCARD,
    OUTLINE_SHADER,
    SceneRenderer,
    image_transform,
    lighting_fragment_shader,
)
from tractfigure.scene_state_v1_20260730 import (
    CanvasState,
    ImageLayerState,
    LightingState,
    MeshLayerState,
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


def test_renderer_loads_gifti_mesh_and_sets_opacity(tmp_path: Path) -> None:
    reference, _affine = make_reference(tmp_path)
    vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=np.float32)
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.int32)
    gifti = nib.gifti.GiftiImage()
    gifti.add_gifti_data_array(nib.gifti.GiftiDataArray(vertices, intent="NIFTI_INTENT_POINTSET"))
    gifti.add_gifti_data_array(nib.gifti.GiftiDataArray(faces, intent="NIFTI_INTENT_TRIANGLE"))
    mesh_path = tmp_path / "brain.gii"
    nib.save(gifti, mesh_path)

    scene = make_scene(reference)
    scene.mesh = MeshLayerState(path=mesh_path)
    renderer = SceneRenderer(
        pv.Plotter(off_screen=True, window_size=(320, 240)),
        layer_loader=lambda path, reference_path=None, *, name=None: FakeLayer(
            (np.array([[0, 0, 0], [5, 5, 5]], dtype=np.float32),)
        ),
    )
    windows_ci = sys.platform == "win32" and os.getenv("GITHUB_ACTIONS") == "true"

    try:
        renderer.load_scene(scene)
        assert renderer.mesh_actor is not None
        assert renderer.mesh_actor.GetProperty().GetOpacity() == pytest.approx(0.25)
        renderer.set_mesh_opacity(0.6)
        assert renderer.scene.mesh.opacity == pytest.approx(0.6)
        assert renderer.mesh_actor.GetProperty().GetOpacity() == pytest.approx(0.6)
        phong: np.ndarray | None = None
        if not windows_ci:
            phong = renderer._capture_png(io.BytesIO(), 320, 240)

        renderer.set_mesh_shader("outline")
        assert renderer.mesh_actor.GetShaderProperty().GetNumberOfShaderReplacements() == 1
        if phong is not None:
            assert not np.array_equal(
                phong,
                renderer._capture_png(io.BytesIO(), 320, 240),
            )

        renderer.set_mesh_shader("phong")
        assert renderer.mesh_actor.GetShaderProperty().GetNumberOfShaderReplacements() == 0
    finally:
        renderer.close()


def test_image_transform_is_identity_by_default_and_pivots_on_centre() -> None:
    image = ImageLayerState(path=Path("ref.nii.gz"))
    pivot = np.array([5.0, -3.0, 2.0])
    np.testing.assert_allclose(image_transform(image, pivot), np.eye(4))

    image.rotation_deg = (0.0, 0.0, 90.0)
    image.scale = (2.0, 2.0, 2.0)
    image.translation_mm = (1.0, 0.0, 0.0)
    matrix = image_transform(image, pivot)
    # The pivot only moves by the translation.
    np.testing.assert_allclose(apply_affine(matrix, pivot), pivot + [1.0, 0.0, 0.0], atol=1e-12)
    # A point 1 mm +x of the pivot ends up 2 mm +y of it (scaled, rotated 90 deg about z).
    np.testing.assert_allclose(
        apply_affine(matrix, pivot + [1.0, 0.0, 0.0]), pivot + [1.0, 2.0, 0.0], atol=1e-12
    )


def write_tetrahedron_gifti(path: Path) -> Path:
    vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [0, 0, 10]], dtype=np.float32)
    faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]], dtype=np.int32)
    gifti = nib.gifti.GiftiImage()
    gifti.add_gifti_data_array(nib.gifti.GiftiDataArray(vertices, intent="NIFTI_INTENT_POINTSET"))
    gifti.add_gifti_data_array(nib.gifti.GiftiDataArray(faces, intent="NIFTI_INTENT_TRIANGLE"))
    nib.save(gifti, path)
    return path


def test_lighting_fragment_shader_covers_every_preset() -> None:
    assert LIGHTING_PRESETS[0] == "default"
    assert set(LIGHTING_PRESETS[1:]) == set(LIGHT_RIGS)

    # "default" leaves VTK's shared light kit in charge, so there is nothing to inject.
    assert lighting_fragment_shader(LightingState()) is None
    assert lighting_fragment_shader(LightingState(), outline=True) == OUTLINE_SHADER

    three_point = lighting_fragment_shader(LightingState(preset="three_point"))
    assert three_point is not None
    assert three_point.count("vec3 lightDir") == len(LIGHT_RIGS["three_point"]) == 3
    assert "fragOutput0" in three_point

    # The outline silhouette test composes with the rig rather than replacing it.
    outlined = lighting_fragment_shader(LightingState(preset="three_point"), outline=True)
    assert outlined is not None
    assert outlined.startswith(OUTLINE_DISCARD)
    assert outlined.endswith(three_point)

    # Intensity scales every light; "flat" is unlit, so it has no dot products.
    bright = lighting_fragment_shader(LightingState(preset="headlight", intensity=2.0))
    assert bright is not None and "2.0000 * lightDot" in bright
    flat = lighting_fragment_shader(LightingState(preset="flat", intensity=0.8))
    assert flat is not None and "lightDot" not in flat and "0.8000" in flat


def test_renderer_lights_mesh_and_tracts_independently(tmp_path: Path) -> None:
    reference, _affine = make_reference(tmp_path)
    mesh_path = write_tetrahedron_gifti(tmp_path / "brain.gii")

    scene = make_scene(reference)
    scene.image.visible = False
    scene.mesh = MeshLayerState(path=mesh_path, opacity=1.0)
    renderer = SceneRenderer(
        pv.Plotter(off_screen=True, window_size=(320, 240)),
        layer_loader=lambda path, reference_path=None, *, name=None: FakeLayer(
            (np.array([[-10, -10, -10], [0, 0, 0], [8, 8, 8]], dtype=np.float32),)
        ),
    )
    windows_ci = sys.platform == "win32" and os.getenv("GITHUB_ACTIONS") == "true"

    def replacement_counts() -> tuple[int, list[int]]:
        return (
            renderer.mesh_actor.GetShaderProperty().GetNumberOfShaderReplacements(),
            [
                actor.GetShaderProperty().GetNumberOfShaderReplacements()
                for actor in renderer.actors_by_id.values()
            ],
        )

    try:
        scene = renderer.load_scene(scene)

        # Nothing is injected until a preset is chosen.
        assert scene.lighting.mesh.preset == "default"
        assert replacement_counts() == (0, [0, 0])

        renderer.set_mesh_lighting(preset="three_point", intensity=1.4)
        assert scene.lighting.mesh.preset == "three_point"
        assert scene.lighting.mesh.intensity == pytest.approx(1.4)
        # Lighting the glass brain must leave the tracts on the default rig.
        assert scene.lighting.tracts.preset == "default"
        assert replacement_counts() == (1, [0, 0])

        renderer.set_tract_lighting(preset="rim")
        assert scene.lighting.tracts.preset == "rim"
        assert scene.lighting.mesh.preset == "three_point"
        assert replacement_counts() == (1, [1, 1])

        # A tract added afterwards picks up the rig already in force.
        added = TractLayerState(
            id="tract-c",
            name="Tract C",
            path=reference.parent / "c.trk",
            color="#00A087",
        )
        scene.tracts.append(added)
        renderer.add_tract(added)
        assert replacement_counts() == (1, [1, 1, 1])
        renderer.remove_tract("tract-c")

        # Every preset must compile and produce a distinct image.
        if not windows_ci:
            renderer._capture_png(io.BytesIO(), 320, 240)  # warm up the GL context
            renders: dict[str, np.ndarray] = {}

            for preset in LIGHTING_PRESETS:
                renderer.set_mesh_lighting(preset=preset)
                renders[preset] = renderer._capture_png(io.BytesIO(), 320, 240)

            for preset, image in renders.items():
                if preset == "default":
                    continue
                assert not np.array_equal(renders["default"], image), preset

        renderer.set_mesh_lighting(preset="soft")
        renderer.set_mesh_shader("outline")
        # Outline and lighting share one replacement slot.
        assert replacement_counts()[0] == 1

        renderer.set_mesh_lighting(preset="default")
        assert replacement_counts()[0] == 1  # still outlined
        renderer.set_mesh_shader("phong")
        assert replacement_counts()[0] == 0
    finally:
        renderer.close()


def test_lighting_survives_save_and_reset(tmp_path: Path) -> None:
    reference, _affine = make_reference(tmp_path)
    mesh_path = write_tetrahedron_gifti(tmp_path / "brain.gii")

    scene = make_scene(reference)
    scene.mesh = MeshLayerState(path=mesh_path)
    renderer = SceneRenderer(
        pv.Plotter(off_screen=True, window_size=(320, 240)),
        layer_loader=lambda path, reference_path=None, *, name=None: FakeLayer(
            (np.array([[0, 0, 0], [5, 5, 5]], dtype=np.float32),)
        ),
    )

    try:
        scene = renderer.load_scene(scene)
        initial = scene.model_copy(deep=True)

        renderer.set_mesh_lighting(preset="rim", ambient=0.4)
        renderer.set_tract_lighting(preset="soft", specular=0.9)

        saved = json.loads(renderer.save_scene(tmp_path / "scene.json").read_text())
        assert saved["lighting"]["mesh"] == {
            "preset": "rim",
            "intensity": 1.0,
            "ambient": 0.4,
            "specular": 0.3,
        }
        assert saved["lighting"]["tracts"]["preset"] == "soft"
        assert saved["lighting"]["tracts"]["specular"] == pytest.approx(0.9)

        restored = renderer.restore_scene_settings(initial)
        assert restored.lighting.mesh.preset == "default"
        assert restored.lighting.tracts.preset == "default"
        assert renderer.mesh_actor.GetShaderProperty().GetNumberOfShaderReplacements() == 0
        assert all(
            actor.GetShaderProperty().GetNumberOfShaderReplacements() == 0
            for actor in renderer.actors_by_id.values()
        )
    finally:
        renderer.close()
