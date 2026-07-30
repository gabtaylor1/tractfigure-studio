import argparse
from itertools import cycle
from pathlib import Path

import nibabel as nib
import numpy as np
import pyvista as pv

from tractfigure.io import load_streamlines_rasmm
from tractfigure.vtk_conversion import nifti_to_image_data, streamlines_to_polydata

DEFAULT_COLORS = (
    "#E64B35",
    "#4DBBD5",
    "#00A087",
    "#3C5488",
    "#F39B7F",
    "#8491B4",
    "#91D1C2",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("tractograms", nargs="+", type=Path)
    parser.add_argument("--max-streamlines", type=int, default=5000)
    parser.add_argument("--line-width", type=float, default=2.0)
    parser.add_argument("--tract-opacity", type=float, default=0.9)
    parser.add_argument("--slice-opacity", type=float, default=0.65)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    image = nib.load(args.reference)
    image_grid = nifti_to_image_data(image)

    plotter = pv.Plotter(window_size=(1400, 1000))
    plotter.set_background("#101216")
    plotter.enable_anti_aliasing("ssaa")

    intensity = image_grid.point_data["intensity"]
    valid = intensity[np.isfinite(intensity)]

    if valid.size:
        lower, upper = np.percentile(valid, [2, 98])
    else:
        lower, upper = 0.0, 1.0

    for normal in ("x", "y", "z"):
        image_slice = image_grid.slice(
            normal=normal,
            origin=image_grid.center,
        )
        plotter.add_mesh(
            image_slice,
            scalars="intensity",
            cmap="gray",
            clim=(float(lower), float(upper)),
            opacity=args.slice_opacity,
            show_scalar_bar=False,
        )

    colors = cycle(DEFAULT_COLORS)

    for tractogram_path, color in zip(args.tractograms, colors, strict=False):
        streamlines = load_streamlines_rasmm(
            tractogram_path,
            reference_path=args.reference,
        )
        polydata = streamlines_to_polydata(
            streamlines,
            max_streamlines=args.max_streamlines,
        )

        plotter.add_mesh(
            polydata,
            color=color,
            opacity=args.tract_opacity,
            line_width=args.line_width,
            render_lines_as_tubes=True,
            label=tractogram_path.stem,
        )

    plotter.add_legend(
        bcolor="#101216",
        face="circle",
        size=(0.22, 0.18),
    )
    plotter.show_axes()
    plotter.view_isometric()
    plotter.reset_camera()
    plotter.show()


if __name__ == "__main__":
    main()
