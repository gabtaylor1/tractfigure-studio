from __future__ import annotations

import io
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
import pyvista as pv
from PIL import Image, ImageOps

from tractfigure.io import load_tract_layer
from tractfigure.scene_state_v1_20260730 import (
    CameraState,
    ImageLayerState,
    SceneState,
    TractLayerState,
)
from tractfigure.vtk_conversion import (
    nifti_to_orthogonal_slices,
    streamlines_to_polydata,
)

LayerLoader = Callable[..., Any]

SLICE_VISIBILITY_FIELDS = {
    "sagittal": "sagittal_visible",
    "coronal": "coronal_visible",
    "axial": "axial_visible",
}

ANATOMICAL_VIEW_CONFIG = {
    ("sagittal", "left"): ("view_yz", True),
    ("sagittal", "right"): ("view_yz", False),
    ("coronal", "anterior"): ("view_xz", True),
    ("coronal", "posterior"): ("view_xz", False),
    ("axial", "superior"): ("view_xy", False),
    ("axial", "inferior"): ("view_xy", True),
}


def _safe_actor_name(prefix: str, identifier: str) -> str:
    safe_identifier = re.sub(r"[^A-Za-z0-9_]", "_", identifier)
    return f"{prefix}_{safe_identifier}"


def _inspection_to_dict(inspection: object) -> dict[str, Any]:
    if is_dataclass(inspection):
        return asdict(inspection)

    report: dict[str, Any] = {}

    if hasattr(inspection, "format_report"):
        report["formatted_report"] = inspection.format_report()

    return report


def _portable_output_path(path: Path, recipe_directory: Path) -> str:
    """Serialize a scene path portably, relative to the saved recipe when possible."""

    path = path.expanduser().resolve()
    recipe_directory = recipe_directory.expanduser().resolve()

    try:
        return Path(os.path.relpath(path, recipe_directory)).as_posix()
    except ValueError:
        # Windows cannot form a relative path across drive letters. Retain an
        # explicit POSIX-style absolute path so the saved scene remains usable
        # on the originating computer and the limitation is visible in JSON.
        return path.as_posix()


class SceneRenderer:
    def __init__(
        self,
        plotter: pv.Plotter | None = None,
        *,
        layer_loader: LayerLoader = load_tract_layer,
    ) -> None:
        self.plotter = plotter or pv.Plotter(
            off_screen=True,
            window_size=(1400, 1000),
        )
        self.layer_loader = layer_loader

        self.scene: SceneState | None = None
        self.reference_image: nib.spatialimages.SpatialImage | None = None
        self.image_shape: tuple[int, int, int] | None = None

        self.layers_by_id: dict[str, object] = {}
        self.line_meshes_by_id: dict[str, pv.PolyData] = {}
        self.tube_meshes_by_key: dict[
            tuple[str, float, int],
            pv.PolyData,
        ] = {}
        self.actors_by_id: dict[str, pv.Actor] = {}
        self.image_actors: dict[str, pv.Actor] = {}

    def _require_scene(self) -> SceneState:
        if self.scene is None:
            raise RuntimeError("No scene has been loaded")
        return self.scene

    def _refresh(self) -> None:
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

    def clear(self) -> None:
        self.plotter.clear()

        self.reference_image = None
        self.image_shape = None

        self.layers_by_id.clear()
        self.line_meshes_by_id.clear()
        self.tube_meshes_by_key.clear()
        self.actors_by_id.clear()
        self.image_actors.clear()

    def load_scene(self, scene: SceneState) -> SceneState:
        self.clear()
        self.scene = scene.model_copy(deep=True)

        active_scene = self._require_scene()

        self.plotter.window_size = (
            active_scene.canvas.width,
            active_scene.canvas.height,
        )
        self.plotter.set_background(active_scene.canvas.background)
        self.plotter.enable_anti_aliasing("ssaa")

        self.load_reference(active_scene.image)

        for tract_state in active_scene.tracts:
            self.add_tract(tract_state)

        self.plotter.add_axes(
            color="#202124",
            viewport=(0.88, 0.0, 1.0, 0.12),
        )

        if active_scene.camera is None:
            self.plotter.view_isometric()
            self.plotter.reset_camera()
            active_scene.camera = self.capture_camera()
        else:
            self.apply_camera(active_scene.camera, refresh=False)

        self._refresh()
        return active_scene

    def _actual_slice_indices(
        self,
        image_state: ImageLayerState,
        shape: tuple[int, int, int],
    ) -> tuple[int, int, int]:
        supplied = (
            image_state.sagittal_index,
            image_state.coronal_index,
            image_state.axial_index,
        )

        indices = tuple(
            size // 2 if value is None else int(value)
            for value, size in zip(supplied, shape, strict=True)
        )

        for axis, (index, size) in enumerate(zip(indices, shape, strict=True)):
            if not 0 <= index < size:
                raise ValueError(f"Slice index {index} is outside axis {axis} with size {size}")

        return indices

    def _remove_image_actors(self) -> None:
        for actor in tuple(self.image_actors.values()):
            self.plotter.remove_actor(
                actor,
                reset_camera=False,
                render=False,
            )

        self.image_actors.clear()

    def _slice_actor_visible(
        self,
        image_state: ImageLayerState,
        slice_name: str,
    ) -> bool:
        try:
            visibility_field = SLICE_VISIBILITY_FIELDS[slice_name]
        except KeyError as error:
            raise ValueError(f"Unknown anatomical slice: {slice_name}") from error

        return bool(image_state.visible and getattr(image_state, visibility_field))

    def load_reference(self, image_state: ImageLayerState) -> None:
        self._remove_image_actors()

        image_path = Path(image_state.path).expanduser().resolve()
        image = nib.as_closest_canonical(nib.load(str(image_path)))
        data = np.asarray(image.dataobj, dtype=np.float32)

        if data.ndim != 3:
            raise ValueError(f"Expected a 3D reference image; received {data.shape}")

        shape = tuple(int(value) for value in data.shape)
        indices = self._actual_slice_indices(image_state, shape)

        image_state.path = image_path
        image_state.sagittal_index = indices[0]
        image_state.coronal_index = indices[1]
        image_state.axial_index = indices[2]

        self.reference_image = image
        self.image_shape = shape

        valid = data[np.isfinite(data)]

        if valid.size:
            lower, upper = np.percentile(valid, [2, 98])
        else:
            lower, upper = 0.0, 1.0

        if np.isclose(lower, upper):
            upper = lower + 1.0

        slice_grids = nifti_to_orthogonal_slices(
            image,
            indices=indices,
        )

        missing_slices = set(SLICE_VISIBILITY_FIELDS) - set(slice_grids)

        if missing_slices:
            missing_text = ", ".join(sorted(missing_slices))
            raise RuntimeError(f"Anatomical slice conversion omitted: {missing_text}")

        for slice_name, grid in slice_grids.items():
            actor = self.plotter.add_mesh(
                grid,
                scalars="intensity",
                cmap="gray",
                clim=(float(lower), float(upper)),
                opacity=image_state.opacity,
                show_scalar_bar=False,
                name=f"reference_{slice_name}",
                reset_camera=False,
            )
            actor.SetVisibility(
                self._slice_actor_visible(
                    image_state,
                    slice_name,
                )
            )
            self.image_actors[slice_name] = actor

    def _tube_geometry(
        self,
        tract_state: TractLayerState,
    ) -> pv.PolyData:
        key = (
            tract_state.id,
            float(tract_state.tube_radius),
            int(tract_state.tube_sides),
        )

        if key not in self.tube_meshes_by_key:
            line_mesh = self.line_meshes_by_id[tract_state.id]
            self.tube_meshes_by_key[key] = line_mesh.tube(
                radius=tract_state.tube_radius,
                n_sides=tract_state.tube_sides,
                capping=False,
            )

        return self.tube_meshes_by_key[key]

    def _geometry_for_state(
        self,
        tract_state: TractLayerState,
    ) -> pv.PolyData:
        if tract_state.render_mode == "line":
            return self.line_meshes_by_id[tract_state.id]

        return self._tube_geometry(tract_state)

    def _add_actor(
        self,
        tract_state: TractLayerState,
    ) -> pv.Actor:
        geometry = self._geometry_for_state(tract_state)

        actor = self.plotter.add_mesh(
            geometry,
            color=tract_state.color,
            opacity=tract_state.opacity,
            line_width=tract_state.line_width,
            render_lines_as_tubes=False,
            smooth_shading=tract_state.render_mode == "tube",
            specular=0.15 if tract_state.render_mode == "tube" else 0.0,
            specular_power=15.0,
            name=_safe_actor_name("tract", tract_state.id),
            reset_camera=False,
        )
        actor.SetVisibility(bool(tract_state.visible))

        self.actors_by_id[tract_state.id] = actor
        return actor

    def add_tract(self, tract_state: TractLayerState) -> None:
        scene = self._require_scene()

        if tract_state.id in self.actors_by_id:
            raise ValueError(f"Tract layer ID is already loaded: {tract_state.id}")

        tract_state.path = Path(tract_state.path).expanduser().resolve()

        layer = self.layer_loader(
            tract_state.path,
            reference_path=scene.image.path,
            name=tract_state.name,
        )

        tract_state.coordinate_report = _inspection_to_dict(layer.inspection)

        line_mesh = streamlines_to_polydata(
            layer.streamlines,
            max_streamlines=tract_state.max_streamlines,
        )
        line_mesh.verts = np.empty(0, dtype=np.int64)

        self.layers_by_id[tract_state.id] = layer
        self.line_meshes_by_id[tract_state.id] = line_mesh
        self._add_actor(tract_state)

    def remove_tract(self, layer_id: str) -> None:
        scene = self._require_scene()
        scene.tract_by_id(layer_id)

        actor = self.actors_by_id.pop(layer_id)
        self.plotter.remove_actor(
            actor,
            reset_camera=False,
            render=False,
        )

        self.layers_by_id.pop(layer_id, None)
        self.line_meshes_by_id.pop(layer_id, None)

        keys_to_remove = [key for key in self.tube_meshes_by_key if key[0] == layer_id]

        for key in keys_to_remove:
            self.tube_meshes_by_key.pop(key, None)

        scene.tracts = [tract for tract in scene.tracts if tract.id != layer_id]

        if scene.active_layer_id == layer_id:
            scene.active_layer_id = scene.tracts[0].id if scene.tracts else None

        self._refresh()

    def _replace_tract_actor(
        self,
        tract_state: TractLayerState,
    ) -> None:
        old_actor = self.actors_by_id.pop(tract_state.id)

        self.plotter.remove_actor(
            old_actor,
            reset_camera=False,
            render=False,
        )
        self._add_actor(tract_state)

    def set_all_tracts_visible(self, visible: bool) -> None:
        scene = self._require_scene()
        visible = bool(visible)

        for tract_state in scene.tracts:
            tract_state.visible = visible
            self.actors_by_id[tract_state.id].SetVisibility(visible)

        self._refresh()

    def set_tract_visible(
        self,
        layer_id: str,
        visible: bool,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        tract_state.visible = bool(visible)
        self.actors_by_id[layer_id].SetVisibility(bool(visible))
        self._refresh()

    def set_tract_color(
        self,
        layer_id: str,
        color: str,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        tract_state.color = color
        rgb = pv.Color(tract_state.color).float_rgb

        self.actors_by_id[layer_id].GetProperty().SetColor(*rgb)
        self._refresh()

    def set_tract_opacity(
        self,
        layer_id: str,
        opacity: float,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        tract_state.opacity = opacity
        self.actors_by_id[layer_id].GetProperty().SetOpacity(tract_state.opacity)
        self._refresh()

    def set_tract_appearance(
        self,
        layer_id: str,
        color: str,
        opacity: float,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        tract_state.color = color
        tract_state.opacity = opacity

        actor_property = self.actors_by_id[layer_id].GetProperty()
        actor_property.SetColor(*pv.Color(tract_state.color).float_rgb)
        actor_property.SetOpacity(tract_state.opacity)
        self._refresh()

    def set_render_mode(
        self,
        layer_id: str,
        mode: str,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        if tract_state.render_mode == mode:
            return

        tract_state.render_mode = mode
        self._replace_tract_actor(tract_state)
        self._refresh()

    def set_line_width(
        self,
        layer_id: str,
        width: float,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        tract_state.line_width = width
        self.actors_by_id[layer_id].GetProperty().SetLineWidth(tract_state.line_width)
        self._refresh()

    def set_tube_radius(
        self,
        layer_id: str,
        radius: float,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        if np.isclose(tract_state.tube_radius, radius):
            return

        tract_state.tube_radius = radius

        if tract_state.render_mode == "tube":
            self._replace_tract_actor(tract_state)
            self._refresh()

    def set_tube_sides(
        self,
        layer_id: str,
        sides: int,
    ) -> None:
        scene = self._require_scene()
        tract_state = scene.tract_by_id(layer_id)

        if tract_state.tube_sides == sides:
            return

        tract_state.tube_sides = sides

        if tract_state.render_mode == "tube":
            self._replace_tract_actor(tract_state)
            self._refresh()

    def set_image_visible(self, visible: bool) -> None:
        scene = self._require_scene()
        scene.image.visible = bool(visible)

        for slice_name, actor in self.image_actors.items():
            actor.SetVisibility(
                self._slice_actor_visible(
                    scene.image,
                    slice_name,
                )
            )

        self._refresh()

    def set_slice_visible(
        self,
        slice_name: str,
        visible: bool,
    ) -> None:
        scene = self._require_scene()

        try:
            visibility_field = SLICE_VISIBILITY_FIELDS[slice_name]
        except KeyError as error:
            valid = ", ".join(SLICE_VISIBILITY_FIELDS)
            raise ValueError(
                f"Unknown anatomical slice {slice_name!r}; expected one of: {valid}"
            ) from error

        setattr(
            scene.image,
            visibility_field,
            bool(visible),
        )

        try:
            actor = self.image_actors[slice_name]
        except KeyError as error:
            raise RuntimeError(f"Anatomical slice actor is unavailable: {slice_name}") from error

        actor.SetVisibility(
            self._slice_actor_visible(
                scene.image,
                slice_name,
            )
        )
        self._refresh()

    def set_image_opacity(self, opacity: float) -> None:
        scene = self._require_scene()
        scene.image.opacity = opacity

        for actor in self.image_actors.values():
            actor.GetProperty().SetOpacity(scene.image.opacity)

        self._refresh()

    def set_slice_indices(
        self,
        sagittal: int,
        coronal: int,
        axial: int,
    ) -> None:
        scene = self._require_scene()

        scene.image.sagittal_index = int(sagittal)
        scene.image.coronal_index = int(coronal)
        scene.image.axial_index = int(axial)

        self.load_reference(scene.image)
        self._refresh()

    def capture_camera(self) -> CameraState:
        camera = self.plotter.camera

        return CameraState(
            position=tuple(float(value) for value in camera.GetPosition()),
            focal_point=tuple(float(value) for value in camera.GetFocalPoint()),
            view_up=tuple(float(value) for value in camera.GetViewUp()),
            parallel_projection=bool(camera.GetParallelProjection()),
            parallel_scale=float(camera.GetParallelScale()),
            clipping_range=tuple(float(value) for value in camera.GetClippingRange()),
        )

    def apply_camera(
        self,
        camera_state: CameraState,
        *,
        refresh: bool = True,
    ) -> None:
        camera = self.plotter.camera

        camera.SetPosition(*camera_state.position)
        camera.SetFocalPoint(*camera_state.focal_point)
        camera.SetViewUp(*camera_state.view_up)
        camera.SetParallelProjection(int(camera_state.parallel_projection))
        camera.SetParallelScale(camera_state.parallel_scale)
        camera.SetClippingRange(*camera_state.clipping_range)

        if refresh:
            self.plotter.render()

    def set_anatomical_view(
        self,
        plane: str,
        side: str,
    ) -> CameraState:
        scene = self._require_scene()

        try:
            view_method_name, negative = ANATOMICAL_VIEW_CONFIG[(plane, side)]
        except KeyError as error:
            valid = ", ".join(
                f"{view_plane}:{view_side}" for view_plane, view_side in ANATOMICAL_VIEW_CONFIG
            )
            raise ValueError(
                f"Unknown anatomical view {plane}:{side}. Valid views: {valid}"
            ) from error

        self.plotter.camera.SetParallelProjection(1)
        view_method = getattr(self.plotter, view_method_name)
        view_method(
            negative=negative,
            render=False,
        )
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

        scene.camera = self.capture_camera()
        return scene.camera

    def set_perspective_view(self) -> CameraState:
        scene = self._require_scene()

        self.plotter.camera.SetParallelProjection(0)
        self.plotter.view_isometric(render=False)
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

        scene.camera = self.capture_camera()
        return scene.camera

    def set_background(self, color: str) -> str:
        scene = self._require_scene()
        scene.canvas.background = color

        normalized = scene.canvas.background
        self.plotter.set_background(normalized)
        self.plotter.render()
        return normalized

    def restore_scene_settings(
        self,
        initial_scene: SceneState,
    ) -> SceneState:
        scene = self._require_scene()

        current_ids = [tract.id for tract in scene.tracts]
        initial_ids = [tract.id for tract in initial_scene.tracts]

        if current_ids != initial_ids:
            raise ValueError("Cannot restore settings after tract layers changed")

        current_reference = Path(scene.image.path).expanduser().resolve()
        initial_reference = Path(initial_scene.image.path).expanduser().resolve()

        if current_reference != initial_reference:
            raise ValueError("Cannot restore settings after reference image changed")

        scene.canvas = initial_scene.canvas.model_copy(deep=True)
        self.plotter.window_size = (
            scene.canvas.width,
            scene.canvas.height,
        )
        self.plotter.set_background(scene.canvas.background)

        initial_image = initial_scene.image
        indices_changed = (
            scene.image.sagittal_index,
            scene.image.coronal_index,
            scene.image.axial_index,
        ) != (
            initial_image.sagittal_index,
            initial_image.coronal_index,
            initial_image.axial_index,
        )

        scene.image.visible = initial_image.visible
        scene.image.opacity = initial_image.opacity
        scene.image.sagittal_visible = initial_image.sagittal_visible
        scene.image.coronal_visible = initial_image.coronal_visible
        scene.image.axial_visible = initial_image.axial_visible
        scene.image.sagittal_index = initial_image.sagittal_index
        scene.image.coronal_index = initial_image.coronal_index
        scene.image.axial_index = initial_image.axial_index

        if indices_changed:
            self.load_reference(scene.image)
        else:
            for slice_name, actor in self.image_actors.items():
                actor.SetVisibility(
                    self._slice_actor_visible(
                        scene.image,
                        slice_name,
                    )
                )
                actor.GetProperty().SetOpacity(scene.image.opacity)

        for initial_tract in initial_scene.tracts:
            tract = scene.tract_by_id(initial_tract.id)
            geometry_changed = tract.render_mode != initial_tract.render_mode or (
                initial_tract.render_mode == "tube"
                and (
                    not np.isclose(
                        tract.tube_radius,
                        initial_tract.tube_radius,
                    )
                    or tract.tube_sides != initial_tract.tube_sides
                )
            )

            tract.visible = initial_tract.visible
            tract.color = initial_tract.color
            tract.opacity = initial_tract.opacity
            tract.render_mode = initial_tract.render_mode
            tract.line_width = initial_tract.line_width
            tract.tube_radius = initial_tract.tube_radius
            tract.tube_sides = initial_tract.tube_sides

            if geometry_changed:
                self._replace_tract_actor(tract)
                continue

            actor = self.actors_by_id[tract.id]
            actor.SetVisibility(tract.visible)
            actor_property = actor.GetProperty()
            actor_property.SetColor(*pv.Color(tract.color).float_rgb)
            actor_property.SetOpacity(tract.opacity)
            actor_property.SetLineWidth(tract.line_width)

        scene.active_layer_id = initial_scene.active_layer_id

        if initial_scene.camera is None:
            self.plotter.reset_camera()
            scene.camera = self.capture_camera()
        else:
            scene.camera = initial_scene.camera.model_copy(deep=True)
            self.apply_camera(scene.camera, refresh=False)

        self._refresh()
        return scene

    def reset_camera(self) -> CameraState:
        scene = self._require_scene()

        self.plotter.camera.SetParallelProjection(0)
        self.plotter.view_isometric(render=False)
        self.plotter.reset_camera(render=False)
        self.plotter.reset_camera_clipping_range()
        self.plotter.render()

        scene.camera = self.capture_camera()
        return scene.camera

    def _orientation_axes_widgets(
        self,
    ) -> tuple[tuple[Any, bool], ...]:
        widgets: list[tuple[Any, bool]] = []

        for renderer in self.plotter.renderers:
            widget = renderer.axes_widget

            if widget is not None:
                widgets.append((widget, bool(widget.GetEnabled())))

        return tuple(widgets)

    def _capture_png(
        self,
        destination: str | Path | io.BytesIO,
        width: int,
        height: int,
    ) -> np.ndarray:
        if self.plotter.render_window is None:
            raise RuntimeError("The render window is unavailable")

        axes_widgets = self._orientation_axes_widgets()

        try:
            for widget, enabled in axes_widgets:
                if enabled:
                    widget.EnabledOff()

            self.plotter.render()

            image = self.plotter.screenshot(
                filename=None,
                return_img=True,
            )

            if image is None:
                raise RuntimeError("PyVista did not return a screenshot")

            output_image = Image.fromarray(np.asarray(image))

            if output_image.size != (int(width), int(height)):
                background = pv.Color(self._require_scene().canvas.background).int_rgb
                fill_color: tuple[int, ...]

                if output_image.mode == "RGBA":
                    fill_color = (*background, 255)
                else:
                    fill_color = background

                output_image = ImageOps.pad(
                    output_image,
                    (int(width), int(height)),
                    method=Image.Resampling.LANCZOS,
                    color=fill_color,
                    centering=(0.5, 0.5),
                )

            if isinstance(destination, io.BytesIO):
                destination.seek(0)
                destination.truncate(0)
                output_image.save(destination, format="PNG")
            else:
                output_image.save(destination)

            return np.asarray(output_image)
        finally:
            for widget, enabled in axes_widgets:
                if enabled:
                    widget.EnabledOn()

            self.plotter.render()

    def screenshot_png(
        self,
        width: int,
        height: int,
    ) -> bytes:
        buffer = io.BytesIO()
        self._capture_png(buffer, width, height)
        return buffer.getvalue()

    def save_scene(self, output_path: str | Path) -> Path:
        scene = self._require_scene()
        output_path = Path(output_path).expanduser().resolve()

        scene.camera = self.capture_camera()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = scene.model_dump(mode="json")
        payload["image"]["path"] = _portable_output_path(
            scene.image.path,
            output_path.parent,
        )

        for tract_payload, tract in zip(payload["tracts"], scene.tracts, strict=True):
            tract_payload["path"] = _portable_output_path(
                tract.path,
                output_path.parent,
            )

        output_path.write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
        return output_path

    def export_png(
        self,
        output_path: str | Path,
        width: int,
        height: int,
    ) -> Path:
        output_path = Path(output_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._capture_png(
            str(output_path),
            width,
            height,
        )

        return output_path

    def close(self) -> None:
        self.plotter.close()
