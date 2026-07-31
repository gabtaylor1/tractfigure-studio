from pathlib import Path

import pytest
from pydantic import ValidationError

from tractfigure.scene_state_v1_20260730 import (
    CameraState,
    CanvasState,
    ImageLayerState,
    SceneState,
    TractLayerState,
)


def make_camera() -> CameraState:
    return CameraState(
        position=(100.0, 120.0, 130.0),
        focal_point=(0.0, 0.0, 0.0),
        view_up=(0.0, 0.0, 1.0),
        parallel_projection=False,
        parallel_scale=75.0,
        clipping_range=(0.1, 1000.0),
    )


def make_scene() -> SceneState:
    tracts = [
        TractLayerState(
            id="tract-a",
            name="Tract A",
            path=Path("tract_a.trk"),
            color="#E64B35",
        ),
        TractLayerState(
            id="tract-b",
            name="Tract B",
            path=Path("tract_b.tck"),
            color="#4DBBD5",
        ),
    ]

    return SceneState(
        image=ImageLayerState(
            path=Path("reference.nii.gz")
        ),
        tracts=tracts,
        active_layer_id="tract-a",
        camera=make_camera(),
        canvas=CanvasState(),
    )


def test_scene_json_round_trip() -> None:
    scene = make_scene()

    restored = SceneState.model_validate_json(
        scene.model_dump_json()
    )

    assert restored == scene


def test_layer_order_is_preserved() -> None:
    scene = make_scene()

    restored = SceneState.model_validate_json(
        scene.model_dump_json()
    )

    assert [
        tract.id for tract in restored.tracts
    ] == ["tract-a", "tract-b"]


def test_active_layer_must_exist() -> None:
    payload = make_scene().model_dump()
    payload["active_layer_id"] = "missing-layer"

    with pytest.raises(
        ValidationError,
        match="active_layer_id",
    ):
        SceneState.model_validate(payload)


def test_duplicate_layer_ids_are_rejected() -> None:
    payload = make_scene().model_dump()
    payload["tracts"][1]["id"] = "tract-a"

    with pytest.raises(
        ValidationError,
        match="unique",
    ):
        SceneState.model_validate(payload)


@pytest.mark.parametrize("opacity", [-0.01, 1.01])
def test_invalid_opacity_is_rejected(
    opacity: float,
) -> None:
    with pytest.raises(ValidationError):
        TractLayerState(
            id="tract-a",
            name="Tract A",
            path=Path("tract_a.trk"),
            color="#E64B35",
            opacity=opacity,
        )


@pytest.mark.parametrize(
    "color",
    [
        "red",
        "#FFF",
        "#GG0000",
        "E64B35",
        "#E64B3500",
    ],
)
def test_invalid_color_is_rejected(
    color: str,
) -> None:
    with pytest.raises(ValidationError):
        TractLayerState(
            id="tract-a",
            name="Tract A",
            path=Path("tract_a.trk"),
            color=color,
        )


def test_camera_round_trip_is_exact() -> None:
    camera = make_camera()

    restored = CameraState.model_validate_json(
        camera.model_dump_json()
    )

    assert restored == camera


def test_unknown_fields_are_rejected() -> None:
    payload = make_scene().model_dump()
    payload["unexpected_field"] = 123

    with pytest.raises(
        ValidationError,
        match="extra",
    ):
        SceneState.model_validate(payload)
