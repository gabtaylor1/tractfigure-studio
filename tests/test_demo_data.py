from pathlib import Path

import pytest

from tractfigure.io import load_streamlines_rasmm, streamline_bounds

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET = PROJECT_ROOT / "demo_data" / "cache" / "bundle_file_formats_example"
REFERENCE = DATASET / "template0.nii.gz"

TRACTOGRAMS = (
    "cc_m_sub.trk",
    "laf_m_sub.tck",
    "lpt_m_sub.fib",
    "raf_m_sub.vtk",
    "rpt_m_sub.dpy",
)


@pytest.mark.integration
@pytest.mark.parametrize("filename", TRACTOGRAMS)
def test_demo_tractogram_loads(filename: str) -> None:
    tractogram = DATASET / filename

    if not REFERENCE.is_file() or not tractogram.is_file():
        pytest.skip("Run scripts/fetch_demo_data.py to enable integration tests")

    streamlines = load_streamlines_rasmm(
        tractogram,
        reference_path=REFERENCE,
    )
    lower, upper = streamline_bounds(streamlines)

    assert len(streamlines) > 0
    assert (upper > lower).any()
