from __future__ import annotations

import json
import os
import re
from itertools import cycle
from pathlib import Path

from tractfigure.gui.app_trame_v1_20260730 import DEFAULT_COLORS
from tractfigure.scene_state_v1_20260730 import (
    CanvasState,
    ImageLayerState,
    SceneState,
    TractLayerState,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PROJECT_ROOT / "demo_data" / "data_inventory.json"
RECIPE_PATH = PROJECT_ROOT / "examples" / "recipes" / "five_bundle_trame_v1_20260730.json"


def project_path(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


def layer_id(path: Path) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-")
    return normalized or "tract"


def portable_relative(path: Path, directory: Path) -> str:
    """Return a recipe-relative path using JSON-portable forward slashes."""

    return Path(os.path.relpath(path.resolve(), directory.resolve())).as_posix()


def main() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    reference = project_path(inventory["file_formats"]["reference"])
    tractograms = [project_path(value) for value in inventory["file_formats"]["tractograms"]]
    recipe_directory = RECIPE_PATH.parent.resolve()
    colors = cycle(DEFAULT_COLORS)

    tracts = [
        TractLayerState(
            id=layer_id(path),
            name=path.stem,
            path=Path(os.path.relpath(path, recipe_directory)),
            color=color,
        )
        for path, color in zip(tractograms, colors, strict=False)
    ]
    scene = SceneState(
        image=ImageLayerState(
            path=Path(os.path.relpath(reference, recipe_directory)),
            opacity=1.0,
        ),
        tracts=tracts,
        active_layer_id=tracts[0].id,
        canvas=CanvasState(
            width=1400,
            height=1000,
            background="#FFFFFF",
        ),
    )

    payload = scene.model_dump(mode="json")
    payload["image"]["path"] = portable_relative(reference, recipe_directory)

    for tract_payload, tractogram in zip(
        payload["tracts"],
        tractograms,
        strict=True,
    ):
        tract_payload["path"] = portable_relative(tractogram, recipe_directory)

    RECIPE_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECIPE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Demo recipe ready: {RECIPE_PATH}")


if __name__ == "__main__":
    main()
