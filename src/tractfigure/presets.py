"""Named anatomical presentation presets and the documented tract palette.

Presets restyle an existing scene (background, slice/mesh presentation,
palette colors) and never rename, reorder, add, or drop layers.

Palette: the Okabe-Ito categorical scheme, chosen for color-vision
deficiency safety in publication figures.
Reference: https://jfly.uni-koeln.de/color/ (Okabe & Ito palette).
"""

from dataclasses import dataclass
from typing import Literal

from tractfigure.scene_state_v1_20260730 import SceneState


@dataclass(frozen=True)
class PaletteColor:
    name: str
    hex_value: str


TRACT_PALETTE: tuple[PaletteColor, ...] = (
    PaletteColor("Orange", "#E69F00"),
    PaletteColor("Sky Blue", "#56B4E9"),
    PaletteColor("Bluish Green", "#009E73"),
    PaletteColor("Yellow", "#F0E442"),
    PaletteColor("Blue", "#0072B2"),
    PaletteColor("Vermillion", "#D55E00"),
    PaletteColor("Reddish Purple", "#CC79A7"),
)


@dataclass(frozen=True)
class PresentationPreset:
    name: str
    background: str
    image_visible: bool
    slices_visible: bool
    mesh_shader: Literal["phong", "outline"]
    mesh_opacity: float
    use_palette: bool
    view: tuple[str, str] | None


PRESENTATION_PRESETS: dict[str, PresentationPreset] = {
    preset.name: preset
    for preset in (
        PresentationPreset(
            name="orthographic-atlas",
            background="#FFFFFF",
            image_visible=False,
            slices_visible=False,
            mesh_shader="outline",
            mesh_opacity=0.85,
            use_palette=True,
            view=("coronal", "anterior"),
        ),
        PresentationPreset(
            name="clinical-dark",
            background="#000000",
            image_visible=True,
            slices_visible=True,
            mesh_shader="phong",
            mesh_opacity=0.25,
            use_palette=False,
            view=("sagittal", "left"),
        ),
    )
}

_SLICE_FIELDS = ("sagittal_visible", "coronal_visible", "axial_visible")


def apply_presentation_preset(
    scene: SceneState,
    preset: PresentationPreset,
) -> None:
    """Restyle the scene in place; layer identity and geometry stay untouched."""
    scene.canvas.background = preset.background
    scene.image.visible = preset.image_visible

    for field in _SLICE_FIELDS:
        setattr(scene.image, field, preset.slices_visible)

    if scene.mesh is not None:
        scene.mesh.shader = preset.mesh_shader
        scene.mesh.opacity = preset.mesh_opacity

    if preset.use_palette:
        for index, tract in enumerate(scene.tracts):
            tract.color = TRACT_PALETTE[index % len(TRACT_PALETTE)].hex_value
