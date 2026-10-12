from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from dipy.io.stateful_tractogram import Space, StatefulTractogram
from dipy.io.streamline import save_tractogram
from nibabel.affines import apply_affine
from scipy.io import savemat

from tractfigure.io import (
    detect_source_coordinates,
    load_tinytrack,
    load_tract_layer,
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


def test_load_tinytrack_decodes_deltas_and_affine(tmp_path: Path) -> None:
    first = np.array([32, 64, 96], dtype="<i4")  # voxel (1, 2, 3) in 1/32 units
    deltas = np.array([[32, 0, 0], [0, -32, 0]], dtype=np.int8)
    byte_count = np.array([3 + deltas.size], dtype="<u4")  # 3 bytes per point incl. the first
    track = np.concatenate(
        [byte_count.view(np.uint8), first.view(np.uint8), deltas.reshape(-1).view(np.uint8)]
    )
    trans = np.array([-1, 0, 0, 10, 0, 1, 0, 20, 0, 0, 1, 30, 0, 0, 0, 1], dtype=np.float32)
    path = tmp_path / "t.tt"
    savemat(
        path,
        {"track": track[:, None], "trans_to_mni": trans[None], "voxel_size": np.ones((1, 3))},
        format="4",
    )

    (streamline,) = load_tinytrack(path)
    expected = np.array([[9.0, 22.0, 33.0], [8.0, 22.0, 33.0], [8.0, 21.0, 33.0]])
    np.testing.assert_allclose(streamline, expected)


def test_load_tract_layer_reads_trk_with_keyword_dipy_space(tmp_path: Path) -> None:
    # dipy >= 1.12 makes to_space keyword-only; a positional reference in the
    # to_space slot breaks every .trk load (issue #12).
    affine = np.array(
        [
            [2.0, 0.0, 0.0, -35.0],
            [0.0, 2.0, 0.0, -45.0],
            [0.0, 0.0, 2.0, -50.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    data = np.zeros((30, 40, 45), dtype=np.float32)
    data[10:20, 10:20, 15:25] = 1.0
    reference_image = nib.Nifti1Image(data, affine)
    reference = tmp_path / "reference.nii.gz"
    nib.save(reference_image, reference)

    streamlines = [
        np.array([[-5.0, 0.0, 5.0], [-3.0, 2.0, 7.0], [-1.0, 4.0, 9.0]], dtype=np.float32),
        np.array([[-7.0, -2.0, 3.0], [-6.0, -1.0, 4.0], [-5.0, 0.0, 5.0]], dtype=np.float32),
    ]
    bundle = tmp_path / "bundle.trk"
    save_tractogram(
        StatefulTractogram(streamlines, reference_image, Space.RASMM),
        bundle,
    )

    layer = load_tract_layer(bundle, reference)

    assert layer.inspection.coordinate_detection == "embedded format metadata"
    assert len(layer.streamlines) == 2
    assert np.allclose(layer.streamlines[0], streamlines[0])
    assert np.allclose(layer.streamlines[1], streamlines[1])
    assert layer.inspection.point_fraction_inside_reference == pytest.approx(1.0)
    assert layer.inspection.warnings == ()
