from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from nibabel.affines import apply_affine

from tractfigure.registration import (
    apply_affine_to_streamlines,
    register_affine,
    resample_image_to_fixed,
)


def asymmetric_image() -> nib.Nifti1Image:
    data = np.zeros((32, 32, 32), dtype=np.float32)
    data[5:12, 7:16, 9:18] = 1.0
    data[18:26, 19:24, 5:12] = 0.7
    data[12:17, 4:9, 22:29] = 0.4
    return nib.Nifti1Image(data, np.eye(4))


def test_identity_preserves_streamlines() -> None:
    streamlines = (
        np.array([[0, 0, 0], [1, 2, 3]], dtype=np.float32),
        np.array([[4, 5, 6], [7, 8, 9]], dtype=np.float32),
    )
    transformed = apply_affine_to_streamlines(streamlines, np.eye(4))
    for actual, expected in zip(transformed, streamlines, strict=True):
        assert np.allclose(actual, expected)


def test_known_affine_maps_moving_points_to_fixed() -> None:
    fixed_streamlines = (np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype=np.float32),)
    fixed_to_moving = np.array(
        [
            [1.0, 0.0, 0.0, 4.0],
            [0.0, 1.0, 0.0, -3.0],
            [0.0, 0.0, 1.0, 2.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    moving = tuple(
        apply_affine(fixed_to_moving, streamline).astype(np.float32)
        for streamline in fixed_streamlines
    )
    actual = apply_affine_to_streamlines(moving, np.linalg.inv(fixed_to_moving))
    assert np.allclose(actual[0], fixed_streamlines[0], atol=1e-5)


def test_resampled_image_uses_fixed_geometry() -> None:
    moving = asymmetric_image()
    fixed_data = np.zeros((24, 25, 26), dtype=np.float32)
    fixed_affine = np.diag([1.5, 1.5, 2.0, 1.0])
    fixed = nib.Nifti1Image(fixed_data, fixed_affine)
    result = resample_image_to_fixed(moving, fixed, np.eye(4))
    assert result.shape == fixed.shape
    assert np.allclose(result.affine, fixed.affine)


@pytest.mark.registration
def test_affine_registration_improves_alignment() -> None:
    fixed = asymmetric_image()
    fixed_to_moving = np.eye(4)
    fixed_to_moving[:3, 3] = (2.0, -1.0, 1.0)
    moving = resample_image_to_fixed(fixed, fixed, fixed_to_moving)
    moving_to_fixed = register_affine(
        moving,
        fixed,
        level_iters=(100, 50, 20),
        sigmas=(2.0, 1.0, 0.0),
        factors=(4, 2, 1),
    )
    aligned = resample_image_to_fixed(moving, fixed, moving_to_fixed)
    before_error = np.mean((np.asarray(moving.dataobj) - np.asarray(fixed.dataobj)) ** 2)
    after_error = np.mean((np.asarray(aligned.dataobj) - np.asarray(fixed.dataobj)) ** 2)
    assert np.isfinite(moving_to_fixed).all()
    assert after_error < before_error


@pytest.mark.integration
def test_generated_registration_fixtures() -> None:
    project_root = Path(__file__).resolve().parents[1]
    fixture_root = project_root / "demo_data" / "registration"

    for case in ("identity", "rigid", "affine"):
        case_directory = fixture_root / case
        required = (
            case_directory / "fixed.nii.gz",
            case_directory / "moving.nii.gz",
            case_directory / "ground_truth_moving_to_fixed.txt",
            case_directory / "registration_qc.png",
            case_directory / "fixture_metadata.json",
        )
        for path in required:
            assert path.is_file(), (
                "Run scripts/generate_registration_demo.py before integration tests: "
                f"missing {path}"
            )

        matrix = np.loadtxt(case_directory / "ground_truth_moving_to_fixed.txt")
        assert matrix.shape == (4, 4)
        assert np.isfinite(matrix).all()
