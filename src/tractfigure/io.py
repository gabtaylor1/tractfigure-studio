from pathlib import Path

import numpy as np
from dipy.io.stateful_tractogram import Space
from dipy.io.streamline import load_tractogram

SUPPORTED_EXTENSIONS = {
    ".trk",
    ".tck",
    ".trx",
    ".vtk",
    ".vtp",
    ".fib",
    ".dpy",
}


def tractogram_extension(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".gz":
        return "".join(path.suffixes[-2:]).lower()

    return suffix


def load_streamlines_rasmm(
    tractogram_path: str | Path,
    reference_path: str | Path | None = None,
) -> tuple[np.ndarray, ...]:
    """Load a tractogram and return streamlines in RAS+ world millimeters."""

    tractogram_path = Path(tractogram_path).expanduser().resolve()

    if not tractogram_path.is_file():
        raise FileNotFoundError(f"Tractogram does not exist: {tractogram_path}")

    extension = tractogram_extension(tractogram_path)

    if extension.endswith(".gz"):
        raise ValueError(
            "Compressed tractograms will be added through a dedicated adapter. "
            f"Decompress this file for the initial checkpoint: {tractogram_path.name}"
        )

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported tractogram extension {extension!r}. Supported: {supported}")

    if reference_path is None:
        if extension in {".trk", ".trx"}:
            reference: str | Path = "same"
        else:
            raise ValueError(
                f"{extension} requires a corresponding reference NIfTI or TRK header."
            )
    else:
        reference_path = Path(reference_path).expanduser().resolve()

        if not reference_path.is_file():
            raise FileNotFoundError(f"Reference image does not exist: {reference_path}")

        reference = reference_path

    stateful = load_tractogram(
        str(tractogram_path),
        str(reference),
        to_space=Space.RASMM,
        bbox_valid_check=True,
    )

    if stateful is False or stateful is None:
        raise RuntimeError(f"DIPY could not load {tractogram_path}")

    streamlines = tuple(
        np.asarray(streamline, dtype=np.float32)
        for streamline in stateful.streamlines
        if len(streamline) >= 2
    )

    if not streamlines:
        raise ValueError(f"No valid streamlines were found in {tractogram_path}")

    if any(streamline.ndim != 2 or streamline.shape[1] != 3 for streamline in streamlines):
        raise ValueError("Every streamline must have shape (number_of_points, 3)")

    if any(not np.isfinite(streamline).all() for streamline in streamlines):
        raise ValueError("The tractogram contains non-finite coordinates")

    return streamlines


def streamline_bounds(
    streamlines: tuple[np.ndarray, ...],
) -> tuple[np.ndarray, np.ndarray]:
    points = np.concatenate(streamlines, axis=0)
    return points.min(axis=0), points.max(axis=0)
