from __future__ import annotations

import argparse
from datetime import datetime
from itertools import cycle
from math import isfinite
from pathlib import Path
from types import MethodType
from typing import Any
from uuid import uuid4

import pyvista as pv
from pyvista.trame.ui import get_viewer, plotter_ui
from pyvista.trame.ui.vuetify3 import button as pv_button
from pyvista.trame.ui.vuetify3 import checkbox as pv_checkbox
from pyvista.trame.ui.vuetify3 import divider as pv_divider
from trame.app import get_server
from trame.ui.vuetify3 import SinglePageWithDrawerLayout
from trame.widgets import vuetify3 as v3

from tractfigure.renderer_trame_v1_20260730 import SceneRenderer
from tractfigure.scene_state_v1_20260730 import (
    CanvasState,
    ImageLayerState,
    SceneState,
    TractLayerState,
)

DEFAULT_COLORS = (
    "#E64B35",
    "#4DBBD5",
    "#00A087",
    "#3C5488",
    "#F39B7F",
    "#8491B4",
    "#91D1C2",
)

SLICE_VISIBILITY_FIELDS = {
    "sagittal": "sagittal_visible",
    "coronal": "coronal_visible",
    "axial": "axial_visible",
}

ANATOMICAL_PRIMARY_SIDES = {
    "sagittal": "left",
    "coronal": "anterior",
    "axial": "superior",
}

ANATOMICAL_OPPOSITE_SIDES = {
    "left": "right",
    "right": "left",
    "anterior": "posterior",
    "posterior": "anterior",
    "superior": "inferior",
    "inferior": "superior",
}


def color_with_alpha(color: str, opacity: float) -> str:
    alpha = int(round(float(opacity) * 255.0))
    alpha = max(0, min(255, alpha))
    return f"{color.upper()}{alpha:02X}"


NUMERIC_CONTROL_CONFIG: dict[
    str,
    tuple[float, float | str, bool],
] = {
    "slice_opacity": (0.0, 1.0, False),
    "sagittal_index": (0.0, "sagittal_max", True),
    "coronal_index": (0.0, "coronal_max", True),
    "axial_index": (0.0, "axial_max", True),
    "active_line_width": (0.5, 10.0, False),
    "active_tube_radius": (0.05, 2.0, False),
    "active_tube_sides": (3.0, 24.0, True),
}

ACTIVE_NUMERIC_MODELS = (
    "active_line_width",
    "active_tube_radius",
    "active_tube_sides",
)


def split_color_and_alpha(
    value: str,
) -> tuple[str, float | None]:
    if not isinstance(value, str):
        raise ValueError("Color picker must return a hexadecimal color")

    normalized = value.strip().upper()

    if not normalized.startswith("#"):
        raise ValueError("Color must begin with #")

    if len(normalized) not in {7, 9}:
        raise ValueError("Color must use #RRGGBB or #RRGGBBAA format")

    try:
        int(normalized[1:], 16)
    except ValueError as error:
        raise ValueError("Color contains non-hexadecimal characters") from error

    color = normalized[:7]

    if len(normalized) == 7:
        return color, None

    opacity = int(normalized[7:9], 16) / 255.0
    return color, opacity


def numeric_slider(
    *,
    label: str,
    model: str,
    value: float | int,
    minimum: float | int,
    maximum: float | int | tuple[str, int],
    step: float | int,
    input_model: str,
    commit: Any,
    v_if: str | None = None,
) -> None:
    row_arguments: dict[str, Any] = {
        "classes": "ma-0 align-center",
    }

    if v_if is not None:
        row_arguments["v_if"] = v_if

    with v3.VRow(**row_arguments):
        with v3.VCol(
            cols=9,
            classes="pa-0 pr-2",
        ):
            v3.VSlider(
                label=label,
                v_model=(model, value),
                min=minimum,
                max=maximum,
                step=step,
                thumb_label=True,
                hide_details=True,
            )

        with v3.VCol(
            cols=3,
            classes="pa-0",
        ):
            v3.VTextField(
                v_model=(
                    input_model,
                    format_numeric_value(
                        value,
                        integer=step == 1,
                    ),
                ),
                type="text",
                inputmode="decimal",
                autocomplete="off",
                focus="$event.target.select()",
                blur=commit,
                density="compact",
                variant="outlined",
                hide_details=True,
                aria_label=f"{label} value",
            )


def format_numeric_value(
    value: float | int | None,
    *,
    integer: bool,
) -> str:
    if value is None:
        return ""

    numeric = float(value)

    if integer:
        return str(int(round(numeric)))

    return f"{numeric:g}"


def unique_layer_names(paths: list[Path]) -> list[str]:
    occurrences: dict[str, int] = {}
    names: list[str] = []

    for path in paths:
        base = path.stem
        occurrences[base] = occurrences.get(base, 0) + 1
        count = occurrences[base]

        names.append(
            base if count == 1 else f"{base} ({count})"
        )

    return names


def scene_from_inputs(
    reference_path: Path,
    tractogram_paths: list[Path],
) -> SceneState:
    reference_path = reference_path.expanduser().resolve()
    tractogram_paths = [
        path.expanduser().resolve()
        for path in tractogram_paths
    ]

    if not reference_path.is_file():
        raise FileNotFoundError(
            f"Reference image does not exist: {reference_path}"
        )

    if not tractogram_paths:
        raise ValueError("At least one tractogram is required")

    for path in tractogram_paths:
        if not path.is_file():
            raise FileNotFoundError(
                f"Tractogram does not exist: {path}"
            )

    colors = cycle(DEFAULT_COLORS)
    names = unique_layer_names(tractogram_paths)

    tracts = [
        TractLayerState(
            id=str(uuid4()),
            name=name,
            path=path,
            color=color,
        )
        for path, name, color in zip(
            tractogram_paths,
            names,
            colors,
            strict=False,
        )
    ]

    return SceneState(
        image=ImageLayerState(path=reference_path),
        tracts=tracts,
        active_layer_id=tracts[0].id,
        canvas=CanvasState(),
    )


def resolve_recipe_paths(
    scene: SceneState,
    recipe_path: Path,
) -> SceneState:
    recipe_directory = recipe_path.resolve().parent
    resolved = scene.model_copy(deep=True)

    if not resolved.image.path.is_absolute():
        resolved.image.path = (
            recipe_directory / resolved.image.path
        ).resolve()

    for tract in resolved.tracts:
        if not tract.path.is_absolute():
            tract.path = (
                recipe_directory / tract.path
            ).resolve()

    return resolved


def load_recipe(recipe_path: Path) -> SceneState:
    recipe_path = recipe_path.expanduser().resolve()

    if not recipe_path.is_file():
        raise FileNotFoundError(
            f"Scene recipe does not exist: {recipe_path}"
        )

    scene = SceneState.model_validate_json(
        recipe_path.read_text(encoding="utf-8")
    )
    return resolve_recipe_paths(scene, recipe_path)


class TractFigureController:
    def __init__(
        self,
        server: Any,
        renderer: SceneRenderer,
        output_directory: Path,
    ) -> None:
        self.server = server
        self.state = server.state
        self.ctrl = server.controller
        self.renderer = renderer
        self.scene = renderer._require_scene()
        self.output_directory = output_directory.resolve()
        self.view: Any | None = None

        self.visibility_keys: dict[str, str] = {}
        self.color_keys: dict[str, str] = {}
        self.callbacks: list[Any] = []
        self.numeric_commit_actions: dict[str, Any] = {}
        self._state_sync_in_progress = False
        self._last_anatomical_plane: str | None = None
        self._anatomical_side: dict[str, str] = {}

        self._initialize_state()
        self.initial_scene = self.scene.model_copy(deep=True)
        self._register_callbacks()
        self._register_controller_actions()

    def _initialize_state(self) -> None:
        image_shape = self.renderer.image_shape

        if image_shape is None:
            raise RuntimeError("Reference image has not been loaded")

        self.state.trame__title = "TractFigure Studio"
        self.state.render_mode_items = ["tube", "line"]

        self.state.reference_visible = self.scene.image.visible
        self.state.slice_opacity = self.scene.image.opacity
        self.state.scene_background = self.scene.canvas.background

        for slice_name, field_name in (
            SLICE_VISIBILITY_FIELDS.items()
        ):
            setattr(
                self.state,
                f"{slice_name}_visible",
                getattr(self.scene.image, field_name),
            )

        self.state.sagittal_index = (
            self.scene.image.sagittal_index
        )
        self.state.coronal_index = (
            self.scene.image.coronal_index
        )
        self.state.axial_index = self.scene.image.axial_index

        self.state.sagittal_max = image_shape[0] - 1
        self.state.coronal_max = image_shape[1] - 1
        self.state.axial_max = image_shape[2] - 1

        self.state.all_tracts_visible = all(
            tract.visible for tract in self.scene.tracts
        )

        for index, tract in enumerate(self.scene.tracts):
            visibility_key = f"layer_visible_{index}"
            color_key = f"layer_color_{index}"

            self.visibility_keys[tract.id] = visibility_key
            self.color_keys[tract.id] = color_key

            setattr(
                self.state,
                visibility_key,
                tract.visible,
            )
            setattr(
                self.state,
                color_key,
                tract.color,
            )

        self._refresh_layer_items()

        if self.scene.active_layer_id is None and self.scene.tracts:
            self.scene.active_layer_id = self.scene.tracts[0].id

        self.state.active_layer_id = self.scene.active_layer_id
        self.state.status_message = "Scene loaded"
        self.state.export_path = ""

        self._populate_active_controls()
        self._synchronize_numeric_inputs()

    def _register_callbacks(self) -> None:
        self.callbacks.append(
            self.state.change("all_tracts_visible")(
                self._on_all_tracts_visible
            )
        )
        self.callbacks.append(
            self.state.change("active_layer_id")(
                self._on_active_layer_changed
            )
        )
        self.callbacks.append(
            self.state.change("reference_visible")(
                self._on_reference_visible
            )
        )
        self.callbacks.append(
            self.state.change("slice_opacity")(
                self._on_slice_opacity
            )
        )
        self.callbacks.append(
            self.state.change("scene_background")(
                self._on_scene_background
            )
        )

        for slice_name in SLICE_VISIBILITY_FIELDS:
            state_key = f"{slice_name}_visible"
            callback = self._make_slice_visibility_callback(
                slice_name,
                state_key,
            )
            self.callbacks.append(
                self.state.change(state_key)(callback)
            )

        for key in (
            "sagittal_index",
            "coronal_index",
            "axial_index",
        ):
            self.callbacks.append(
                self.state.change(key)(
                    self._on_slice_indices
                )
            )

        for key, callback in (
            ("active_color", self._on_active_color),
            (
                "active_render_mode",
                self._on_active_render_mode,
            ),
            (
                "active_line_width",
                self._on_active_line_width,
            ),
            (
                "active_tube_radius",
                self._on_active_tube_radius,
            ),
            (
                "active_tube_sides",
                self._on_active_tube_sides,
            ),
        ):
            self.callbacks.append(
                self.state.change(key)(callback)
            )

        for tract in self.scene.tracts:
            key = self.visibility_keys[tract.id]
            callback = self._make_visibility_callback(
                tract.id,
                key,
            )
            self.callbacks.append(
                self.state.change(key)(callback)
            )

    def _register_controller_actions(self) -> None:
        self.ctrl.reset_camera = self.reset_camera
        self.ctrl.reset_active_tract_settings = (
            self.reset_active_tract_settings
        )
        self.ctrl.reset_all_settings = self.reset_all_settings
        self.ctrl.view_perspective = self.view_perspective
        self.ctrl.view_sagittal = self.view_sagittal
        self.ctrl.view_coronal = self.view_coronal
        self.ctrl.view_axial = self.view_axial
        self.ctrl.save_scene = self.save_scene
        self.ctrl.export_png = self.export_png

        for model in NUMERIC_CONTROL_CONFIG:
            callback = self._make_numeric_commit_callback(model)
            action_name = f"commit_{model}_input"
            self.numeric_commit_actions[model] = callback
            setattr(self.ctrl, action_name, callback)

    def _make_visibility_callback(
        self,
        layer_id: str,
        state_key: str,
    ):
        def callback(**kwargs: Any) -> None:
            if self._state_sync_in_progress:
                return

            value = bool(kwargs.get(state_key))
            tract = self.scene.tract_by_id(layer_id)

            if tract.visible == value:
                return

            self.renderer.set_tract_visible(
                layer_id,
                value,
            )

            self.state.all_tracts_visible = all(
                item.visible for item in self.scene.tracts
            )
            self._refresh_layer_items()
            self.update_view()

        return callback

    def _active_tract(self) -> TractLayerState | None:
        layer_id = self.state.active_layer_id

        if layer_id is None:
            return None

        try:
            return self.scene.tract_by_id(layer_id)
        except KeyError:
            return None

    def _make_slice_visibility_callback(
        self,
        slice_name: str,
        state_key: str,
    ):
        def callback(**kwargs: Any) -> None:
            if self._state_sync_in_progress:
                return

            visible = bool(kwargs.get(state_key))
            field_name = SLICE_VISIBILITY_FIELDS[slice_name]

            if getattr(self.scene.image, field_name) == visible:
                return

            self.renderer.set_slice_visible(
                slice_name,
                visible,
            )
            self.update_view()

        return callback

    def _refresh_layer_items(self) -> None:
        self.state.layer_items = [
            {
                "id": tract.id,
                "name": tract.name,
                "color": tract.color,
                "visible": tract.visible,
                "warning_count": len(
                    tract.coordinate_report.get(
                        "warnings",
                        (),
                    )
                ),
            }
            for tract in self.scene.tracts
        ]

    def _populate_active_controls(self) -> None:
        tract = self._active_tract()

        if tract is None:
            self.state.active_color = "#808080FF"
            self.state.active_render_mode = "tube"
            self.state.active_line_width = 2.0
            self.state.active_tube_radius = 0.35
            self.state.active_tube_sides = 8
            self.state.active_warnings_text = ""
            self.state.active_warnings_visible = False
            self._synchronize_numeric_inputs(
                ACTIVE_NUMERIC_MODELS
            )
            return

        self.state.active_color = color_with_alpha(
            tract.color,
            tract.opacity,
        )
        self.state.active_render_mode = tract.render_mode
        self.state.active_line_width = tract.line_width
        self.state.active_tube_radius = tract.tube_radius
        self.state.active_tube_sides = tract.tube_sides

        warnings = tract.coordinate_report.get(
            "warnings",
            (),
        )
        self.state.active_warnings_text = "\n".join(
            str(warning) for warning in warnings
        )
        self.state.active_warnings_visible = bool(warnings)

        self._synchronize_numeric_inputs(
            ACTIVE_NUMERIC_MODELS
        )

    def _synchronize_state_from_scene(self) -> None:
        self._state_sync_in_progress = True

        try:
            self.state.reference_visible = self.scene.image.visible
            self.state.slice_opacity = self.scene.image.opacity
            self.state.scene_background = (
                self.scene.canvas.background
            )

            for slice_name, field_name in (
                SLICE_VISIBILITY_FIELDS.items()
            ):
                setattr(
                    self.state,
                    f"{slice_name}_visible",
                    getattr(self.scene.image, field_name),
                )

            self.state.sagittal_index = (
                self.scene.image.sagittal_index
            )
            self.state.coronal_index = (
                self.scene.image.coronal_index
            )
            self.state.axial_index = self.scene.image.axial_index
            self.state.all_tracts_visible = all(
                tract.visible for tract in self.scene.tracts
            )

            for tract in self.scene.tracts:
                setattr(
                    self.state,
                    self.visibility_keys[tract.id],
                    tract.visible,
                )
                setattr(
                    self.state,
                    self.color_keys[tract.id],
                    tract.color,
                )

            self.state.active_layer_id = (
                self.scene.active_layer_id
            )
            self._refresh_layer_items()
            self._populate_active_controls()
            self._synchronize_numeric_inputs()
        finally:
            self._state_sync_in_progress = False

    def set_view(self, view: Any) -> None:
        self.view = view
        self.ctrl.view_update = view.update
        self.ctrl.view_reset_camera = self.reset_camera

    def update_view(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        if self.view is not None:
            self.view.update()

    def _synchronize_camera_to_view(self) -> None:
        if self.view is None:
            return

        update_camera = getattr(
            self.view,
            "update_camera",
            None,
        )

        if callable(update_camera):
            update_camera()
        else:
            self.view.update()

    def _assign_state_without_callback(
        self,
        key: str,
        value: Any,
    ) -> None:
        previous = self._state_sync_in_progress
        self._state_sync_in_progress = True

        try:
            setattr(self.state, key, value)
        finally:
            self._state_sync_in_progress = previous

    def _numeric_bounds(
        self,
        key: str,
    ) -> tuple[float, float, bool]:
        minimum, maximum_source, integer = (
            NUMERIC_CONTROL_CONFIG[key]
        )

        if isinstance(maximum_source, str):
            maximum = float(
                getattr(self.state, maximum_source)
            )
        else:
            maximum = float(maximum_source)

        return float(minimum), maximum, integer

    def _synchronize_numeric_input(
        self,
        key: str,
        value: float | int | None = None,
    ) -> None:
        if value is None:
            value = getattr(self.state, key)

        _minimum, _maximum, integer = self._numeric_bounds(key)
        self._assign_state_without_callback(
            f"{key}_input",
            format_numeric_value(
                value,
                integer=integer,
            ),
        )

    def _synchronize_numeric_inputs(
        self,
        models: tuple[str, ...] | None = None,
    ) -> None:
        selected = (
            tuple(NUMERIC_CONTROL_CONFIG)
            if models is None
            else models
        )

        for key in selected:
            self._synchronize_numeric_input(key)

    def _make_numeric_commit_callback(self, key: str):
        def callback(
            *_args: Any,
            **_kwargs: Any,
        ) -> None:
            self._commit_numeric_input(key)

        return callback

    def _restore_numeric_input(
        self,
        key: str,
        message: str,
    ) -> None:
        self._synchronize_numeric_input(key)
        self.state.status_message = message

    def _commit_numeric_input(self, key: str) -> None:
        input_key = f"{key}_input"
        raw_value = getattr(self.state, input_key, "")
        text = "" if raw_value is None else str(raw_value).strip()
        label = key.replace("_", " ").capitalize()

        if not text:
            self._restore_numeric_input(
                key,
                f"{label} was left blank; previous value retained",
            )
            return

        try:
            numeric = float(text)
        except ValueError:
            self._restore_numeric_input(
                key,
                f"{label} must be numeric; previous value retained",
            )
            return

        minimum, maximum, integer = self._numeric_bounds(key)

        if not isfinite(numeric):
            self._restore_numeric_input(
                key,
                f"{label} must be finite; previous value retained",
            )
            return

        if numeric < minimum or numeric > maximum:
            self._restore_numeric_input(
                key,
                f"{label} must be between {minimum:g} and "
                f"{maximum:g}; previous value retained",
            )
            return

        if integer and not numeric.is_integer():
            self._restore_numeric_input(
                key,
                f"{label} must be a whole number; "
                "previous value retained",
            )
            return

        normalized: float | int = (
            int(numeric) if integer else numeric
        )
        setattr(self.state, key, normalized)
        self._synchronize_numeric_input(key, normalized)
        self.state.status_message = (
            f"{label} set to "
            f"{format_numeric_value(normalized, integer=integer)}"
        )

    def _normalize_numeric_state(
        self,
        *,
        key: str,
        raw_value: Any,
        current_value: float | int,
        minimum: float | int,
        maximum: float | int,
        integer: bool = False,
    ) -> float | int | None:
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError):
            self._assign_state_without_callback(
                key,
                current_value,
            )
            self._synchronize_numeric_input(
                key,
                current_value,
            )
            self.state.status_message = (
                f"{key.replace('_', ' ').capitalize()} "
                "must be numeric"
            )
            return None

        if not isfinite(numeric):
            self._assign_state_without_callback(
                key,
                current_value,
            )
            self._synchronize_numeric_input(
                key,
                current_value,
            )
            self.state.status_message = (
                f"{key.replace('_', ' ').capitalize()} "
                "must be finite"
            )
            return None

        bounded = max(float(minimum), min(float(maximum), numeric))
        normalized: float | int

        if integer:
            normalized = int(round(bounded))
        else:
            normalized = bounded

        if raw_value != normalized:
            self._assign_state_without_callback(
                key,
                normalized,
            )

        self._synchronize_numeric_input(
            key,
            normalized,
        )

        return normalized

    def _on_all_tracts_visible(
        self,
        all_tracts_visible: bool,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        target = bool(all_tracts_visible)

        if target == all(
            tract.visible for tract in self.scene.tracts
        ):
            return

        self.renderer.set_all_tracts_visible(target)

        for tract in self.scene.tracts:
            setattr(
                self.state,
                self.visibility_keys[tract.id],
                target,
            )

        self._refresh_layer_items()
        self.update_view()

    def _on_active_layer_changed(
        self,
        active_layer_id: str | None,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        if active_layer_id is None:
            return

        try:
            self.scene.tract_by_id(active_layer_id)
        except KeyError:
            return

        self.scene.active_layer_id = active_layer_id
        self._populate_active_controls()

    def _on_reference_visible(
        self,
        reference_visible: bool,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        target = bool(reference_visible)

        if self.scene.image.visible == target:
            return

        self.renderer.set_image_visible(target)
        self.update_view()

    def _on_slice_opacity(
        self,
        slice_opacity: float,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        opacity = self._normalize_numeric_state(
            key="slice_opacity",
            raw_value=slice_opacity,
            current_value=self.scene.image.opacity,
            minimum=0.0,
            maximum=1.0,
        )

        if opacity is None:
            return

        if abs(self.scene.image.opacity - opacity) < 1e-9:
            return

        self.renderer.set_image_opacity(opacity)
        self.update_view()

    def _on_scene_background(
        self,
        scene_background: str,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        try:
            color, _opacity = split_color_and_alpha(
                scene_background
            )
        except ValueError as error:
            self._assign_state_without_callback(
                "scene_background",
                self.scene.canvas.background,
            )
            self.state.status_message = str(error)
            return

        if self.scene.canvas.background == color:
            return

        normalized = self.renderer.set_background(color)
        self._assign_state_without_callback(
            "scene_background",
            normalized,
        )
        self.state.status_message = (
            f"Background changed to {normalized}"
        )
        self.update_view()

    def _on_slice_indices(
        self,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        current = (
            self.scene.image.sagittal_index,
            self.scene.image.coronal_index,
            self.scene.image.axial_index,
        )

        normalized = tuple(
            self._normalize_numeric_state(
                key=key,
                raw_value=getattr(self.state, key),
                current_value=current_value,
                minimum=0,
                maximum=maximum,
                integer=True,
            )
            for key, current_value, maximum in zip(
                (
                    "sagittal_index",
                    "coronal_index",
                    "axial_index",
                ),
                current,
                (
                    self.state.sagittal_max,
                    self.state.coronal_max,
                    self.state.axial_max,
                ),
                strict=True,
            )
        )

        if any(value is None for value in normalized):
            return

        indices = tuple(int(value) for value in normalized)

        if indices == current:
            return

        self.renderer.set_slice_indices(*indices)
        self.update_view()

    def _on_active_color(
        self,
        active_color: str,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        tract = self._active_tract()

        if tract is None:
            return

        try:
            color, opacity = split_color_and_alpha(active_color)
        except ValueError as error:
            self.state.status_message = str(error)
            self._assign_state_without_callback(
                "active_color",
                color_with_alpha(tract.color, tract.opacity),
            )
            return

        target_opacity = (
            tract.opacity if opacity is None else opacity
        )

        if (
            tract.color == color
            and abs(tract.opacity - target_opacity) < 1e-9
        ):
            return

        self.renderer.set_tract_appearance(
            tract.id,
            color,
            target_opacity,
        )
        setattr(
            self.state,
            self.color_keys[tract.id],
            tract.color,
        )
        self._refresh_layer_items()
        self.update_view()

    def _on_active_render_mode(
        self,
        active_render_mode: str,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        tract = self._active_tract()

        if (
            tract is None
            or tract.render_mode == active_render_mode
        ):
            return

        self.renderer.set_render_mode(
            tract.id,
            active_render_mode,
        )
        self.update_view()

    def _on_active_line_width(
        self,
        active_line_width: float,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        tract = self._active_tract()

        if tract is None:
            return

        width = self._normalize_numeric_state(
            key="active_line_width",
            raw_value=active_line_width,
            current_value=tract.line_width,
            minimum=0.5,
            maximum=10.0,
        )

        if width is None:
            return

        if abs(tract.line_width - width) < 1e-9:
            return

        self.renderer.set_line_width(
            tract.id,
            width,
        )
        self.update_view()

    def _on_active_tube_radius(
        self,
        active_tube_radius: float,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        tract = self._active_tract()

        if tract is None:
            return

        radius = self._normalize_numeric_state(
            key="active_tube_radius",
            raw_value=active_tube_radius,
            current_value=tract.tube_radius,
            minimum=0.05,
            maximum=2.0,
        )

        if radius is None:
            return

        if abs(tract.tube_radius - radius) < 1e-9:
            return

        self.renderer.set_tube_radius(
            tract.id,
            radius,
        )
        self.update_view()

    def _on_active_tube_sides(
        self,
        active_tube_sides: int,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        tract = self._active_tract()

        if tract is None:
            return

        sides = self._normalize_numeric_state(
            key="active_tube_sides",
            raw_value=active_tube_sides,
            current_value=tract.tube_sides,
            minimum=3,
            maximum=24,
            integer=True,
        )

        if sides is None:
            return

        if tract.tube_sides == sides:
            return

        self.renderer.set_tube_sides(
            tract.id,
            sides,
        )
        self.update_view()

    def _set_anatomical_view(self, plane: str) -> None:
        primary = ANATOMICAL_PRIMARY_SIDES[plane]

        if self._last_anatomical_plane == plane:
            current = self._anatomical_side.get(
                plane,
                primary,
            )
            side = ANATOMICAL_OPPOSITE_SIDES[current]
        else:
            side = primary

        self.renderer.set_anatomical_view(plane, side)
        self._last_anatomical_plane = plane
        self._anatomical_side[plane] = side
        self._synchronize_camera_to_view()
        self.state.status_message = (
            f"{plane.capitalize()} view: {side.capitalize()}"
        )

    def view_sagittal(self) -> None:
        self._set_anatomical_view("sagittal")

    def view_coronal(self) -> None:
        self._set_anatomical_view("coronal")

    def view_axial(self) -> None:
        self._set_anatomical_view("axial")

    def view_perspective(self) -> None:
        self.renderer.set_perspective_view()
        self._last_anatomical_plane = None
        self._synchronize_camera_to_view()
        self.state.status_message = "Perspective view"

    def reset_camera(self) -> None:
        self.renderer.reset_camera()
        self._last_anatomical_plane = None
        self._anatomical_side.clear()
        self._synchronize_camera_to_view()
        self.state.status_message = "Camera reset"

    def reset_active_tract_settings(self) -> None:
        tract = self._active_tract()

        if tract is None:
            self.state.status_message = "No active tract selected"
            return

        initial = self.initial_scene.tract_by_id(tract.id)

        if tract.color != initial.color:
            self.renderer.set_tract_color(
                tract.id,
                initial.color,
            )

        if abs(tract.opacity - initial.opacity) >= 1e-9:
            self.renderer.set_tract_opacity(
                tract.id,
                initial.opacity,
            )

        if tract.render_mode != initial.render_mode:
            self.renderer.set_render_mode(
                tract.id,
                initial.render_mode,
            )

        if abs(tract.line_width - initial.line_width) >= 1e-9:
            self.renderer.set_line_width(
                tract.id,
                initial.line_width,
            )

        if abs(tract.tube_radius - initial.tube_radius) >= 1e-9:
            self.renderer.set_tube_radius(
                tract.id,
                initial.tube_radius,
            )

        if tract.tube_sides != initial.tube_sides:
            self.renderer.set_tube_sides(
                tract.id,
                initial.tube_sides,
            )

        if tract.visible != initial.visible:
            self.renderer.set_tract_visible(
                tract.id,
                initial.visible,
            )

        self._synchronize_state_from_scene()
        self.state.status_message = (
            f"Reset tract settings: {tract.name}"
        )
        self.update_view()

    def reset_all_settings(self) -> None:
        self.scene = self.renderer.restore_scene_settings(
            self.initial_scene
        )
        self._last_anatomical_plane = None
        self._anatomical_side.clear()
        self._synchronize_state_from_scene()
        self.update_view()
        self._synchronize_camera_to_view()
        self.state.status_message = "All settings reset"

    def _timestamp(self) -> str:
        return datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

    def _flush_state(self) -> None:
        flush = getattr(self.state, "flush", None)

        if callable(flush):
            flush()

    def _set_output_success(
        self,
        message: str,
        saved_path: Path,
    ) -> None:
        self.state.status_message = (
            f"{message}: {saved_path.name}"
        )
        self.state.export_path = str(saved_path)
        self._flush_state()

    def _set_output_failure(
        self,
        action: str,
        error: Exception,
    ) -> None:
        self.state.status_message = (
            f"{action} failed: "
            f"{type(error).__name__}: {error}"
        )
        self.state.export_path = ""
        self._flush_state()

    def save_scene(self) -> Path:
        try:
            output_path = (
                self.output_directory
                / f"tractfigure_scene_{self._timestamp()}.json"
            )
            saved_path = self.renderer.save_scene(output_path)
        except Exception as error:
            self._set_output_failure("Save scene", error)
            raise

        self._set_output_success(
            "Scene recipe saved; browser download ready",
            saved_path,
        )
        return saved_path

    def download_scene(self) -> bytes:
        saved_path = self.save_scene()

        try:
            return saved_path.read_bytes()
        except OSError as error:
            self._set_output_failure(
                "Read saved scene for download",
                error,
            )
            raise

    def export_png(self) -> Path:
        try:
            output_path = (
                self.output_directory
                / f"tractfigure_render_{self._timestamp()}.png"
            )

            self.scene.camera = self.renderer.capture_camera()

            saved_path = self.renderer.export_png(
                output_path,
                self.scene.canvas.width,
                self.scene.canvas.height,
            )
        except Exception as error:
            self._set_output_failure("Export PNG", error)
            raise

        self._set_output_success(
            "PNG exported; browser download ready",
            saved_path,
        )
        return saved_path

    def download_png(self) -> bytes:
        try:
            self.scene.camera = self.renderer.capture_camera()
            png_data = self.renderer.screenshot_png(
                self.scene.canvas.width,
                self.scene.canvas.height,
            )
        except Exception as error:
            self._set_output_failure(
                "Export PNG",
                error,
            )
            raise

        self.state.status_message = "PNG download ready"
        self.state.export_path = "Browser download"
        self._flush_state()
        return png_data


def install_viewer_controls(
    viewer: Any,
    controller: TractFigureController,
) -> None:
    def ui_controls(
        self: Any,
        mode: str | None = None,
        default_server_rendering: bool = True,
        v_show: Any = None,
    ) -> Any:
        with v3.VRow(
            v_show=v_show,
            classes="pa-0 ma-0 align-center fill-height",
            style="flex-wrap: nowrap",
        ) as row:
            server = row.server

            for state_key, callback in (
                (self.GRID, self.on_grid_visibility_change),
                (self.OUTLINE, self.on_outline_visibility_change),
                (
                    self.SERVER_RENDERING,
                    self.on_rendering_mode_change,
                ),
            ):
                controller.callbacks.append(
                    server.state.change(state_key)(callback)
                )

            pv_divider(vertical=True, classes="mr-1")
            pv_button(
                click=controller.reset_camera,
                icon="mdi-arrow-expand-all",
                tooltip="Reset Camera",
            )
            pv_divider(vertical=True, classes="mx-1")
            pv_button(
                click=controller.view_perspective,
                icon="mdi-axis-arrow",
                tooltip="Perspective view",
            )

            v3.VBtn(
                "Sagittal L/R",
                click=controller.view_sagittal,
                size="small",
                variant="text",
            )
            v3.VBtn(
                "Coronal A/P",
                click=controller.view_coronal,
                size="small",
                variant="text",
            )
            v3.VBtn(
                "Axial S/I",
                click=controller.view_axial,
                size="small",
                variant="text",
            )

            pv_divider(vertical=True, classes="mx-1")
            pv_checkbox(
                model=(self.OUTLINE, False),
                icons=("mdi-cube", "mdi-cube-off"),
                tooltip=(
                    "Toggle bounding box "
                    f"({{{{ {self.OUTLINE} ? 'on' : 'off' }}}})"
                ),
            )
            pv_checkbox(
                model=(self.GRID, False),
                icons=("mdi-ruler-square", "mdi-ruler-square"),
                tooltip=(
                    "Toggle ruler "
                    f"({{{{ {self.GRID} ? 'on' : 'off' }}}})"
                ),
            )

            if mode == "trame":
                pv_divider(vertical=True, classes="mx-1")
                pv_checkbox(
                    model=(
                        self.SERVER_RENDERING,
                        default_server_rendering,
                    ),
                    icons=("mdi-dns", "mdi-open-in-app"),
                    tooltip=(
                        "Toggle rendering mode "
                        f"({{{{ {self.SERVER_RENDERING} "
                        "? 'remote' : 'local' }}}})"
                    ),
                )

            def attach_export() -> Any:
                return server.protocol.addAttachment(self.export())

            pv_button(
                click=(
                    "utils.download('scene-export.html', "
                    f"trigger('{server.trigger_name(attach_export)}'), "
                    "'application/octet-stream')"
                ),
                icon="mdi-download",
                tooltip="Export scene as HTML",
            )

        return row

    viewer.ui_controls = MethodType(ui_controls, viewer)


def build_ui(
    server: Any,
    controller: TractFigureController,
) -> Any:
    ctrl = server.controller
    viewer = get_viewer(
        controller.renderer.plotter,
        server=server,
    )
    install_viewer_controls(viewer, controller)

    def attach_scene() -> Any:
        return server.protocol.addAttachment(
            memoryview(controller.download_scene())
        )

    def attach_png() -> Any:
        attachment = server.protocol.addAttachment(
            memoryview(controller.download_png())
        )
        return attachment

    scene_download_trigger = server.trigger_name(attach_scene)
    png_download_trigger = server.trigger_name(attach_png)

    scene_download_click = (
        "utils.download("
        "'tractfigure_scene_' + Date.now() + '.json', "
        f"trigger('{scene_download_trigger}'), "
        "'application/json')"
    )
    png_download_click = (
        "utils.download("
        "'tractfigure_render_' + Date.now() + '.png', "
        f"trigger('{png_download_trigger}'), "
        "'image/png')"
    )

    with SinglePageWithDrawerLayout(server) as layout:
        layout.title.set_text("TractFigure Studio")
        layout.drawer.width = 420

        with layout.toolbar:
            v3.VSpacer()
            v3.VBtn(
                "Reset all settings",
                prepend_icon="mdi-restore",
                click=ctrl.reset_all_settings,
                size="small",
            )
            v3.VBtn(
                "Save scene",
                prepend_icon="mdi-content-save",
                click=scene_download_click,
                loading=("trame__busy", False),
                disabled=("trame__busy", False),
                size="small",
            )
            v3.VBtn(
                "Export PNG",
                prepend_icon="mdi-image",
                click=png_download_click,
                loading=("trame__busy", False),
                disabled=("trame__busy", False),
                size="small",
            )

        with layout.drawer:
            with v3.VContainer(
                fluid=True,
                classes="pa-3",
            ):
                v3.VCardTitle("Reference image")

                v3.VSwitch(
                    label="Visible",
                    v_model=(
                        "reference_visible",
                        controller.scene.image.visible,
                    ),
                    color="#444444",
                    hide_details=True,
                    density="compact",
                )

                for slice_name in SLICE_VISIBILITY_FIELDS:
                    v3.VSwitch(
                        label=f"{slice_name.capitalize()} slice",
                        v_model=(
                            f"{slice_name}_visible",
                            getattr(
                                controller.scene.image,
                                SLICE_VISIBILITY_FIELDS[slice_name],
                            ),
                        ),
                        color="#616161",
                        hide_details=True,
                        density="compact",
                        disabled=("!reference_visible",),
                        classes="ml-4",
                    )

                numeric_slider(
                    label="Slice opacity",
                    model="slice_opacity",
                    value=controller.scene.image.opacity,
                    minimum=0.0,
                    maximum=1.0,
                    step=0.05,
                    input_model="slice_opacity_input",
                    commit=ctrl.commit_slice_opacity_input,
                )

                numeric_slider(
                    label="Sagittal",
                    model="sagittal_index",
                    value=controller.scene.image.sagittal_index,
                    minimum=0,
                    maximum=("sagittal_max", 0),
                    step=1,
                    input_model="sagittal_index_input",
                    commit=ctrl.commit_sagittal_index_input,
                )

                numeric_slider(
                    label="Coronal",
                    model="coronal_index",
                    value=controller.scene.image.coronal_index,
                    minimum=0,
                    maximum=("coronal_max", 0),
                    step=1,
                    input_model="coronal_index_input",
                    commit=ctrl.commit_coronal_index_input,
                )

                numeric_slider(
                    label="Axial",
                    model="axial_index",
                    value=controller.scene.image.axial_index,
                    minimum=0,
                    maximum=("axial_max", 0),
                    step=1,
                    input_model="axial_index_input",
                    commit=ctrl.commit_axial_index_input,
                )

                v3.VDivider(classes="my-3")
                v3.VCardTitle("Tract layers")

                v3.VSwitch(
                    label="All tracts",
                    v_model=(
                        "all_tracts_visible",
                        controller.state.all_tracts_visible,
                    ),
                    color="#202124",
                    hide_details=True,
                    density="compact",
                )

                for tract in controller.scene.tracts:
                    v3.VSwitch(
                        label=tract.name,
                        v_model=(
                            controller.visibility_keys[tract.id],
                            tract.visible,
                        ),
                        color=(
                            controller.color_keys[tract.id],
                            tract.color,
                        ),
                        hide_details=True,
                        density="compact",
                    )

                v3.VSelect(
                    label="Active tract",
                    v_model=(
                        "active_layer_id",
                        controller.scene.active_layer_id,
                    ),
                    items=(
                        "layer_items",
                        controller.state.layer_items,
                    ),
                    item_title="name",
                    item_value="id",
                    hide_details=True,
                    density="compact",
                    variant="outlined",
                    classes="mt-3",
                )

                v3.VDivider(classes="my-3")
                v3.VCardTitle("Active tract display")

                v3.VBtn(
                    "Reset active tract",
                    prepend_icon="mdi-restore",
                    click=ctrl.reset_active_tract_settings,
                    block=True,
                    classes="mb-3",
                )

                with v3.VSheet(
                    classes="mb-2",
                    style="min-height: 360px;",
                ):
                    v3.VColorPicker(
                        v_model=(
                            "active_color",
                            controller.state.active_color,
                        ),
                        mode="hexa",
                        hide_inputs=False,
                        show_swatches=False,
                        width=360,
                    )

                v3.VSelect(
                    label="Rendering mode",
                    v_model=(
                        "active_render_mode",
                        controller.state.active_render_mode,
                    ),
                    items=(
                        "render_mode_items",
                        ["tube", "line"],
                    ),
                    hide_details=True,
                    density="compact",
                    variant="outlined",
                    classes="mt-6",
                )

                numeric_slider(
                    label="Line width",
                    model="active_line_width",
                    value=controller.state.active_line_width,
                    minimum=0.5,
                    maximum=10.0,
                    step=0.5,
                    input_model="active_line_width_input",
                    commit=ctrl.commit_active_line_width_input,
                    v_if="active_render_mode === 'line'",
                )

                numeric_slider(
                    label="Tube radius (mm)",
                    model="active_tube_radius",
                    value=controller.state.active_tube_radius,
                    minimum=0.05,
                    maximum=2.0,
                    step=0.05,
                    input_model="active_tube_radius_input",
                    commit=ctrl.commit_active_tube_radius_input,
                    v_if="active_render_mode === 'tube'",
                )

                numeric_slider(
                    label="Tube sides",
                    model="active_tube_sides",
                    value=controller.state.active_tube_sides,
                    minimum=3,
                    maximum=24,
                    step=1,
                    input_model="active_tube_sides_input",
                    commit=ctrl.commit_active_tube_sides_input,
                    v_if="active_render_mode === 'tube'",
                )

                v3.VAlert(
                    type="warning",
                    text=(
                        "active_warnings_text",
                        "",
                    ),
                    v_if="active_warnings_visible",
                    classes="mt-3",
                )

                v3.VDivider(classes="my-3")
                v3.VCardTitle("Scene settings")

                with v3.VSheet(
                    classes="mb-2",
                    style="min-height: 360px;",
                ):
                    v3.VColorPicker(
                        v_model=(
                            "scene_background",
                            controller.scene.canvas.background,
                        ),
                        mode="hex",
                        hide_inputs=False,
                        show_swatches=False,
                        width=360,
                    )

                v3.VDivider(classes="my-3")

                v3.VTextField(
                    label="Status",
                    v_model=(
                        "status_message",
                        "",
                    ),
                    readonly=True,
                    hide_details=True,
                )

                v3.VTextarea(
                    label="Last saved output",
                    v_model=(
                        "export_path",
                        "",
                    ),
                    readonly=True,
                    rows=2,
                    hide_details=True,
                    classes="mt-2",
                )

        with layout.content:
            with v3.VContainer(
                fluid=True,
                classes="pa-0 fill-height",
            ):
                view = plotter_ui(
                    controller.renderer.plotter,
                    mode="trame",
                    default_server_rendering=True,
                    collapse_menu=False,
                    add_menu=True,
                    server=server,
                )

        layout.footer.hide()

    controller.set_view(view)
    ctrl.on_server_ready.add(controller.update_view)
    return layout


def configure_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the TractFigure Studio Trame viewer.",
    )

    parser.add_argument(
        "--reference",
        type=Path,
    )
    parser.add_argument(
        "--tractogram",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--recipe",
        type=Path,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
    )
    parser.add_argument(
        "--app-port",
        type=int,
        default=8080,
    )

    args, _unknown = parser.parse_known_args()
    return args


def scene_from_cli(args: Any) -> SceneState:
    if args.recipe is not None:
        if args.reference is not None or args.tractogram:
            raise ValueError(
                "--recipe cannot be combined with "
                "--reference or --tractogram"
            )

        return load_recipe(args.recipe)

    if args.reference is None:
        raise ValueError(
            "--reference is required when --recipe is absent"
        )

    if not args.tractogram:
        raise ValueError(
            "At least one --tractogram is required"
        )

    return scene_from_inputs(
        args.reference,
        args.tractogram,
    )


def main() -> None:
    pv.OFF_SCREEN = True

    args = configure_cli()
    server = get_server(
        "tractfigure-studio-v1",
        client_type="vue3",
    )

    if not 1 <= args.app_port <= 65535:
        raise ValueError("--app-port must be between 1 and 65535")

    scene = scene_from_cli(args)

    plotter = pv.Plotter(
        off_screen=True,
        window_size=(
            scene.canvas.width,
            scene.canvas.height,
        ),
    )

    renderer = SceneRenderer(plotter)
    renderer.load_scene(scene)

    controller = TractFigureController(
        server,
        renderer,
        args.output_dir.expanduser().resolve(),
    )
    build_ui(server, controller)

    server.start(
        port=args.app_port,
        open_browser=True,
        show_connection_info=True,
    )


if __name__ == "__main__":
    main()
