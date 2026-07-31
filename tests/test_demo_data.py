import json
from pathlib import Path

import numpy as np
import pytest

from tractfigure.io import load_tract_layer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PROJECT_ROOT / "demo_data" / "data_inventory.json"


def load_inventory() -> dict:
    assert INVENTORY_PATH.is_file(), "Run scripts/fetch_demo_data.py"
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def project_path(value: str) -> Path:
    return (PROJECT_ROOT / value).resolve()


@pytest.mark.integration
@pytest.mark.parametrize("tractogram_index", range(5))
def test_five_format_tractograms(tractogram_index: int) -> None:
    inventory = load_inventory()
    reference = project_path(inventory["file_formats"]["reference"])
    tractograms = inventory["file_formats"]["tractograms"]
    assert len(tractograms) == 5
    path = project_path(tractograms[tractogram_index])

    layer = load_tract_layer(path, reference_path=reference)
    inspection = layer.inspection

    assert layer.streamlines
    assert all(np.isfinite(streamline).all() for streamline in layer.streamlines)
    assert inspection.output_space == "RASMM"
    assert inspection.bounding_boxes_overlap, inspection.format_report()
    assert inspection.point_fraction_inside_reference > 0, inspection.format_report()

    if inspection.coordinate_detection == "automatic reference-image scoring":
        selected = f"{inspection.source_space.lower()}/{inspection.source_origin.lower()}"
        assert selected == inspection.candidate_scores[0][0]
        assert inspection.candidate_scores[0][1] >= 0.80, inspection.format_report()


@pytest.mark.integration
def test_hcp842_inventory_represents_80_anatomical_bundles() -> None:
    inventory = load_inventory()
    bundles = [project_path(value) for value in inventory["hcp842"]["bundles"]]
    assert len(bundles) == 79
    assert inventory["hcp842"].get("anatomical_bundle_count", 80) == 80
    assert inventory["hcp842"].get("tractogram_file_count", len(bundles)) == 79
    assert all(path.is_file() and path.stat().st_size > 0 for path in bundles)


@pytest.mark.integration
def test_verification_report_exists() -> None:
    report = PROJECT_ROOT / "demo_data" / "verification_report.json"
    assert report.is_file(), "Run scripts/verify_demo_data.py"
    contents = json.loads(report.read_text(encoding="utf-8"))
    assert len(contents["file_formats"]) == 5
    assert len(contents["hcp842"]["bundles"]) == 79
    assert contents["hcp842"]["anatomical_bundle_count"] == 80
    assert contents["hcp842"]["tractogram_file_count"] == 79
