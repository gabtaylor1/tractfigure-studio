from __future__ import annotations

import argparse
import json
from datetime import datetime
from itertools import cycle
from pathlib import Path
from typing import Any
from uuid import uuid4

import pyvista as pv
from pyvista.trame.ui import plotter_ui
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
        self._state_sync_in_progress = False

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
            ("active_opacity", self._on_active_opacity),
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
        self.ctrl.save_scene = self.save_scene
        self.ctrl.export_png = self.export_png

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
            self.state.active_color = "#808080"
            self.state.active_opacity = 1.0
            self.state.active_render_mode = "tube"
            self.state.active_line_width = 2.0
            self.state.active_tube_radius = 0.35
            self.state.active_tube_sides = 8
            self.state.active_warnings_text = ""
            self.state.active_warnings_visible = False
            self.state.active_coordinate_report = ""
            return

        self.state.active_color = tract.color
        self.state.active_opacity = tract.opacity
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

        self.state.active_coordinate_report = json.dumps(
            tract.coordinate_report,
            indent=2,
            default=str,
        )

    def _synchronize_state_from_scene(self) -> None:
        self._state_sync_in_progress = True

        try:
            self.state.reference_visible = self.scene.image.visible
            self.state.slice_opacity = self.scene.image.opacity

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
        finally:
            self._state_sync_in_progress = False

    def set_view(self, view: Any) -> None:
        self.view = view
        self.ctrl.view_update = view.update
        self.ctrl.view_reset_camera = view.reset_camera

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

        opacity = float(slice_opacity)

        if abs(self.scene.image.opacity - opacity) < 1e-9:
            return

        self.renderer.set_image_opacity(opacity)
        self.update_view()

    def _on_slice_indices(
        self,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        indices = (
            int(self.state.sagittal_index),
            int(self.state.coronal_index),
            int(self.state.axial_index),
        )

        current = (
            self.scene.image.sagittal_index,
            self.scene.image.coronal_index,
            self.scene.image.axial_index,
        )

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

        if tract is None or tract.color == active_color:
            return

        try:
            self.renderer.set_tract_color(
                tract.id,
                active_color,
            )
        except ValueError as error:
            self.state.status_message = str(error)
            self.state.active_color = tract.color
            return

        setattr(
            self.state,
            self.color_keys[tract.id],
            tract.color,
        )
        self._refresh_layer_items()
        self.update_view()

    def _on_active_opacity(
        self,
        active_opacity: float,
        **_kwargs: Any,
    ) -> None:
        if self._state_sync_in_progress:
            return

        tract = self._active_tract()

        if tract is None:
            return

        opacity = float(active_opacity)

        if abs(tract.opacity - opacity) < 1e-9:
            return

        self.renderer.set_tract_opacity(
            tract.id,
            opacity,
        )
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

        width = float(active_line_width)

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

        radius = float(active_tube_radius)

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

        sides = int(active_tube_sides)

        if tract.tube_sides == sides:
            return

        self.renderer.set_tube_sides(
            tract.id,
            sides,
        )
        self.update_view()

    def reset_camera(self) -> None:
        self.renderer.reset_camera()
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
        restored = self.initial_scene.model_copy(deep=True)
        self.renderer.load_scene(restored)
        self.scene = self.renderer._require_scene()
        self._synchronize_state_from_scene()
        self.update_view()
        self._synchronize_camera_to_view()
        self.state.status_message = "All settings reset"

    def _timestamp(self) -> str:
        return datetime.now().strftime(
            "%Y%m%d_%H%M%S_%f"
        )

    def save_scene(self) -> None:
        output_path = (
            self.output_directory
            / f"tractfigure_scene_{self._timestamp()}.json"
        )

        saved_path = self.renderer.save_scene(output_path)
        self.state.status_message = "Scene recipe saved"
        self.state.export_path = str(saved_path)

    def export_png(self) -> None:
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

        self.state.status_message = "PNG exported"
        self.state.export_path = str(saved_path)


def build_ui(
    server: Any,
    controller: TractFigureController,
) -> Any:
    ctrl = server.controller

    with SinglePageWithDrawerLayout(server) as layout:
        layout.title.set_text("TractFigure Studio")
        layout.drawer.width = 420

        with layout.toolbar:
            v3.VSpacer()
            v3.VBtn(
                "Reset camera",
                prepend_icon="mdi-camera-retake",
                click=ctrl.reset_camera,
            )
            v3.VBtn(
                "Reset all settings",
                prepend_icon="mdi-restore",
                click=ctrl.reset_all_settings,
            )
            v3.VBtn(
                "Save scene",
                prepend_icon="mdi-content-save",
                click=ctrl.save_scene,
            )
            v3.VBtn(
                "Export PNG",
                prepend_icon="mdi-image",
                click=ctrl.export_png,
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

                v3.VSlider(
                    label="Slice opacity",
                    v_model=(
                        "slice_opacity",
                        controller.scene.image.opacity,
                    ),
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    thumb_label=True,
                    hide_details=True,
                )

                v3.VSlider(
                    label="Sagittal",
                    v_model=(
                        "sagittal_index",
                        controller.scene.image.sagittal_index,
                    ),
                    min=0,
                    max=("sagittal_max", 0),
                    step=1,
                    thumb_label=True,
                    hide_details=True,
                )

                v3.VSlider(
                    label="Coronal",
                    v_model=(
                        "coronal_index",
                        controller.scene.image.coronal_index,
                    ),
                    min=0,
                    max=("coronal_max", 0),
                    step=1,
                    thumb_label=True,
                    hide_details=True,
                )

                v3.VSlider(
                    label="Axial",
                    v_model=(
                        "axial_index",
                        controller.scene.image.axial_index,
                    ),
                    min=0,
                    max=("axial_max", 0),
                    step=1,
                    thumb_label=True,
                    hide_details=True,
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

                v3.VColorPicker(
                    v_model=(
                        "active_color",
                        controller.state.active_color,
                    ),
                    hide_inputs=True,
                    show_swatches=False,
                    width=360,
                )

                v3.VSlider(
                    label="Opacity",
                    v_model=(
                        "active_opacity",
                        controller.state.active_opacity,
                    ),
                    min=0.0,
                    max=1.0,
                    step=0.05,
                    thumb_label=True,
                    hide_details=True,
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
                )

                v3.VSlider(
                    label="Line width",
                    v_model=(
                        "active_line_width",
                        controller.state.active_line_width,
                    ),
                    min=0.5,
                    max=10.0,
                    step=0.5,
                    thumb_label=True,
                    hide_details=True,
                    v_if="active_render_mode === 'line'",
                )

                v3.VSlider(
                    label="Tube radius (mm)",
                    v_model=(
                        "active_tube_radius",
                        controller.state.active_tube_radius,
                    ),
                    min=0.05,
                    max=2.0,
                    step=0.05,
                    thumb_label=True,
                    hide_details=True,
                    v_if="active_render_mode === 'tube'",
                )

                v3.VSlider(
                    label="Tube sides",
                    v_model=(
                        "active_tube_sides",
                        controller.state.active_tube_sides,
                    ),
                    min=3,
                    max=24,
                    step=1,
                    thumb_label=True,
                    hide_details=True,
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

                v3.VTextarea(
                    label="Coordinate inspection",
                    v_model=(
                        "active_coordinate_report",
                        "",
                    ),
                    readonly=True,
                    rows=8,
                    variant="outlined",
                    classes="mt-3",
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
