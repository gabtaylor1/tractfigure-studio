from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from nibabel.affines import apply_affine

from tractfigure.io import (
    detect_source_coordinates,
    point_fraction_inside_reference,
    reference_world_bounds,
    source_to_rasmm_affine,
    tractogram_extension,
)


def test_tractogram_extension() -> None:
    assert tractogram_extension("bundle.trk") == ".trk"
    assert tractogram_extension("bundle.tck.gz") == ".tck.gz"


def test_source_to_rasmm_affines_include_origin_shift() -> None:
    affine = np.array(
        [
            [2.0, 0.0, 0.0, -10.0],
            [0.0, 3.0, 0.0, -20.0],
            [0.0, 0.0, 4.0, -30.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    zooms = (2.0, 3.0, 4.0)

    assert np.allclose(
        source_to_rasmm_affine("rasmm", "nifti", affine, zooms),
        np.eye(4),
    )
    assert np.allclose(
        source_to_rasmm_affine("lpsmm", "nifti", affine, zooms),
        np.diag([-1.0, -1.0, 1.0, 1.0]),
    )
    assert np.allclose(
        source_to_rasmm_affine("vox", "nifti", affine, zooms),
        affine,
    )

    expected_trackvis = affine.copy()
    expected_trackvis[:3, 3] += affine[:3, :3] @ np.full(3, -0.5)
    assert np.allclose(
        source_to_rasmm_affine("vox", "trackvis", affine, zooms),
        expected_trackvis,
    )


def test_reference_bounds_and_inside_fraction() -> None:
    affine = np.diag([2.0, 3.0, 4.0, 1.0])
    dimensions = (8, 9, 10)
    lower, upper = reference_world_bounds(affine, dimensions)
    corners = apply_affine(
        affine,
        np.array([[-0.5, -0.5, -0.5], [7.5, 8.5, 9.5]]),
    )
    assert np.allclose(lower, corners.min(axis=0))
    assert np.allclose(upper, corners.max(axis=0))

    inside = apply_affine(affine, np.array([[1.0, 1.0, 1.0], [6.0, 7.0, 8.0]]))
    outside = apply_affine(affine, np.array([[20.0, 20.0, 20.0]]))
    assert point_fraction_inside_reference(
        (inside, outside),
        affine,
        dimensions,
    ) == pytest.approx(2 / 3)


def test_automatic_lpsmm_detection(tmp_path: Path) -> None:
    shape = (40, 50, 60)
    affine = np.array(
        [
            [2.0, 0.0, 0.0, -35.0],
            [0.0, 2.5, 0.0, -45.0],
            [0.0, 0.0, 3.0, -50.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    data = np.zeros(shape, dtype=np.float32)
    data[25:35, 8:18, 35:48] = 1.0
    reference = tmp_path / "reference.nii.gz"
    nib.save(nib.Nifti1Image(data, affine), reference)

    voxel_points = np.array(
        [[x, y, z] for x in range(27, 33) for y in range(10, 16) for z in range(38, 45)],
        dtype=float,
    )
    rasmm_points = apply_affine(affine, voxel_points)
    rasmm_to_lpsmm = np.diag([-1.0, -1.0, 1.0, 1.0])
    raw_lpsmm = apply_affine(rasmm_to_lpsmm, rasmm_points).astype(np.float32)

    detection = detect_source_coordinates(
        (raw_lpsmm,),
        reference,
        affine,
        (2.0, 2.5, 3.0),
    )

    assert detection.source_space == "lpsmm"
    assert detection.confidence in {"moderate", "high"}
    assert detection.candidate_scores[0][0].startswith("lpsmm/")
