"""Headless, deterministic recipe-to-PNG rendering with a provenance manifest.

Exit codes: 0 success, 2 invalid recipe/inputs or refused overwrite,
3 rendering failure. Every rendered setting comes from the recipe or a
documented command-line argument.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pyvista as pv

from tractfigure.gui.app_trame_v1_20260730 import load_recipe
from tractfigure.renderer_trame_v1_20260730 import SceneRenderer

EXIT_OK = 0
EXIT_INVALID = 2
EXIT_RENDER_FAILED = 3

VIEW_CHOICES = (
    "perspective",
    "sagittal-left",
    "sagittal-right",
    "coronal-anterior",
    "coronal-posterior",
    "axial-superior",
    "axial-inferior",
)

TRACKED_PACKAGES = ("tractfigure-studio", "python", "dipy", "vtk", "pyvista", "trame")


def _software_versions() -> dict[str, str]:
    versions: dict[str, str] = {"python": sys.version.split()[0]}

    for package in TRACKED_PACKAGES:
        if package == "python":
            continue

        versions[package] = version(package)

    return versions


def _scene_inputs(scene: Any) -> list[tuple[str, Path]]:
    entries = [("image", Path(scene.image.path))]
    entries += [("tractogram", Path(tract.path)) for tract in scene.tracts]

    if scene.mesh is not None:
        entries.append(("mesh", Path(scene.mesh.path)))

    return entries


def _input_provenance(scene: Any) -> list[dict[str, Any]]:
    return [
        {"role": role, "path": str(path), "bytes": path.stat().st_size}
        for role, path in _scene_inputs(scene)
    ]


def _missing_inputs(scene: Any) -> list[Path]:
    return [path for _role, path in _scene_inputs(scene) if not path.is_file()]


def configure_cli(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tractfigure-render",
        description="Render a validated scene recipe to PNGs without a browser.",
    )
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--views", nargs="+", choices=VIEW_CHOICES, default=["perspective"])
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing outputs instead of failing.",
    )
    return parser.parse_args(argv)


def _render_view(renderer: SceneRenderer, view: str) -> None:
    if view == "perspective":
        renderer.set_perspective_view()
        return

    plane, side = view.split("-", 1)
    renderer.set_anatomical_view(plane, side)


def render_main(argv: list[str]) -> int:
    args = configure_cli(argv)
    output_directory = args.output_dir.expanduser().resolve()

    try:
        scene = load_recipe(args.recipe)
    except Exception as error:
        print(f"Recipe is not loadable: {error}", file=sys.stderr)
        return EXIT_INVALID

    missing = _missing_inputs(scene)
    if missing:
        print("Recipe inputs missing:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        return EXIT_INVALID

    stem = args.recipe.expanduser().resolve().stem
    outputs = [f"{stem}_{view}.png" for view in args.views]
    existing = [name for name in outputs if (output_directory / name).is_file()]

    if existing and not args.overwrite:
        print(
            "Outputs exist; pass --overwrite to replace:",
            ", ".join(existing),
            file=sys.stderr,
        )
        return EXIT_INVALID

    output_directory.mkdir(parents=True, exist_ok=True)
    pv.OFF_SCREEN = True
    baseline = scene.model_copy(deep=True)
    plotter = pv.Plotter(off_screen=True, window_size=(scene.canvas.width, scene.canvas.height))
    renderer = SceneRenderer(plotter)

    try:
        renderer.load_scene(scene)
    except Exception as error:
        print(f"Rendering failed: {error}", file=sys.stderr)
        return EXIT_RENDER_FAILED

    try:
        for view, name in zip(args.views, outputs, strict=True):
            _render_view(renderer, view)
            renderer.export_png(
                output_directory / name,
                scene.canvas.width,
                scene.canvas.height,
            )
            renderer.restore_scene_settings(baseline)
    except Exception as error:
        print(f"Rendering failed: {error}", file=sys.stderr)
        return EXIT_RENDER_FAILED
    finally:
        renderer.close()

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "software": _software_versions(),
        "recipe": str(args.recipe.expanduser().resolve()),
        "views": list(args.views),
        "canvas": {"width": scene.canvas.width, "height": scene.canvas.height},
        "inputs": _input_provenance(scene),
        "outputs": outputs,
    }
    (output_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return EXIT_OK


def main() -> None:
    sys.exit(render_main(sys.argv[1:]))


if __name__ == "__main__":
    main()
