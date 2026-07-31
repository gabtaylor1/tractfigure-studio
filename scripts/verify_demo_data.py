from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / "demo_data" / "cache"
INVENTORY_PATH = PROJECT_ROOT / "demo_data" / "data_inventory.json"
REPORT_PATH = PROJECT_ROOT / "demo_data" / "verification_report.json"

os.environ["DIPY_HOME"] = str(CACHE_ROOT)

from tractfigure.io import load_tract_layer  # noqa: E402

EXPECTED_FORMAT_NAMES = {
    "cc_m_sub.trk",
    "laf_m_sub.tck",
    "lpt_m_sub.fib",
    "raf_m_sub.vtk",
    "rpt_m_sub.dpy",
}
HCP842_ANATOMICAL_BUNDLE_COUNT = 80
HCP842_TRACTOGRAM_FILE_COUNT = 79
AUTOMATIC_MIN_REFERENCE_SCORE = 0.80


def project_path(value: str) -> Path:
    path = (PROJECT_ROOT / value).resolve()

    if not path.is_relative_to(PROJECT_ROOT):
        raise ValueError(f"Inventory path leaves the project directory: {value}")

    return path


def require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Required data file is missing: {path}")

    if path.stat().st_size == 0:
        raise ValueError(f"Required data file is empty: {path}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def verify_image(path: Path) -> dict[str, Any]:
    require_file(path)
    image = nib.load(path)
    data = np.asarray(image.dataobj)
    affine = np.asarray(image.affine, dtype=float)

    if data.ndim != 3:
        raise ValueError(f"Expected a 3D NIfTI image: {path} has shape {data.shape}")

    if not np.isfinite(data).all():
        raise ValueError(f"NIfTI contains non-finite values: {path}")

    if not np.isfinite(affine).all() or abs(np.linalg.det(affine[:3, :3])) < 1e-10:
        raise ValueError(f"NIfTI affine is invalid or singular: {path}")

    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": sha256(path),
        "shape": [int(value) for value in data.shape],
        "voxel_sizes": [float(value) for value in image.header.get_zooms()[:3]],
        "orientation": list(nib.aff2axcodes(affine)),
        "affine": affine.tolist(),
    }


def verify_tractogram(path: Path, reference: Path) -> dict[str, Any]:
    require_file(path)
    layer = load_tract_layer(path, reference_path=reference)
    inspection = layer.inspection

    if not layer.streamlines:
        raise ValueError(f"No streamlines were loaded: {path}")

    if any(not np.isfinite(streamline).all() for streamline in layer.streamlines):
        raise ValueError(f"Tractogram contains non-finite coordinates: {path}")

    if inspection.output_space != "RASMM":
        raise ValueError(f"Tractogram did not normalize to RASMM: {path}")

    if not inspection.bounding_boxes_overlap:
        raise ValueError(f"Tractogram and reference bounds do not overlap: {path}")

    if inspection.point_fraction_inside_reference <= 0:
        raise ValueError(f"No tract points fall within the reference bounds: {path}")

    if inspection.coordinate_detection == "automatic reference-image scoring":
        if not inspection.candidate_scores:
            raise ValueError(
                "Automatic coordinate detection did not report candidate scores:\n"
                + inspection.format_report()
            )

        selected = f"{inspection.source_space.lower()}/{inspection.source_origin.lower()}"
        best_candidate, best_score = inspection.candidate_scores[0]

        if selected != best_candidate:
            raise ValueError(
                "Automatic coordinate detection did not select its highest-scoring candidate:\n"
                + inspection.format_report()
            )

        if best_score < AUTOMATIC_MIN_REFERENCE_SCORE:
            raise ValueError(
                "Automatic coordinate detection had inadequate absolute reference support:\n"
                + inspection.format_report()
            )

    return {
        "path": path.relative_to(PROJECT_ROOT).as_posix(),
        "sha256": sha256(path),
        "streamline_count": inspection.streamline_count,
        "point_count": inspection.point_count,
        "source_space": inspection.source_space,
        "source_origin": inspection.source_origin,
        "output_space": inspection.output_space,
        "coordinate_detection": inspection.coordinate_detection,
        "detection_confidence": inspection.detection_confidence,
        "point_fraction_inside_reference": inspection.point_fraction_inside_reference,
        "bounding_boxes_overlap": inspection.bounding_boxes_overlap,
        "world_bounds_min": list(inspection.world_bounds_min),
        "world_bounds_max": list(inspection.world_bounds_max),
        "warnings": list(inspection.warnings),
    }


def main() -> None:
    require_file(INVENTORY_PATH)
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    reference = project_path(inventory["file_formats"]["reference"])
    format_paths = [project_path(value) for value in inventory["file_formats"]["tractograms"]]
    hcp_whole_brain = project_path(inventory["hcp842"]["whole_brain"])
    hcp_bundle_paths = [project_path(value) for value in inventory["hcp842"]["bundles"]]
    mni_t1 = project_path(inventory["mni2009a"]["t1"])

    format_names = {path.name for path in format_paths}
    if format_names != EXPECTED_FORMAT_NAMES:
        raise ValueError(
            "Unexpected five-format dataset contents: "
            f"expected {sorted(EXPECTED_FORMAT_NAMES)}, received {sorted(format_names)}"
        )

    if len(hcp_bundle_paths) != HCP842_TRACTOGRAM_FILE_COUNT:
        raise ValueError(
            "Unexpected HCP842 atlas contents: "
            f"expected {HCP842_TRACTOGRAM_FILE_COUNT} tractogram files representing "
            f"{HCP842_ANATOMICAL_BUNDLE_COUNT} anatomical bundles; "
            f"received {len(hcp_bundle_paths)} tractogram files"
        )

    require_file(hcp_whole_brain)
    for path in hcp_bundle_paths:
        require_file(path)

    report = {
        "reference": verify_image(reference),
        "file_formats": [verify_tractogram(path, reference) for path in format_paths],
        "hcp842": {
            "anatomical_bundle_count": HCP842_ANATOMICAL_BUNDLE_COUNT,
            "tractogram_file_count": len(hcp_bundle_paths),
            "whole_brain": {
                "path": hcp_whole_brain.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": sha256(hcp_whole_brain),
            },
            "bundles": [
                {
                    "path": path.relative_to(PROJECT_ROOT).as_posix(),
                    "sha256": sha256(path),
                }
                for path in hcp_bundle_paths
            ],
        },
        "mni2009a_t1": verify_image(mni_t1),
    }

    REPORT_PATH.write_text(
        json.dumps(report, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Demo-data verification passed: {REPORT_PATH}")


if __name__ == "__main__":
    main()
