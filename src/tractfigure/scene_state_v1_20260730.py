from __future__ import annotations

import re
from math import isfinite
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_hex_color(value: str) -> str:
    if not HEX_COLOR_PATTERN.fullmatch(value):
        raise ValueError("Color must use hexadecimal #RRGGBB format")
    return value.upper()


class TractLayerState(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    path: Path
    visible: bool = True
    color: str
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    render_mode: Literal["line", "tube"] = "tube"
    line_width: float = Field(default=2.0, gt=0.0)
    tube_radius: float = Field(default=0.35, gt=0.0)
    tube_sides: int = Field(default=8, ge=3)
    max_streamlines: int = Field(default=5000, ge=1)
    coordinate_report: dict[str, Any] = Field(default_factory=dict)

    _validate_color = field_validator("color")(validate_hex_color)


class ImageLayerState(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    path: Path
    visible: bool = True
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)
    sagittal_visible: bool = True
    coronal_visible: bool = True
    axial_visible: bool = True
    sagittal_index: int | None = Field(default=None, ge=0)
    coronal_index: int | None = Field(default=None, ge=0)
    axial_index: int | None = Field(default=None, ge=0)
    # Manual registration, moving (native) RASMM -> fixed (displayed) RASMM, about the image centre.
    translation_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    @model_validator(mode="after")
    def validate_transform(self) -> ImageLayerState:
        values = self.translation_mm + self.rotation_deg + self.scale
        if not all(isfinite(value) for value in values):
            raise ValueError("Image transform values must be finite")

        if any(value <= 0 for value in self.scale):
            raise ValueError("Image scale values must be positive")

        return self


class LightingState(BaseModel):
    """Lighting rig for one group of actors (the glass brain, or every tract)."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    # "default" keeps VTK's shared light kit; every other preset is a view-space
    # rig applied to this group alone, so the two groups can be lit differently.
    preset: Literal[
        "default",
        "headlight",
        "three_point",
        "rim",
        "soft",
        "flat",
    ] = "default"
    intensity: float = Field(default=1.0, ge=0.0, le=3.0)
    ambient: float = Field(default=0.15, ge=0.0, le=1.0)
    specular: float = Field(default=0.3, ge=0.0, le=1.0)


class SceneLightingState(BaseModel):
    """Independent lighting rigs for the glass brain and the tracts."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    mesh: LightingState = Field(default_factory=LightingState)
    tracts: LightingState = Field(default_factory=LightingState)


class MeshLayerState(BaseModel):
    """Translucent cortical surface (GIFTI) drawn over the tracts as a glass brain."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    path: Path
    opacity: float = Field(default=0.25, ge=0.0, le=1.0)
    color: str = "#D9D9D9"
    shader: Literal["phong", "outline"] = "phong"

    _validate_color = field_validator("color")(validate_hex_color)


class CameraState(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    position: tuple[float, float, float]
    focal_point: tuple[float, float, float]
    view_up: tuple[float, float, float]
    parallel_projection: bool = False
    parallel_scale: float = Field(gt=0.0)
    clipping_range: tuple[float, float]

    @model_validator(mode="after")
    def validate_clipping_range(self) -> CameraState:
        near, far = self.clipping_range

        if near <= 0:
            raise ValueError("Camera near clipping distance must be positive")

        if far <= near:
            raise ValueError("Camera far clipping distance must exceed the near distance")

        return self


class CanvasState(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    width: int = Field(default=1400, ge=1)
    height: int = Field(default=1000, ge=1)
    background: str = "#FFFFFF"

    _validate_background = field_validator("background")(validate_hex_color)


class SceneState(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    schema_version: Literal["1.0"] = "1.0"
    image: ImageLayerState
    tracts: list[TractLayerState]
    mesh: MeshLayerState | None = None
    active_layer_id: str | None = None
    camera: CameraState | None = None
    canvas: CanvasState = Field(default_factory=CanvasState)
    lighting: SceneLightingState = Field(default_factory=SceneLightingState)

    @model_validator(mode="after")
    def validate_layer_identity(self) -> SceneState:
        layer_ids = [tract.id for tract in self.tracts]

        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("Every tract layer ID must be unique")

        if self.active_layer_id is not None and self.active_layer_id not in layer_ids:
            raise ValueError("active_layer_id must identify a tract in this scene")

        return self

    def tract_by_id(self, layer_id: str) -> TractLayerState:
        for tract in self.tracts:
            if tract.id == layer_id:
                return tract

        raise KeyError(f"Unknown tract layer ID: {layer_id}")
