import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / "demo_data" / "cache"

os.environ["DIPY_HOME"] = str(CACHE_ROOT)

from dipy.data.fetcher import fetch_file_formats  # noqa: E402

EXPECTED_FILES = (
    "cc_m_sub.trk",
    "laf_m_sub.tck",
    "lpt_m_sub.fib",
    "raf_m_sub.vtk",
    "rpt_m_sub.dpy",
    "template0.nii.gz",
)


def main() -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    fetch_file_formats()

    dataset_directory = CACHE_ROOT / "bundle_file_formats_example"
    missing = [
        filename
        for filename in EXPECTED_FILES
        if not (dataset_directory / filename).is_file()
    ]

    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(f"Demo-data download is incomplete: {missing_text}")

    print(f"Demo data ready: {dataset_directory}")


if __name__ == "__main__":
    main()
