from pathlib import Path

import pytest

from tractfigure.presets import (
    PRESENTATION_PRESETS,
    TRACT_PALETTE,
    apply_presentation_preset,
)
from tractfigure.scene_state_v1_20260730 import (
    ImageLayerState,
    MeshLayerState,
    SceneState,
    TractLayerState,
)


def build_scene() -> SceneState:
    return SceneState(
        image=ImageLayerState(path=Path("t1.nii.gz")),
        tracts=[
            TractLayerState(
                id=f"tract-{index}",
                name=f"tract-{index}",
                path=Path(f"bundle-{index}.trk"),
                color="#112233",
            )
            for index in range(3)
        ],
        mesh=MeshLayerState(path=Path("surface.gii"), shader="outline", opacity=1.0),
        active_layer_id="tract-0",
    )


def test_preset_palette_is_named_valid_hex_and_unique() -> None:
    hex_values = [entry.hex_value for entry in TRACT_PALETTE]

    assert len(hex_values) >= 5
    assert len(set(hex_values)) == len(hex_values)
    assert len({entry.name for entry in TRACT_PALETTE}) == len(TRACT_PALETTE)
    for value in hex_values:
        assert value.startswith("#")
        assert len(value) == 7


def test_preset_application_restyles_without_renaming_layers() -> None:
    scene = build_scene()
    before = [(tract.id, tract.name, tract.path) for tract in scene.tracts]

    apply_presentation_preset(scene, PRESENTATION_PRESETS["orthographic-atlas"])

    assert [(tract.id, tract.name, tract.path) for tract in scene.tracts] == before
    assert scene.active_layer_id == "tract-0"
    assert scene.canvas.background == "#FFFFFF"
    assert scene.image.visible is False
    assert (
        scene.image.sagittal_visible
        and scene.image.coronal_visible
        and scene.image.axial_visible
    ) is False
    assert scene.mesh.shader == "outline"
    assert scene.mesh.opacity == pytest.approx(0.85)
    assert [tract.color for tract in scene.tracts] == [
        entry.hex_value for entry in TRACT_PALETTE[:3]
    ]


def test_preset_application_is_deterministic_across_scenes_and_repeats() -> None:
    first = build_scene()
    second = build_scene()

    apply_presentation_preset(first, PRESENTATION_PRESETS["clinical-dark"])
    apply_presentation_preset(second, PRESENTATION_PRESETS["clinical-dark"])
    apply_presentation_preset(second, PRESENTATION_PRESETS["clinical-dark"])

    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    reloaded = SceneState.model_validate_json(first.model_dump_json())
    assert reloaded.model_dump(mode="json") == first.model_dump(mode="json")


def test_preset_without_palette_keeps_tract_colors() -> None:
    scene = build_scene()

    apply_presentation_preset(scene, PRESENTATION_PRESETS["clinical-dark"])

    assert all(tract.color == "#112233" for tract in scene.tracts)
    assert scene.canvas.background == "#000000"
    assert scene.image.visible is True
    assert scene.mesh.shader == "phong"
    assert scene.mesh.opacity == pytest.approx(0.25)
