"""Standalone v5 viewer with affine-exact NIfTI slice geometry.

This module retains automatic tract coordinate detection, tube/line rendering,
color-coded visibility controls, the white background, opaque image slices, and
the legend-free viewport from the previous viewer version.
"""

import argparse
from collections.abc import Sequence
from functools import partial
from itertools import cycle
from pathlib import Path

import nibabel as nib
import numpy as np
import pyvista as pv

from tractfigure.io import TractLayer, load_tract_layer
from tractfigure.vtk_conversion import (
    nifti_to_orthogonal_slices,
    streamlines_to_polydata,
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

WINDOW_SIZE = (1400, 1000)
CHECKBOX_SIZE = 22
CHECKBOX_ROW_HEIGHT = 30
CHECKBOX_COLUMN_WIDTH = 300
CHECKBOX_MARGIN = 18
CHECKBOX_LABEL_MAX_CHARACTERS = 36


class TractVisibilityController:
    """Keep global and per-tract actor visibility controls synchronized."""

    def __init__(self, plotter: pv.Plotter) -> None:
        self.plotter = plotter
        self.actors: dict[str, pv.Actor] = {}
        self.layer_widgets: dict[str, object] = {}
        self.global_widget: object | None = None

    def add_actor(self, name: str, actor: pv.Actor) -> None:
        self.actors[name] = actor

    def set_global_widget(self, widget: object) -> None:
        self.global_widget = widget

    def set_layer_widget(self, name: str, widget: object) -> None:
        self.layer_widgets[name] = widget

    @staticmethod
    def _set_widget_state(widget: object | None, state: bool) -> None:
        if widget is None:
            return
        representation = widget.GetRepresentation()
        representation.SetState(int(state))

    def _finish_update(self) -> None:
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

    def set_all_visible(self, state: bool) -> None:
        state = bool(state)
        for actor in self.actors.values():
            actor.visibility = state
        for widget in self.layer_widgets.values():
            self._set_widget_state(widget, state)
        self._set_widget_state(self.global_widget, state)
        self._finish_update()

    def set_layer_visible(self, name: str, state: bool) -> None:
        self.actors[name].visibility = bool(state)
        all_visible = all(bool(actor.visibility) for actor in self.actors.values())
        self._set_widget_state(self.global_widget, all_visible)
        self._finish_update()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("tractograms", nargs="+", type=Path)
    parser.add_argument("--max-streamlines", type=int, default=5000)
    parser.add_argument("--render-mode", choices=("tube", "line"), default="tube")
    parser.add_argument("--tube-radius", type=float, default=0.35)
    parser.add_argument("--tube-sides", type=int, default=8)
    parser.add_argument("--line-width", type=float, default=2.0)
    parser.add_argument("--tract-opacity", type=float, default=1.0)
    parser.add_argument("--slice-opacity", type=float, default=1.0)
    parser.add_argument("--min-reference-overlap", type=float, default=0.80)
    return parser


def unique_layer_names(paths: Sequence[Path]) -> list[str]:
    names = []
    occurrences: dict[str, int] = {}

    for path in paths:
        base = path.stem
        occurrences[base] = occurrences.get(base, 0) + 1
        count = occurrences[base]
        names.append(base if count == 1 else f"{base} ({count})")

    return names


def _short_visibility_label(name: str) -> str:
    if len(name) <= CHECKBOX_LABEL_MAX_CHARACTERS:
        return name
    return f"{name[: CHECKBOX_LABEL_MAX_CHARACTERS - 1]}…"


def _visibility_item_position(
    item_index: int,
    item_count: int,
    rows_per_column: int,
) -> tuple[int, int]:
    column = item_index // rows_per_column
    row = item_index % rows_per_column
    column_start = column * rows_per_column
    items_in_column = min(rows_per_column, item_count - column_start)

    x_position = CHECKBOX_MARGIN + column * CHECKBOX_COLUMN_WIDTH
    y_position = CHECKBOX_MARGIN + (items_in_column - row - 1) * CHECKBOX_ROW_HEIGHT
    return x_position, y_position


def add_visibility_controls(
    plotter: pv.Plotter,
    controller: TractVisibilityController,
    colors_by_name: dict[str, str],
) -> None:
    controls = [
        (
            "All tracts",
            controller.set_all_visible,
            "#202124",
            None,
        )
    ]
    controls.extend(
        (
            name,
            partial(controller.set_layer_visible, name),
            colors_by_name[name],
            name,
        )
        for name in controller.actors
    )

    window_height = int(plotter.window_size[1])
    rows_per_column = max(
        1,
        (window_height - 2 * CHECKBOX_MARGIN - CHECKBOX_SIZE)
        // CHECKBOX_ROW_HEIGHT
        + 1,
    )

    for item_index, (label, callback, color, layer_name) in enumerate(controls):
        position = _visibility_item_position(
            item_index,
            len(controls),
            rows_per_column,
        )
        widget = plotter.add_checkbox_button_widget(
            callback,
            value=True,
            position=position,
            size=CHECKBOX_SIZE,
            border_size=2,
            color_on=color,
            color_off="#B7BCC5",
            background_color="#FFFFFF",
        )

        if layer_name is None:
            controller.set_global_widget(widget)
            text_name = "visibility_label_all"
        else:
            controller.set_layer_widget(layer_name, widget)
            text_name = f"visibility_label_{item_index}"

        plotter.add_text(
            _short_visibility_label(label),
            position=(position[0] + CHECKBOX_SIZE + 8, position[1] + 2),
            font_size=10,
            color="#202124",
            shadow=False,
            name=text_name,
        )


def install_camera_clipping_updates(plotter: pv.Plotter) -> tuple[int, ...]:
    """Reset near and far clipping planes throughout camera interaction."""

    def reset_clipping_range(*_args: object) -> None:
        plotter.renderer.ResetCameraClippingRange()

    events = (
        "InteractionEvent",
        "EndInteractionEvent",
        "MouseWheelForwardEvent",
        "MouseWheelBackwardEvent",
    )
    return tuple(
        plotter.iren.add_observer(event, reset_clipping_range)
        for event in events
    )


def build_tract_geometry(
    polydata: pv.PolyData,
    render_mode: str,
    tube_radius: float,
    tube_sides: int,
) -> pv.PolyData:
    if render_mode == "line":
        return polydata

    return polydata.tube(
        radius=tube_radius,
        n_sides=tube_sides,
        capping=False,
    )


def print_inspection(layer: TractLayer) -> None:
    print(layer.inspection.format_report())
    print()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.max_streamlines < 1:
        parser.error("--max-streamlines must be positive")
    if args.tube_radius <= 0:
        parser.error("--tube-radius must be positive")
    if args.tube_sides < 3:
        parser.error("--tube-sides must be at least 3")
    if args.line_width <= 0:
        parser.error("--line-width must be positive")
    if not 0.0 <= args.tract_opacity <= 1.0:
        parser.error("--tract-opacity must be between 0 and 1")
    if not 0.0 <= args.slice_opacity <= 1.0:
        parser.error("--slice-opacity must be between 0 and 1")
    if not 0.0 <= args.min_reference_overlap <= 1.0:
        parser.error("--min-reference-overlap must be between 0 and 1")

    image = nib.load(args.reference)
    canonical_image = nib.as_closest_canonical(image)
    image_slices = nifti_to_orthogonal_slices(canonical_image)

    plotter = pv.Plotter(window_size=WINDOW_SIZE)
    plotter.set_background("#FFFFFF")
    plotter.enable_anti_aliasing("ssaa")

    image_data = np.asarray(canonical_image.dataobj, dtype=np.float32)
    valid = image_data[np.isfinite(image_data)]

    if valid.size:
        lower, upper = np.percentile(valid, [2, 98])
    else:
        lower, upper = 0.0, 1.0

    for image_slice in image_slices.values():
        plotter.add_mesh(
            image_slice,
            scalars="intensity",
            cmap="gray",
            clim=(float(lower), float(upper)),
            opacity=args.slice_opacity,
            show_scalar_bar=False,
        )

    colors = cycle(DEFAULT_COLORS)
    layer_names = unique_layer_names(args.tractograms)
    controller = TractVisibilityController(plotter)
    colors_by_name: dict[str, str] = {}

    for tractogram_path, name, color in zip(
        args.tractograms,
        layer_names,
        colors,
        strict=False,
    ):
        layer = load_tract_layer(
            tractogram_path,
            reference_path=args.reference,
            name=name,
            min_reference_overlap=args.min_reference_overlap,
        )
        print_inspection(layer)

        polydata = streamlines_to_polydata(
            layer.streamlines,
            max_streamlines=args.max_streamlines,
        )
        geometry = build_tract_geometry(
            polydata,
            args.render_mode,
            args.tube_radius,
            args.tube_sides,
        )

        actor = plotter.add_mesh(
            geometry,
            color=color,
            opacity=args.tract_opacity,
            line_width=args.line_width,
            render_lines_as_tubes=False,
            smooth_shading=args.render_mode == "tube",
            specular=0.15 if args.render_mode == "tube" else 0.0,
            specular_power=15.0,
            force_opaque=args.tract_opacity >= 1.0,
            label=name,
        )
        controller.add_actor(name, actor)
        colors_by_name[name] = color

    add_visibility_controls(plotter, controller, colors_by_name)
    plotter.add_axes(
        color="#202124",
        viewport=(0.88, 0.0, 1.0, 0.12),
    )
    plotter.view_isometric()
    plotter.reset_camera()
    plotter.reset_camera_clipping_range()
    install_camera_clipping_updates(plotter)
    plotter.show()


if __name__ == "__main__":
    main()
