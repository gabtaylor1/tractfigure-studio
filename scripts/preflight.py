from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_FILES = (
    "src/tractfigure/io.py",
    "src/tractfigure/vtk_conversion.py",
    "src/tractfigure/scene_state_v1_20260730.py",
    "src/tractfigure/renderer_trame_v1_20260730.py",
    "src/tractfigure/gui/app_trame_v1_20260730.py",
    "src/tractfigure/registration.py",
)

FORBIDDEN_NAME_FRAGMENTS = (
    "anatomical" + "_controls",
    "fast" + "_reset",
    "browser" + "_downloads",
    "patch" + "_2026",
)


def run(*arguments: str) -> None:
    subprocess.run(arguments, cwd=PROJECT_ROOT, check=True)


def verify_names() -> None:
    missing = [name for name in CANONICAL_FILES if not (PROJECT_ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing canonical files: " + ", ".join(missing))

    source_roots = (
        PROJECT_ROOT / "src",
        PROJECT_ROOT / "tests",
        PROJECT_ROOT / "scripts",
        PROJECT_ROOT / "examples",
    )

    for root in source_roots:
        for path in root.rglob("*"):
            forbidden = any(fragment in path.name for fragment in FORBIDDEN_NAME_FRAGMENTS)
            if path.is_file() and forbidden:
                raise ValueError(f"Temporary development filename remains: {path}")


def main() -> None:
    verify_names()
    run(sys.executable, "-m", "ruff", "check", "src", "tests", "scripts")
    run(sys.executable, "-m", "pytest", "-m", "not integration")
    run(sys.executable, "scripts/verify_demo_data.py")
    run(sys.executable, "scripts/create_demo_recipe.py")
    run(sys.executable, "scripts/generate_registration_demo.py")
    run(sys.executable, "-m", "pytest", "-m", "integration")
    run(sys.executable, "scripts/render_reference_scenes.py")
    print("Pre-hackathon release gate passed")


if __name__ == "__main__":
    main()
