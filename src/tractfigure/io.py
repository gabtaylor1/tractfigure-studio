from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from pathlib import Path

import nibabel as nib
import numpy as np
from dipy.io.stateful_tractogram import Origin, Space
from dipy.io.streamline import load_tractogram
from nibabel.affines import apply_affine
from scipy.ndimage import distance_transform_edt

SUPPORTED_EXTENSIONS = {
    ".trk",
    ".tck",
    ".trx",
    ".vtk",
    ".vtp",
    ".fib",
    ".dpy",
}

SELF_DESCRIBING_SPATIAL_EXTENSIONS = {".trk", ".tck", ".trx"}

SOURCE_SPACES = {
    "rasmm": Space.RASMM,
    "lpsmm": Space.LPSMM,
    "vox": Space.VOX,
    "voxmm": Space.VOXMM,
}

SOURCE_ORIGINS = {
    "nifti": Origin.NIFTI,
    "trackvis": Origin.TRACKVIS,
}

AUTO_DETECTION_CANDIDATES = tuple(product(SOURCE_SPACES, SOURCE_ORIGINS))
AUTO_DETECTION_MAX_POINTS = 200_000
AUTO_DETECTION_DEPTH_SCALE_MM = 10.0


@dataclass(frozen=True)
class ReferenceSupport:
    affine: np.ndarray
    inverse_affine: np.ndarray
    dimensions: tuple[int, int, int]
    voxel_sizes: tuple[float, float, float]
    foreground: np.ndarray
    foreground_distance_mm: np.ndarray


@dataclass(frozen=True)
class CoordinateDetection:
    source_space: str
    source_origin: str
    transform: np.ndarray
    confidence: str
    candidate_scores: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class TractInspection:
    filename: str
    detected_format: str
    streamline_count: int
    point_count: int
    coordinate_detection: str
    detection_confidence: str
    candidate_scores: tuple[tuple[str, float], ...]
    source_space: str
    source_origin: str
    output_space: str
    source_to_rasmm: tuple[tuple[float, ...], ...]
    world_bounds_min: tuple[float, float, float]
    world_bounds_max: tuple[float, float, float]
    reference: str
    reference_dimensions: tuple[int, int, int]
    reference_voxel_sizes: tuple[float, float, float]
    reference_orientation: tuple[str, str, str]
    reference_world_bounds_min: tuple[float, float, float]
    reference_world_bounds_max: tuple[float, float, float]
    bounding_boxes_overlap: bool
    point_fraction_inside_reference: float
    warnings: tuple[str, ...]

    def format_report(self) -> str:
        matrix = np.array2string(
            np.asarray(self.source_to_rasmm),
            precision=4,
            suppress_small=True,
        )
        orientation = "".join(self.reference_orientation)
        warning_text = "\n".join(f"  WARNING: {warning}" for warning in self.warnings)
        if not warning_text:
            warning_text = "  Warnings: none"

        score_text = ", ".join(
            f"{candidate}={score:.4f}" for candidate, score in self.candidate_scores
        )
        if not score_text:
            score_text = "embedded format metadata"

        return "\n".join(
            (
                f"Tract: {self.filename}",
                f"  Detected format: {self.detected_format}",
                f"  Streamlines: {self.streamline_count}",
                f"  Points: {self.point_count}",
                f"  Coordinate detection: {self.coordinate_detection}",
                f"  Detection confidence: {self.detection_confidence}",
                f"  Candidate scores: {score_text}",
                f"  Coordinate state: {self.source_space}/{self.source_origin} -> RASMM/NIFTI",
                f"  Source-to-RASMM transform:\n{matrix}",
                f"  World bounds: {self.world_bounds_min} to {self.world_bounds_max}",
                f"  Reference: {self.reference}",
                f"  Reference dimensions: {self.reference_dimensions}",
                f"  Reference voxel sizes: {self.reference_voxel_sizes}",
                f"  Reference orientation: {orientation}",
                (
                    "  Reference world bounds: "
                    f"{self.reference_world_bounds_min} to "
                    f"{self.reference_world_bounds_max}"
                ),
                f"  Bounding boxes overlap: {self.bounding_boxes_overlap}",
                (
                    "  Point fraction inside reference: "
                    f"{self.point_fraction_inside_reference:.1%}"
                ),
                warning_text,
            )
        )


@dataclass(frozen=True)
class TractLayer:
    name: str
    path: Path
    streamlines: tuple[np.ndarray, ...]
    inspection: TractInspection


def tractogram_extension(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".gz":
        return "".join(path.suffixes[-2:]).lower()

    return suffix


def _as_source_space(source_space: str | Space) -> tuple[str, Space]:
    if isinstance(source_space, Space):
        for name, enum_value in SOURCE_SPACES.items():
            if source_space == enum_value:
                return name, enum_value

    key = str(source_space).strip().lower()
    if key not in SOURCE_SPACES:
        choices = ", ".join(SOURCE_SPACES)
        raise ValueError(f"Unknown source space {source_space!r}. Choose from: {choices}")

    return key, SOURCE_SPACES[key]


def _as_source_origin(source_origin: str | Origin) -> tuple[str, Origin]:
    if isinstance(source_origin, Origin):
        for name, enum_value in SOURCE_ORIGINS.items():
            if source_origin == enum_value:
                return name, enum_value

    key = str(source_origin).strip().lower()
    if key not in SOURCE_ORIGINS:
        choices = ", ".join(SOURCE_ORIGINS)
        raise ValueError(f"Unknown source origin {source_origin!r}. Choose from: {choices}")

    return key, SOURCE_ORIGINS[key]


def source_to_rasmm_affine(
    source_space: str | Space,
    source_origin: str | Origin,
    reference_affine: np.ndarray,
    reference_voxel_sizes: tuple[float, float, float] | np.ndarray,
) -> np.ndarray:
    """Return the affine represented by DIPY's source-to-RASMM conversion."""

    _, space = _as_source_space(source_space)
    _, origin = _as_source_origin(source_origin)

    reference_affine = np.asarray(reference_affine, dtype=float)
    voxel_sizes = np.asarray(reference_voxel_sizes, dtype=float)

    if reference_affine.shape != (4, 4):
        raise ValueError("reference_affine must have shape (4, 4)")

    if voxel_sizes.shape != (3,) or np.any(voxel_sizes <= 0):
        raise ValueError("reference_voxel_sizes must contain three positive values")

    if space == Space.RASMM:
        transform = np.eye(4, dtype=float)
    elif space == Space.LPSMM:
        transform = np.diag([-1.0, -1.0, 1.0, 1.0])
    elif space == Space.VOX:
        transform = reference_affine.copy()
    elif space == Space.VOXMM:
        voxmm_to_vox = np.diag(
            [1.0 / voxel_sizes[0], 1.0 / voxel_sizes[1], 1.0 / voxel_sizes[2], 1.0]
        )
        transform = reference_affine @ voxmm_to_vox
    else:
        raise ValueError(f"Unsupported source space: {space}")

    if origin == Origin.TRACKVIS:
        origin_shift_rasmm = reference_affine[:3, :3] @ np.full(3, -0.5)
        transform[:3, 3] += origin_shift_rasmm

    return transform


def streamline_bounds(
    streamlines: tuple[np.ndarray, ...],
) -> tuple[np.ndarray, np.ndarray]:
    lower = np.full(3, np.inf)
    upper = np.full(3, -np.inf)

    for streamline in streamlines:
        lower = np.minimum(lower, streamline.min(axis=0))
        upper = np.maximum(upper, streamline.max(axis=0))

    return lower, upper


def reference_world_bounds(
    affine: np.ndarray,
    dimensions: tuple[int, int, int],
) -> tuple[np.ndarray, np.ndarray]:
    """Return axis-aligned world bounds for the outer faces of a reference image."""

    edge_coordinates = tuple((-0.5, float(size) - 0.5) for size in dimensions)
    voxel_corners = np.asarray(list(product(*edge_coordinates)), dtype=float)
    world_corners = apply_affine(affine, voxel_corners)
    return world_corners.min(axis=0), world_corners.max(axis=0)


def point_fraction_inside_reference(
    streamlines: tuple[np.ndarray, ...],
    affine: np.ndarray,
    dimensions: tuple[int, int, int],
) -> float:
    """Return the fraction of RASMM tract points inside the reference image."""

    inverse_affine = np.linalg.inv(np.asarray(affine, dtype=float))
    lower = np.full(3, -0.5)
    upper = np.asarray(dimensions, dtype=float) - 0.5
    inside_count = 0
    point_count = 0

    for streamline in streamlines:
        voxel_points = apply_affine(inverse_affine, streamline)
        inside = np.all((voxel_points >= lower) & (voxel_points <= upper), axis=1)
        inside_count += int(inside.sum())
        point_count += len(streamline)

    if point_count == 0:
        return 0.0

    return inside_count / point_count


def _sample_streamline_points(
    streamlines: tuple[np.ndarray, ...],
    max_points: int = AUTO_DETECTION_MAX_POINTS,
) -> np.ndarray:
    if max_points < 1:
        raise ValueError("max_points must be positive")

    streamline_count = len(streamlines)
    selected_count = min(streamline_count, max(1, max_points // 4))
    streamline_indices = np.linspace(
        0,
        streamline_count - 1,
        num=selected_count,
        dtype=int,
    )
    points_per_streamline = max(1, max_points // selected_count)
    samples = []

    for index in streamline_indices:
        streamline = streamlines[index]
        sample_count = min(len(streamline), points_per_streamline)
        point_indices = np.linspace(
            0,
            len(streamline) - 1,
            num=sample_count,
            dtype=int,
        )
        samples.append(streamline[point_indices])

    return np.concatenate(samples, axis=0)


@lru_cache(maxsize=4)
def _load_reference_support(reference_path: str) -> ReferenceSupport:
    image = nib.load(reference_path)
    data = np.asarray(image.dataobj, dtype=np.float32)

    if data.ndim != 3:
        raise ValueError(
            "Automatic tract coordinate detection requires a 3D reference image; "
            f"received shape {data.shape}."
        )

    affine = np.asarray(image.affine, dtype=float)
    inverse_affine = np.linalg.inv(affine)
    dimensions = tuple(int(value) for value in data.shape)
    voxel_sizes = tuple(float(value) for value in image.header.get_zooms()[:3])

    finite = np.isfinite(data)
    absolute = np.abs(data)
    nonzero = absolute[finite & (absolute > 0)]

    if nonzero.size:
        threshold = max(
            float(np.percentile(nonzero, 1.0)) * 0.25,
            float(np.finfo(np.float32).eps),
        )
        foreground = finite & (absolute > threshold)
    else:
        foreground = finite

    foreground_distance_mm = distance_transform_edt(
        foreground,
        sampling=voxel_sizes,
    ).astype(np.float32)

    return ReferenceSupport(
        affine=affine,
        inverse_affine=inverse_affine,
        dimensions=dimensions,
        voxel_sizes=voxel_sizes,
        foreground=foreground,
        foreground_distance_mm=foreground_distance_mm,
    )


def _score_coordinate_candidate(
    sampled_raw_points: np.ndarray,
    transform: np.ndarray,
    support: ReferenceSupport,
) -> float:
    world_points = apply_affine(transform, sampled_raw_points)
    voxel_points = apply_affine(support.inverse_affine, world_points)
    nearest_voxels = np.rint(voxel_points).astype(np.int64)
    dimensions = np.asarray(support.dimensions, dtype=np.int64)
    inside = np.all(
        (nearest_voxels >= 0) & (nearest_voxels < dimensions),
        axis=1,
    )

    inside_fraction = float(inside.mean())
    if not inside.any():
        return 0.0

    in_bounds_voxels = nearest_voxels[inside]
    index = tuple(in_bounds_voxels.T)
    foreground_count = int(support.foreground[index].sum())
    foreground_fraction = foreground_count / len(sampled_raw_points)

    depth = np.zeros(len(sampled_raw_points), dtype=np.float32)
    depth[inside] = support.foreground_distance_mm[index]
    depth_score = float(
        np.clip(
            depth / AUTO_DETECTION_DEPTH_SCALE_MM,
            0.0,
            1.0,
        ).mean()
    )

    return 0.40 * inside_fraction + 0.45 * foreground_fraction + 0.15 * depth_score


def detect_source_coordinates(
    streamlines: tuple[np.ndarray, ...],
    reference_path: str | Path,
    reference_affine: np.ndarray,
    reference_voxel_sizes: tuple[float, float, float],
) -> CoordinateDetection:
    """Select a source coordinate interpretation using the reference image."""

    support = _load_reference_support(str(Path(reference_path).resolve()))
    sampled_points = _sample_streamline_points(streamlines)
    scored_candidates = []

    for source_space, source_origin in AUTO_DETECTION_CANDIDATES:
        transform = source_to_rasmm_affine(
            source_space,
            source_origin,
            reference_affine,
            reference_voxel_sizes,
        )
        score = _score_coordinate_candidate(
            sampled_points,
            transform,
            support,
        )
        scored_candidates.append(
            (
                source_space,
                source_origin,
                transform,
                score,
            )
        )

    scored_candidates.sort(key=lambda item: item[3], reverse=True)
    best_space, best_origin, best_transform, best_score = scored_candidates[0]

    best_score_by_space = {}
    for source_space, _source_origin, _transform, score in scored_candidates:
        best_score_by_space[source_space] = max(
            score,
            best_score_by_space.get(source_space, -np.inf),
        )
    space_scores = sorted(best_score_by_space.values(), reverse=True)
    score_gap = space_scores[0] - space_scores[1]

    if score_gap >= 0.10:
        confidence = "high"
    elif score_gap >= 0.02:
        confidence = "moderate"
    else:
        confidence = "low"

    candidate_scores = tuple(
        (f"{space}/{origin}", float(score))
        for space, origin, _transform, score in scored_candidates
    )

    if best_score <= 0.0:
        raise ValueError(
            "No tested coordinate interpretation overlaps the reference image."
        )

    return CoordinateDetection(
        source_space=best_space,
        source_origin=best_origin,
        transform=best_transform,
        confidence=confidence,
        candidate_scores=candidate_scores,
    )


def _transform_streamlines(
    streamlines: tuple[np.ndarray, ...],
    transform: np.ndarray,
) -> tuple[np.ndarray, ...]:
    if np.allclose(transform, np.eye(4), atol=1e-7):
        return streamlines

    return tuple(
        np.asarray(apply_affine(transform, streamline), dtype=np.float32)
        for streamline in streamlines
    )


def _validate_tractogram_path(tractogram_path: str | Path) -> tuple[Path, str]:
    path = Path(tractogram_path).expanduser().resolve()

    if not path.is_file():
        raise FileNotFoundError(f"Tractogram does not exist: {path}")

    extension = tractogram_extension(path)

    if extension.endswith(".gz"):
        raise ValueError(
            "Compressed tractograms require a dedicated adapter. "
            f"Decompress this file before loading: {path.name}"
        )

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported tractogram extension {extension!r}. Supported: {supported}")

    return path, extension


def _resolve_reference(
    tractogram_path: Path,
    extension: str,
    reference_path: str | Path | None,
) -> tuple[str | Path, str]:
    if reference_path is None:
        if extension in {".trk", ".trx"}:
            return "same", f"embedded geometry from {tractogram_path.name}"

        raise ValueError(f"{extension} requires a corresponding reference NIfTI.")

    path = Path(reference_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Reference image does not exist: {path}")

    return path, str(path)


def _extract_streamlines(stateful: object, path: Path) -> tuple[np.ndarray, ...]:
    streamlines = tuple(
        np.asarray(streamline, dtype=np.float32)
        for streamline in stateful.streamlines
        if len(streamline) >= 2
    )

    if not streamlines:
        raise ValueError(f"No valid streamlines were found in {path}")

    if any(streamline.ndim != 2 or streamline.shape[1] != 3 for streamline in streamlines):
        raise ValueError("Every streamline must have shape (number_of_points, 3)")

    if any(not np.isfinite(streamline).all() for streamline in streamlines):
        raise ValueError("The tractogram contains non-finite coordinates")

    return streamlines


def load_tract_layer(
    tractogram_path: str | Path,
    reference_path: str | Path | None = None,
    *,
    name: str | None = None,
    min_reference_overlap: float = 0.80,
) -> TractLayer:
    """Load, automatically normalize, and inspect a tract layer in RASMM."""

    if not 0.0 <= min_reference_overlap <= 1.0:
        raise ValueError("min_reference_overlap must be between 0 and 1")

    path, extension = _validate_tractogram_path(tractogram_path)
    reference, reference_description = _resolve_reference(path, extension, reference_path)

    if extension in SELF_DESCRIBING_SPATIAL_EXTENSIONS:
        stateful = load_tractogram(
            str(path),
            str(reference),
            to_space=Space.RASMM,
            to_origin=Origin.NIFTI,
            bbox_valid_check=False,
        )
        detection_method = "embedded format metadata"
    else:
        stateful = load_tractogram(
            str(path),
            str(reference),
            to_space=Space.RASMM,
            to_origin=Origin.NIFTI,
            bbox_valid_check=False,
            from_space=Space.RASMM,
            from_origin=Origin.NIFTI,
        )
        detection_method = "automatic reference-image scoring"

    if stateful is False or stateful is None:
        raise RuntimeError(f"DIPY could not load {path}")

    raw_streamlines = _extract_streamlines(stateful, path)
    affine, dimensions, voxel_sizes, _voxel_order = stateful.space_attributes
    affine = np.asarray(affine, dtype=float)
    dimensions = tuple(int(value) for value in dimensions)
    voxel_sizes = tuple(float(value) for value in voxel_sizes)

    if extension in SELF_DESCRIBING_SPATIAL_EXTENSIONS:
        source_space_name = "RASMM"
        source_origin_name = "NIFTI"
        transform = np.eye(4)
        confidence = "metadata"
        candidate_scores = ()
        streamlines = raw_streamlines
    else:
        if not isinstance(reference, Path):
            raise ValueError(
                "Automatic coordinate detection requires an explicit reference NIfTI."
            )
        detection = detect_source_coordinates(
            raw_streamlines,
            reference,
            affine,
            voxel_sizes,
        )
        source_space_name = detection.source_space.upper()
        source_origin_name = detection.source_origin.upper()
        transform = detection.transform
        confidence = detection.confidence
        candidate_scores = detection.candidate_scores
        streamlines = _transform_streamlines(raw_streamlines, transform)

    tract_min, tract_max = streamline_bounds(streamlines)
    reference_min, reference_max = reference_world_bounds(affine, dimensions)
    bounding_boxes_overlap = bool(
        np.all(tract_max >= reference_min) and np.all(tract_min <= reference_max)
    )
    fraction_inside = point_fraction_inside_reference(streamlines, affine, dimensions)

    warnings = []
    if confidence == "low":
        warnings.append(
            "The best automatic coordinate interpretation had a small score advantage."
        )
    if not bounding_boxes_overlap:
        warnings.append("Tract and reference world-space bounding boxes do not overlap.")
    if fraction_inside < min_reference_overlap:
        warnings.append(
            f"Only {fraction_inside:.1%} of tract points lie inside the reference image."
        )

    orientation = tuple(str(value) for value in nib.aff2axcodes(affine))

    inspection = TractInspection(
        filename=path.name,
        detected_format=extension,
        streamline_count=len(streamlines),
        point_count=sum(len(streamline) for streamline in streamlines),
        coordinate_detection=detection_method,
        detection_confidence=confidence,
        candidate_scores=candidate_scores,
        source_space=source_space_name,
        source_origin=source_origin_name,
        output_space="RASMM",
        source_to_rasmm=tuple(tuple(float(value) for value in row) for row in transform),
        world_bounds_min=tuple(float(value) for value in tract_min),
        world_bounds_max=tuple(float(value) for value in tract_max),
        reference=reference_description,
        reference_dimensions=dimensions,
        reference_voxel_sizes=voxel_sizes,
        reference_orientation=orientation,
        reference_world_bounds_min=tuple(float(value) for value in reference_min),
        reference_world_bounds_max=tuple(float(value) for value in reference_max),
        bounding_boxes_overlap=bounding_boxes_overlap,
        point_fraction_inside_reference=fraction_inside,
        warnings=tuple(warnings),
    )

    return TractLayer(
        name=name or path.stem,
        path=path,
        streamlines=streamlines,
        inspection=inspection,
    )


def load_streamlines_rasmm(
    tractogram_path: str | Path,
    reference_path: str | Path | None = None,
) -> tuple[np.ndarray, ...]:
    """Compatibility wrapper returning automatically normalized RASMM streamlines."""

    layer = load_tract_layer(
        tractogram_path,
        reference_path=reference_path,
    )
    return layer.streamlines
