import nibabel as nib
import numpy as np
import pyvista as pv


def streamlines_to_polydata(
    streamlines: tuple[np.ndarray, ...],
    max_streamlines: int | None = None,
) -> pv.PolyData:
    selected = streamlines

    if max_streamlines is not None and len(selected) > max_streamlines:
        indices = np.linspace(
            0,
            len(selected) - 1,
            num=max_streamlines,
            dtype=int,
        )
        selected = tuple(selected[index] for index in indices)

    points = np.concatenate(selected, axis=0)
    line_array_size = sum(len(streamline) + 1 for streamline in selected)
    lines = np.empty(line_array_size, dtype=np.int64)

    point_offset = 0
    line_offset = 0

    for streamline in selected:
        number_of_points = len(streamline)

        lines[line_offset] = number_of_points
        lines[line_offset + 1 : line_offset + 1 + number_of_points] = np.arange(
            point_offset,
            point_offset + number_of_points,
            dtype=np.int64,
        )

        point_offset += number_of_points
        line_offset += number_of_points + 1

    polydata = pv.PolyData(points)
    polydata.lines = lines
    return polydata


def nifti_to_image_data(image: nib.spatialimages.SpatialImage) -> pv.ImageData:
    """Convert a 3D NIfTI image into world-coordinate PyVista ImageData."""

    image = nib.as_closest_canonical(image)
    data = np.asarray(image.dataobj, dtype=np.float32)

    if data.ndim != 3:
        raise ValueError(f"Expected a 3D image; received shape {data.shape}")

    affine = np.asarray(image.affine, dtype=float)
    basis = affine[:3, :3]
    spacing = np.linalg.norm(basis, axis=0)

    if np.any(spacing <= 0):
        raise ValueError("Image affine contains invalid voxel spacing")

    direction = basis / spacing

    if not np.allclose(direction.T @ direction, np.eye(3), atol=1e-4):
        raise ValueError("The initial viewer does not support sheared image affines")

    grid = pv.ImageData(
        dimensions=data.shape,
        spacing=spacing,
        origin=affine[:3, 3],
        direction_matrix=direction,
    )
    grid.point_data["intensity"] = data.ravel(order="F")
    return grid
