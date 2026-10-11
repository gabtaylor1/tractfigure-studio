import json
from pathlib import Path

import scripts.create_demo_recipe as create_demo_recipe


def test_generated_recipe_carries_glass_brain_mesh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    recipe_path = tmp_path / "recipes" / "five_bundle_trame_v1_20260730.json"
    monkeypatch.setattr(create_demo_recipe, "RECIPE_PATH", recipe_path)

    create_demo_recipe.main()

    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    mesh = payload["mesh"]
    assert mesh["path"].endswith("../../demo_data/dsi/mni152.gii")
    assert (mesh["opacity"], mesh["color"], mesh["shader"]) == (0.25, "#D9D9D9", "phong")
