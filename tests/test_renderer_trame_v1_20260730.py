
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import nibabel as nib
import numpy as np
import pytest
import pyvista as pv
from PIL import Image

from tractfigure.renderer_trame_v1_20260730 import (
    SceneRenderer,
)
from tractfigure.scene_state_v1_20260730 import (
    CameraState,
    ImageLayerState,
    SceneState,
    TractLayerState,
)

pv.OFF_SCREEN = True


@dataclass(frozen=True)
class FakeInspection:
    filename: str = "fake.trk"
    detected_format: str = ".trk"
    coordinate_detection: str = "test"
    detection_confidence: str = "high"
    source_space: str = "RASMM"
    source_origin: str = "NIFTI"
    output_space: str = "RASMM"
    point_fraction_inside_reference: float = 1.0
    warnings: tuple[str, ...] = ()


def fake_layer_loader(
    tractogram_path: Path,
    reference_path: Path,
    name: str,
):
    streamlines = (
        np.array(
            [
                [1.0, 1.0, 1.0],
                [2.0, 2.0, 2.0],
                [3.0, 3.0, 3.0],
            ],
            dtype=np.float32,
        ),
        np.array(
            [
                [1.0, 3.0, 1.0],
                [2.0, 4.0, 2.0],
                [3.0, 5.0, 3.0],
            ],
            dtype=np.float32,
        ),
    )

    return SimpleNamespace(
        name=name,
        path=tractogram_path,
        streamlines=streamlines,
        inspection=FakeInspection(),
    )


def make_scene(reference_path: Path) -> SceneState:
    tract = TractLayerState(
        id="test-tract",
        name="Test tract",
        path=Path("fake.trk"),
        color="#E64B35",
        render_mode="line",
    )

    return SceneState(
        image=ImageLayerState(path=reference_path),
        tracts=[tract],
        active_layer_id=tract.id,
    )


@pytest.fixture
def loaded_renderer(tmp_path: Path):
    data = np.arange(
        8 * 9 * 10,
        dtype=np.float32,
    ).reshape((8, 9, 10))

    reference_path = tmp_path / "reference.nii.gz"
    nib.save(
        nib.Nifti1Image(
            data,
            np.diag([1.0, 1.2, 1.5, 1.0]),
        ),
        reference_path,
    )

    plotter = pv.Plotter(
        off_screen=True,
        window_size=(400, 300),
    )

    renderer = SceneRenderer(
        plotter,
        layer_loader=fake_layer_loader,
    )
    renderer.load_scene(make_scene(reference_path))

    yield renderer

    renderer.close()


def test_reference_creates_three_slice_actors(
    loaded_renderer: SceneRenderer,
) -> None:
    assert set(loaded_renderer.image_actors) == {
        "sagittal",
        "coronal",
        "axial",
    }


def test_each_tract_creates_one_actor(
    loaded_renderer: SceneRenderer,
) -> None:
    assert set(loaded_renderer.actors_by_id) == {
        "test-tract"
    }


def test_global_visibility_updates_all_actors(
    loaded_renderer: SceneRenderer,
) -> None:
    loaded_renderer.set_all_tracts_visible(False)

    assert all(
        not bool(actor.GetVisibility())
        for actor in loaded_renderer.actors_by_id.values()
    )


def test_individual_visibility_updates_one_actor(
    loaded_renderer: SceneRenderer,
) -> None:
    loaded_renderer.set_tract_visible(
        "test-tract",
        False,
    )

    actor = loaded_renderer.actors_by_id["test-tract"]

    assert not bool(actor.GetVisibility())
    assert not loaded_renderer.scene.tract_by_id(
        "test-tract"
    ).visible


def test_color_and_opacity_update_in_place(
    loaded_renderer: SceneRenderer,
) -> None:
    actor_before = loaded_renderer.actors_by_id[
        "test-tract"
    ]

    loaded_renderer.set_tract_color(
        "test-tract",
        "#112233",
    )
    loaded_renderer.set_tract_opacity(
        "test-tract",
        0.4,
    )

    actor_after = loaded_renderer.actors_by_id[
        "test-tract"
    ]

    assert actor_after is actor_before

    np.testing.assert_allclose(
        actor_after.GetProperty().GetColor(),
        pv.Color("#112233").float_rgb,
    )
    assert actor_after.GetProperty().GetOpacity() == pytest.approx(
        0.4
    )


def test_line_width_updates_in_place(
    loaded_renderer: SceneRenderer,
) -> None:
    actor_before = loaded_renderer.actors_by_id[
        "test-tract"
    ]

    loaded_renderer.set_line_width(
        "test-tract",
        5.0,
    )

    actor_after = loaded_renderer.actors_by_id[
        "test-tract"
    ]

    assert actor_after is actor_before
    assert actor_after.GetProperty().GetLineWidth() == pytest.approx(
        5.0
    )


def test_line_to_tube_replacement_preserves_actor_count(
    loaded_renderer: SceneRenderer,
) -> None:
    actor_before = loaded_renderer.actors_by_id[
        "test-tract"
    ]
    count_before = len(loaded_renderer.actors_by_id)

    loaded_renderer.set_render_mode(
        "test-tract",
        "tube",
    )

    actor_after = loaded_renderer.actors_by_id[
        "test-tract"
    ]

    assert actor_after is not actor_before
    assert len(loaded_renderer.actors_by_id) == count_before


def test_tube_radius_change_preserves_layer_properties(
    loaded_renderer: SceneRenderer,
) -> None:
    loaded_renderer.set_tract_visible(
        "test-tract",
        False,
    )
    loaded_renderer.set_tract_opacity(
        "test-tract",
        0.35,
    )
    loaded_renderer.set_render_mode(
        "test-tract",
        "tube",
    )
    loaded_renderer.set_tube_radius(
        "test-tract",
        0.8,
    )

    actor = loaded_renderer.actors_by_id["test-tract"]
    state = loaded_renderer.scene.tract_by_id(
        "test-tract"
    )

    assert not bool(actor.GetVisibility())
    assert actor.GetProperty().GetOpacity() == pytest.approx(
        0.35
    )
    assert state.tube_radius == pytest.approx(0.8)


def test_camera_capture_and_apply_round_trip(
    loaded_renderer: SceneRenderer,
) -> None:
    expected = CameraState(
        position=(50.0, 60.0, 70.0),
        focal_point=(1.0, 2.0, 3.0),
        view_up=(0.0, 0.0, 1.0),
        parallel_projection=True,
        parallel_scale=42.0,
        clipping_range=(0.5, 500.0),
    )

    loaded_renderer.apply_camera(
        expected,
        refresh=False,
    )
    observed = loaded_renderer.capture_camera()

    assert observed == expected


def test_export_dimensions_are_exact(
    loaded_renderer: SceneRenderer,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "render.png"

    loaded_renderer.export_png(
        output_path,
        width=640,
        height=480,
    )

    with Image.open(output_path) as image:
        assert image.size == (640, 480)
