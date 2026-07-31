from __future__ import annotations

import re
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
    active_layer_id: str | None = None
    camera: CameraState | None = None
    canvas: CanvasState = Field(default_factory=CanvasState)

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
