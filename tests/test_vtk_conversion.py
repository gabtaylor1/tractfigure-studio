import nibabel as nib
import numpy as np
import pytest
from nibabel.affines import apply_affine

from tractfigure.vtk_conversion import (
    nifti_to_image_data,
    nifti_to_orthogonal_slices,
    streamlines_to_polydata,
)


def test_streamlines_to_polydata() -> None:
    streamlines = (
        np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=np.float32),
        np.array([[0, 1, 0], [1, 1, 0]], dtype=np.float32),
    )
    polydata = streamlines_to_polydata(streamlines)
    assert polydata.n_points == 5
    assert polydata.n_lines == 2


def test_streamline_subsampling_is_deterministic() -> None:
    streamlines = tuple(
        np.array([[index, 0, 0], [index, 1, 0]], dtype=np.float32) for index in range(10)
    )
    polydata = streamlines_to_polydata(streamlines, max_streamlines=3)
    assert polydata.n_lines == 3
    assert np.allclose(np.unique(polydata.points[:, 0]), (0.0, 4.0, 9.0))


def test_affine_exact_orthogonal_slices() -> None:
    data = np.arange(8 * 9 * 10, dtype=np.float32).reshape((8, 9, 10))
    affine = np.array(
        [
            [2.0, 0.0, 0.0, -12.0],
            [0.0, 2.5, 0.0, -15.0],
            [0.0, 0.0, 3.0, -18.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )
    image = nib.Nifti1Image(data, affine)
    indices = (3, 4, 5)
    slices = nifti_to_orthogonal_slices(image, indices=indices)
    inverse = np.linalg.inv(nib.as_closest_canonical(image).affine)

    for name, axis, index in (
        ("sagittal", 0, 3),
        ("coronal", 1, 4),
        ("axial", 2, 5),
    ):
        voxel_points = apply_affine(inverse, slices[name].points)
        assert np.allclose(voxel_points[:, axis], index)

    with pytest.raises(ValueError, match="outside"):
        nifti_to_orthogonal_slices(image, indices=(8, 4, 5))


def test_nifti_to_image_data() -> None:
    data = np.zeros((4, 5, 6), dtype=np.float32)
    affine = np.diag([1.0, 1.5, 2.0, 1.0])
    grid = nifti_to_image_data(nib.Nifti1Image(data, affine))
    assert tuple(grid.dimensions) == data.shape
    assert np.allclose(grid.spacing, (1.0, 1.5, 2.0))
