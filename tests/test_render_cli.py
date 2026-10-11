import json
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from dipy.io.stateful_tractogram import Space, StatefulTractogram
from dipy.io.streamline import save_tractogram

from tractfigure.render_cli import render_main
from tractfigure.scene_state_v1_20260730 import (
    ImageLayerState,
    SceneState,
    TractLayerState,
)


@pytest.fixture()
def recipe_setup(tmp_path: Path) -> tuple[Path, Path]:
    affine = np.eye(4)
    reference = tmp_path / "data" / "t1.nii.gz"
    reference.parent.mkdir()
    nib.save(nib.Nifti1Image(np.zeros((10, 12, 14), dtype=np.float32), affine), reference)

    points = [np.array([[2.0, 3.0, 4.0], [3.0, 4.0, 5.0]], dtype=np.float32)]
    bundle = tmp_path / "data" / "bundle.tck"
    save_tractogram(
        StatefulTractogram(points, nib.load(str(reference)), Space.RASMM),
        bundle,
    )

    scene = SceneState(
        image=ImageLayerState(path=Path("../data/t1.nii.gz")),
        tracts=[
            TractLayerState(
                id="tract-0",
                name="bundle",
                path=Path("../data/bundle.tck"),
                color="#E64B35",
            )
        ],
        active_layer_id="tract-0",
    )
    scene.canvas.width = 320
    scene.canvas.height = 240
    recipes = tmp_path / "recipes"
    recipes.mkdir()
    recipe = recipes / "figure.json"
    recipe.write_text(scene.model_dump_json(indent=2), encoding="utf-8")
    return recipe, tmp_path


def test_render_cli_produces_pngs_and_manifest(recipe_setup, tmp_path) -> None:
    recipe, _root = recipe_setup
    output = tmp_path / "out"

    exit_code = render_main(["--recipe", str(recipe), "--output-dir", str(output)])

    assert exit_code == 0
    png = output / "figure_perspective.png"
    assert png.is_file()

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["recipe"] == str(recipe.resolve())
    assert manifest["software"]["tractfigure-studio"]
    assert manifest["software"]["dipy"]
    assert {entry["role"] for entry in manifest["inputs"]} == {"image", "tractogram"}
    assert all(Path(entry["path"]).is_file() for entry in manifest["inputs"])
    assert all(entry["bytes"] > 0 for entry in manifest["inputs"])
    assert manifest["outputs"] == ["figure_perspective.png"]
    assert manifest["canvas"] == {"width": 320, "height": 240}

    from PIL import Image

    with Image.open(png) as image:
        assert image.size == (320, 240)


def test_render_cli_refuses_overwrite_without_flag(recipe_setup, tmp_path) -> None:
    recipe, _root = recipe_setup
    output = tmp_path / "out"

    assert render_main(["--recipe", str(recipe), "--output-dir", str(output)]) == 0
    assert render_main(["--recipe", str(recipe), "--output-dir", str(output)]) == 2
    assert (
        render_main(
            ["--recipe", str(recipe), "--output-dir", str(output), "--overwrite"]
        )
        == 0
    )


def test_render_cli_fails_before_rendering_on_missing_data(recipe_setup, tmp_path) -> None:
    recipe, _root = recipe_setup
    (recipe.parent.parent / "data" / "bundle.tck").unlink()
    output = tmp_path / "out"

    exit_code = render_main(["--recipe", str(recipe), "--output-dir", str(output)])

    assert exit_code == 2
    assert not output.exists() or not list(output.glob("*.png"))


def test_render_cli_repeated_runs_are_identical(recipe_setup, tmp_path) -> None:
    recipe, _root = recipe_setup
    first = tmp_path / "out_a"
    second = tmp_path / "out_b"

    assert render_main(["--recipe", str(recipe), "--output-dir", str(first)]) == 0
    assert render_main(["--recipe", str(recipe), "--output-dir", str(second)]) == 0

    assert (first / "figure_perspective.png").read_bytes() == (
        second / "figure_perspective.png").read_bytes()
    manifest_a = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    manifest_b = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    del manifest_a["generated_at"], manifest_b["generated_at"]
    manifest_a["outputs"] = manifest_b["outputs"] = []
    assert manifest_a == manifest_b


def test_render_cli_exposes_console_entry_point() -> None:
    script = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert "tractfigure-render" in script.read_text(encoding="utf-8")
    completed = subprocess.run(
        ["tractfigure-render", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "--recipe" in completed.stdout
