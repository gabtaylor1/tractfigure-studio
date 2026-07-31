from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from dipy.align import affine_registration
from nibabel.affines import apply_affine
from scipy.ndimage import affine_transform


def _validate_matrix(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=float)

    if matrix.shape != (4, 4):
        raise ValueError("Affine matrix must have shape (4, 4)")

    if not np.isfinite(matrix).all():
        raise ValueError("Affine matrix contains non-finite values")

    if abs(np.linalg.det(matrix[:3, :3])) < 1e-10:
        raise ValueError("Affine matrix is singular")

    return matrix


def _as_3d_image(
    image: nib.spatialimages.SpatialImage,
    label: str,
) -> nib.spatialimages.SpatialImage:
    data = np.asarray(image.dataobj)

    if data.ndim != 3:
        raise ValueError(f"{label} image must be 3D; received shape {data.shape}")

    if not np.isfinite(data).all():
        raise ValueError(f"{label} image contains non-finite values")

    return image


def register_affine(
    moving: nib.spatialimages.SpatialImage,
    fixed: nib.spatialimages.SpatialImage,
    *,
    level_iters: Sequence[int] = (1000, 500, 100),
    sigmas: Sequence[float] = (3.0, 1.0, 0.0),
    factors: Sequence[int] = (4, 2, 1),
) -> np.ndarray:
    """Estimate a moving-RASMM to fixed-RASMM affine transformation."""

    moving = _as_3d_image(moving, "Moving")
    fixed = _as_3d_image(fixed, "Fixed")

    _transformed, fixed_to_moving = affine_registration(
        np.asarray(moving.dataobj, dtype=np.float32),
        np.asarray(fixed.dataobj, dtype=np.float32),
        moving_affine=np.asarray(moving.affine, dtype=float),
        static_affine=np.asarray(fixed.affine, dtype=float),
        pipeline=["center_of_mass", "translation", "rigid", "affine"],
        metric="MI",
        level_iters=list(level_iters),
        sigmas=list(sigmas),
        factors=list(factors),
    )
    return _validate_matrix(np.linalg.inv(fixed_to_moving))


def apply_affine_to_streamlines(
    streamlines: tuple[np.ndarray, ...],
    moving_to_fixed: np.ndarray,
) -> tuple[np.ndarray, ...]:
    """Map RASMM streamlines from moving space into fixed space."""

    matrix = _validate_matrix(moving_to_fixed)
    transformed = tuple(
        np.asarray(apply_affine(matrix, streamline), dtype=np.float32) for streamline in streamlines
    )

    if any(streamline.ndim != 2 or streamline.shape[1] != 3 for streamline in transformed):
        raise ValueError("Every streamline must have shape (number_of_points, 3)")

    if any(not np.isfinite(streamline).all() for streamline in transformed):
        raise ValueError("Transformed streamlines contain non-finite coordinates")

    return transformed


def resample_image_to_fixed(
    moving: nib.spatialimages.SpatialImage,
    fixed: nib.spatialimages.SpatialImage,
    moving_to_fixed: np.ndarray,
    *,
    order: int = 1,
) -> nib.Nifti1Image:
    """Resample a moving image into fixed geometry using a world-space affine."""

    moving = _as_3d_image(moving, "Moving")
    fixed = _as_3d_image(fixed, "Fixed")
    matrix = _validate_matrix(moving_to_fixed)

    output_voxel_to_input_voxel = (
        np.linalg.inv(np.asarray(moving.affine, dtype=float))
        @ np.linalg.inv(matrix)
        @ np.asarray(fixed.affine, dtype=float)
    )

    resampled = affine_transform(
        np.asarray(moving.dataobj, dtype=np.float32),
        matrix=output_voxel_to_input_voxel[:3, :3],
        offset=output_voxel_to_input_voxel[:3, 3],
        output_shape=tuple(int(value) for value in fixed.shape),
        order=int(order),
        mode="constant",
        cval=0.0,
        prefilter=order > 1,
    )

    header = fixed.header.copy()
    header.set_data_dtype(np.float32)
    return nib.Nifti1Image(
        np.asarray(resampled, dtype=np.float32),
        np.asarray(fixed.affine, dtype=float),
        header,
    )


def registration_qc_figure(
    moving: nib.spatialimages.SpatialImage,
    fixed: nib.spatialimages.SpatialImage,
    moving_to_fixed: np.ndarray,
    output_path: str | Path,
) -> Path:
    """Write a three-plane before/after registration QC figure."""

    moving = _as_3d_image(moving, "Moving")
    fixed = _as_3d_image(fixed, "Fixed")
    identity_resampled = resample_image_to_fixed(moving, fixed, np.eye(4))
    aligned = resample_image_to_fixed(moving, fixed, moving_to_fixed)

    fixed_data = np.asarray(fixed.dataobj, dtype=np.float32)
    before_data = np.asarray(identity_resampled.dataobj, dtype=np.float32)
    after_data = np.asarray(aligned.dataobj, dtype=np.float32)
    indices = tuple(size // 2 for size in fixed_data.shape)

    figure, axes = plt.subplots(2, 3, figsize=(12, 8), constrained_layout=True)

    for column, (axis, index, title) in enumerate(
        (
            (0, indices[0], "Sagittal"),
            (1, indices[1], "Coronal"),
            (2, indices[2], "Axial"),
        )
    ):
        if axis == 0:
            fixed_slice = fixed_data[index, :, :]
            before_slice = before_data[index, :, :]
            after_slice = after_data[index, :, :]
        elif axis == 1:
            fixed_slice = fixed_data[:, index, :]
            before_slice = before_data[:, index, :]
            after_slice = after_data[:, index, :]
        else:
            fixed_slice = fixed_data[:, :, index]
            before_slice = before_data[:, :, index]
            after_slice = after_data[:, :, index]

        for row, overlay, row_title in (
            (0, before_slice, "Before"),
            (1, after_slice, "After"),
        ):
            axes[row, column].imshow(
                np.rot90(fixed_slice),
                cmap="gray",
                interpolation="nearest",
            )
            axes[row, column].imshow(
                np.rot90(overlay),
                cmap="magma",
                alpha=0.40,
                interpolation="nearest",
            )
            axes[row, column].set_title(f"{row_title}: {title}")
            axes[row, column].axis("off")

    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=180, facecolor="white")
    plt.close(figure)
    return output_path
