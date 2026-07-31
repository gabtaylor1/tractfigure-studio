from __future__ import annotations

import argparse
from pathlib import Path

import pyvista as pv

from tractfigure.gui.app_trame_v1_20260730 import load_recipe
from tractfigure.renderer_trame_v1_20260730 import SceneRenderer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECIPE = PROJECT_ROOT / "examples" / "recipes" / "five_bundle_trame_v1_20260730.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "reference_renders"


def configure_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe", type=Path, default=DEFAULT_RECIPE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def export(renderer: SceneRenderer, output_path: Path) -> None:
    scene = renderer._require_scene()
    renderer.export_png(output_path, scene.canvas.width, scene.canvas.height)


def main() -> None:
    args = configure_cli()
    output_directory = args.output_dir.expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    pv.OFF_SCREEN = True

    scene = load_recipe(args.recipe)
    plotter = pv.Plotter(
        off_screen=True,
        window_size=(scene.canvas.width, scene.canvas.height),
    )
    renderer = SceneRenderer(plotter)

    try:
        active_scene = renderer.load_scene(scene)
        baseline = active_scene.model_copy(deep=True)

        renderer.set_background("#FFFFFF")
        renderer.set_image_visible(True)
        renderer.set_image_opacity(1.0)
        renderer.reset_camera()
        export(renderer, output_directory / "white_publication.png")

        renderer.set_background("#000000")
        renderer.set_image_opacity(0.35)
        export(renderer, output_directory / "black_tracts.png")

        renderer.restore_scene_settings(baseline)
        renderer.set_anatomical_view("sagittal", "left")
        export(renderer, output_directory / "orthographic_sagittal_left.png")
        renderer.set_anatomical_view("coronal", "anterior")
        export(renderer, output_directory / "orthographic_coronal_anterior.png")
        renderer.set_anatomical_view("axial", "superior")
        export(renderer, output_directory / "orthographic_axial_superior.png")

        renderer.set_image_visible(False)
        renderer.set_perspective_view()
        export(renderer, output_directory / "tract_only_white.png")
    finally:
        renderer.close()

    print(f"Reference renders ready: {output_directory}")


if __name__ == "__main__":
    main()
