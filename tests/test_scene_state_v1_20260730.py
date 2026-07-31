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


def make_scene() -> SceneState:
    return SceneState(
        image=ImageLayerState(
            path=Path("reference.nii.gz"),
            sagittal_visible=False,
        ),
        tracts=[
            TractLayerState(
                id="a",
                name="A",
                path=Path("a.trk"),
                color="#112233",
                opacity=0.5,
            ),
            TractLayerState(
                id="b",
                name="B",
                path=Path("b.tck"),
                color="#445566",
                visible=False,
                render_mode="line",
            ),
        ],
        active_layer_id="a",
        camera=CameraState(
            position=(10.0, 20.0, 30.0),
            focal_point=(1.0, 2.0, 3.0),
            view_up=(0.0, 0.0, 1.0),
            parallel_scale=20.0,
            clipping_range=(0.1, 1000.0),
        ),
        canvas=CanvasState(width=1400, height=1000, background="#FFFFFF"),
    )


def test_scene_json_round_trip_preserves_values_and_order() -> None:
    scene = make_scene()
    restored = SceneState.model_validate_json(scene.model_dump_json())
    assert restored.model_dump(mode="json") == scene.model_dump(mode="json")
    assert [tract.id for tract in restored.tracts] == ["a", "b"]


def test_scene_rejects_duplicate_ids() -> None:
    scene = make_scene()
    duplicate = scene.tracts[0].model_copy(update={"name": "Duplicate"})
    with pytest.raises(ValidationError, match="unique"):
        SceneState(
            image=scene.image,
            tracts=[scene.tracts[0], duplicate],
            active_layer_id="a",
        )


def test_scene_rejects_unknown_active_layer() -> None:
    scene = make_scene()
    with pytest.raises(ValidationError, match="active_layer_id"):
        SceneState.model_validate(
            {
                **scene.model_dump(),
                "active_layer_id": "missing",
            }
        )
