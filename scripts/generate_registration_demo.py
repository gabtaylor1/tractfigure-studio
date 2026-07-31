from __future__ import annotations

import argparse
import json
from pathlib import Path

import nibabel as nib
import numpy as np
from dipy.io.stateful_tractogram import Origin, Space, StatefulTractogram
from dipy.io.streamline import save_tractogram
from scipy.spatial.transform import Rotation

from tractfigure.io import load_tract_layer
from tractfigure.registration import (
    apply_affine_to_streamlines,
    registration_qc_figure,
    resample_image_to_fixed,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = PROJECT_ROOT / "demo_data" / "data_inventory.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "demo_data" / "registration"


def configure_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def project_path(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


def image_world_center(image: nib.spatialimages.SpatialImage) -> np.ndarray:
    voxel_center = (np.asarray(image.shape, dtype=float) - 1.0) / 2.0
    return nib.affines.apply_affine(image.affine, voxel_center)


def centered_affine(
    center: np.ndarray,
    linear: np.ndarray,
    translation: tuple[float, float, float],
) -> np.ndarray:
    to_center = np.eye(4)
    to_center[:3, 3] = center
    from_center = np.eye(4)
    from_center[:3, 3] = -center
    linear_affine = np.eye(4)
    linear_affine[:3, :3] = linear
    translate = np.eye(4)
    translate[:3, 3] = translation
    return translate @ to_center @ linear_affine @ from_center


def fixture_transforms(
    image: nib.spatialimages.SpatialImage,
) -> dict[str, np.ndarray]:
    center = image_world_center(image)
    rigid_linear = Rotation.from_euler(
        "xyz",
        (4.0, -3.0, 6.0),
        degrees=True,
    ).as_matrix()
    affine_linear = Rotation.from_euler(
        "xyz",
        (-3.0, 4.0, 5.0),
        degrees=True,
    ).as_matrix() @ np.array(
        [
            [1.04, 0.02, 0.00],
            [0.00, 0.97, 0.01],
            [0.00, 0.00, 1.02],
        ]
    )

    return {
        "identity": np.eye(4),
        "rigid": centered_affine(center, rigid_linear, (4.0, -5.0, 3.0)),
        "affine": centered_affine(center, affine_linear, (-5.0, 4.0, 2.0)),
    }


def save_rasmm_tractogram(
    streamlines: tuple[np.ndarray, ...],
    reference: Path,
    output_path: Path,
) -> None:
    tractogram = StatefulTractogram(
        streamlines,
        str(reference),
        Space.RASMM,
        origin=Origin.NIFTI,
    )
    save_tractogram(
        tractogram,
        str(output_path),
        bbox_valid_check=False,
    )


def main() -> None:
    args = configure_cli()
    inventory_path = args.inventory.expanduser().resolve()
    output_root = args.output_dir.expanduser().resolve()
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))

    reference_path = project_path(inventory["file_formats"]["reference"])
    tractogram_paths = [project_path(value) for value in inventory["file_formats"]["tractograms"]]
    fixed_image = nib.as_closest_canonical(nib.load(reference_path))
    loaded_layers = [
        load_tract_layer(path, reference_path=reference_path) for path in tractogram_paths
    ]

    for case_name, fixed_to_moving in fixture_transforms(fixed_image).items():
        case_directory = output_root / case_name
        case_directory.mkdir(parents=True, exist_ok=True)

        fixed_path = case_directory / "fixed.nii.gz"
        moving_path = case_directory / "moving.nii.gz"
        moving_to_fixed = np.linalg.inv(fixed_to_moving)
        moving_image = resample_image_to_fixed(
            fixed_image,
            fixed_image,
            fixed_to_moving,
        )

        nib.save(fixed_image, fixed_path)
        nib.save(moving_image, moving_path)
        np.savetxt(
            case_directory / "ground_truth_moving_to_fixed.txt",
            moving_to_fixed,
            fmt="%.10f",
        )

        tract_entries = []
        for layer in loaded_layers:
            fixed_tract_path = case_directory / f"{layer.path.stem}_fixed.trk"
            moving_tract_path = case_directory / f"{layer.path.stem}_moving.trk"
            moving_streamlines = apply_affine_to_streamlines(
                layer.streamlines,
                fixed_to_moving,
            )
            save_rasmm_tractogram(layer.streamlines, fixed_path, fixed_tract_path)
            save_rasmm_tractogram(moving_streamlines, moving_path, moving_tract_path)
            tract_entries.append(
                {
                    "name": layer.name,
                    "fixed": fixed_tract_path.name,
                    "moving": moving_tract_path.name,
                    "streamline_count": len(layer.streamlines),
                }
            )

        registration_qc_figure(
            moving_image,
            fixed_image,
            moving_to_fixed,
            case_directory / "registration_qc.png",
        )

        metadata = {
            "case": case_name,
            "matrix_direction": "moving_rasmm_to_fixed_rasmm",
            "fixed_image": fixed_path.name,
            "moving_image": moving_path.name,
            "ground_truth": "ground_truth_moving_to_fixed.txt",
            "tractograms": tract_entries,
        }
        (case_directory / "fixture_metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Registration fixtures ready: {output_root}")


if __name__ == "__main__":
    main()
