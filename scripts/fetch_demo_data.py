from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import nibabel as nib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / "demo_data" / "cache"
INVENTORY_PATH = PROJECT_ROOT / "demo_data" / "data_inventory.json"

HCP842_ANATOMICAL_BUNDLE_COUNT = 80
HCP842_TRACTOGRAM_FILE_COUNT = 79

os.environ["DIPY_HOME"] = str(CACHE_ROOT)

from dipy.data.fetcher import (  # noqa: E402
    fetch_bundle_atlas_hcp842,
    fetch_file_formats,
    fetch_mni_template,
    get_bundle_atlas_hcp842,
    get_file_formats,
    read_mni_template,
)


def relative(path: str | Path) -> str:
    return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()


def resolve_bundle_paths(path_or_pattern: str | Path) -> list[Path]:
    text = str(path_or_pattern)
    candidate = Path(text)

    if candidate.is_dir():
        paths = sorted(candidate.glob("*.trk"))
    elif any(character in text for character in "*?[]"):
        paths = sorted(Path(path) for path in glob.glob(text))
    elif candidate.is_file():
        paths = [candidate]
    else:
        paths = []

    return [path.resolve() for path in paths]


def main() -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    fetch_file_formats()
    fetch_bundle_atlas_hcp842()
    fetch_mni_template()

    format_bundles, format_reference = get_file_formats()
    hcp_whole_brain, hcp_bundle_pattern = get_bundle_atlas_hcp842(size=80)
    hcp_bundles = resolve_bundle_paths(hcp_bundle_pattern)

    if len(hcp_bundles) != HCP842_TRACTOGRAM_FILE_COUNT:
        raise RuntimeError(
            "Unexpected HCP842 atlas contents: "
            f"expected {HCP842_TRACTOGRAM_FILE_COUNT} tractogram files representing "
            f"{HCP842_ANATOMICAL_BUNDLE_COUNT} anatomical bundles; "
            f"received {len(hcp_bundles)} tractogram files"
        )

    mni_result = read_mni_template(version="a", contrast="T1")
    mni_image = mni_result[0] if isinstance(mni_result, (list, tuple)) else mni_result
    mni_path = CACHE_ROOT / "mni_icbm152_2009a_t1.nii.gz"
    nib.save(mni_image, mni_path)

    inventory = {
        "file_formats": {
            "reference": relative(format_reference),
            "tractograms": [relative(path) for path in format_bundles],
        },
        "hcp842": {
            "whole_brain": relative(hcp_whole_brain),
            "bundles": [relative(path) for path in hcp_bundles],
            "anatomical_bundle_count": HCP842_ANATOMICAL_BUNDLE_COUNT,
            "tractogram_file_count": len(hcp_bundles),
        },
        "mni2009a": {
            "t1": relative(mni_path),
        },
    }

    INVENTORY_PATH.write_text(
        json.dumps(inventory, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        "Demo data ready: "
        f"{len(format_bundles)} format examples, "
        f"{len(hcp_bundles)} HCP842 tractogram files representing "
        f"{HCP842_ANATOMICAL_BUNDLE_COUNT} anatomical bundles, and MNI2009a T1"
    )


if __name__ == "__main__":
    main()
