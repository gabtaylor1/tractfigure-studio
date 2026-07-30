import nibabel as nib
import numpy as np

from tractfigure.vtk_conversion import nifti_to_image_data, streamlines_to_polydata


def test_streamlines_to_polydata() -> None:
    streamlines = (
        np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=np.float32),
        np.array([[0, 1, 0], [1, 1, 0]], dtype=np.float32),
    )

    polydata = streamlines_to_polydata(streamlines)

    assert polydata.n_points == 5
    assert polydata.n_lines == 2


def test_nifti_to_image_data() -> None:
    data = np.arange(4 * 5 * 6, dtype=np.float32).reshape((4, 5, 6))
    affine = np.diag([1.0, 1.5, 2.0, 1.0])
    image = nib.Nifti1Image(data, affine)

    grid = nifti_to_image_data(image)

    assert tuple(grid.dimensions) == data.shape
    assert np.allclose(grid.spacing, (1.0, 1.5, 2.0))
    assert grid.n_points == data.size
