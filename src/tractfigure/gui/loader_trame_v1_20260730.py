from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Any

import nibabel as nib
import pyvista as pv
from trame.app import get_server
from trame.ui.vuetify3 import SinglePageLayout
from trame.widgets import client
from trame.widgets import vuetify3 as v3

from tractfigure.gui.app_trame_v1_20260730 import load_recipe, scene_from_inputs
from tractfigure.io import SUPPORTED_EXTENSIONS
from tractfigure.renderer_trame_v1_20260730 import SceneRenderer
from tractfigure.scene_state_v1_20260730 import SceneState

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_RECIPE_PATH = PROJECT_ROOT / "examples" / "recipes" / "five_bundle_trame_v1_20260730.json"
DEMO_TEMPLATE_PATH = (
    PROJECT_ROOT / "demo_data" / "cache" / "mni_template" / "mni_icbm152_t1_tal_nlin_asym_09a.nii"
)

# No extension filters: Tk/native file dialogs (especially on macOS) handle
# compound extensions like ".nii.gz" unreliably regardless of exact pattern
# syntax, sometimes hiding matching files under a restrictive filter. Showing
# everything and relying on the loader's own validation (which gives a clear
# error for the wrong kind of file) is simpler and always correct.
ALL_FILES_FILETYPES = [("All files", "*.*")]


def _activate_process_frontmost() -> None:
    """macOS: raise this background process above other apps (e.g. Chrome).

    A plain `python -m ...` process has no app-level focus the way a
    double-clicked .app does, so its dialogs can open behind whatever else is
    frontmost. This asks System Events to make our own process frontmost
    right before showing a dialog. Best-effort - failures are ignored.
    """

    if sys.platform != "darwin":
        return

    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                (
                    'tell application "System Events" to set frontmost of '
                    f"(first process whose unix id is {os.getpid()}) to true"
                ),
            ],
            check=False,
            capture_output=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _initial_directory(path_value: str) -> str:
    """Pick a starting directory for a native dialog.

    Prefers the directory of the given (already-typed/selected) path when
    it resolves to something real, so re-opening Browse continues from
    wherever you're already working; falls back to the project root
    otherwise, rather than whatever directory the loader happened to be
    launched from.
    """

    candidate = path_value.strip()

    if candidate:
        path = Path(candidate).expanduser().resolve()
        directory = path if path.is_dir() else path.parent

        if directory.is_dir():
            return str(directory)

    return str(PROJECT_ROOT)


def _run_native_dialog(dialog_fn, **kwargs):
    """Run a tkinter file/directory dialog on the server's own desktop.

    This app's Trame server and browser tab always run on the same machine,
    so a native OS picker here (rather than a browser <input type=file>,
    which never exposes a real filesystem path) gives a real absolute path
    usable by the rest of the loader.
    """

    _activate_process_frontmost()

    root = tk.Tk()
    root.withdraw()
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()

    try:
        return dialog_fn(**kwargs)
    finally:
        root.destroy()


def read_registration_template(template_path: Path) -> nib.spatialimages.SpatialImage:
    """Load a registration template image for later use.

    Registration itself (estimating and applying a moving-to-fixed
    transform) is not implemented yet - this only validates that the
    selected template file exists and is a loadable image, so the path can
    be wired into the actual registration step later.
    """

    template_path = Path(template_path).expanduser().resolve()
    if not template_path.is_file():
        raise FileNotFoundError(f"Template image does not exist: {template_path}")

    return nib.load(str(template_path))


def _expand_tractogram_entry(value: str) -> list[Path]:
    """Resolve one loader tractogram entry, expanding a folder into its files."""

    path = Path(value).expanduser()

    if path.is_dir():
        matches = sorted(
            child
            for child in path.iterdir()
            if child.is_file() and child.suffix.lower() in SUPPORTED_EXTENSIONS
        )

        if not matches:
            supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise ValueError(
                f"Folder has no supported tractogram files ({supported}): {path}"
            )

        return matches

    return [path]


def resolve_loader_scene(
    *,
    mode: str,
    recipe_path: str,
    reference_path: str,
    tractogram_paths: list[str],
    template_path: str,
) -> SceneState:
    """Build a SceneState from loader fields."""

    if mode == "recipe":
        if not recipe_path.strip():
            raise ValueError("Choose a recipe file")
        scene = load_recipe(Path(recipe_path.strip()))
    else:
        if not reference_path.strip():
            raise ValueError("Choose a reference image")

        cleaned_tractograms = [value.strip() for value in tractogram_paths if value.strip()]
        if not cleaned_tractograms:
            raise ValueError("Add at least one tractogram")

        expanded_tractograms: list[Path] = []
        for value in cleaned_tractograms:
            expanded_tractograms.extend(_expand_tractogram_entry(value))

        scene = scene_from_inputs(
            Path(reference_path.strip()),
            expanded_tractograms,
        )

    if template_path.strip():
        read_registration_template(Path(template_path.strip()))

    return scene


def find_free_port() -> int:
    """Return a port that is currently free to bind on localhost."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("localhost", 0))
        return probe.getsockname()[1]


async def wait_for_port(port: int, timeout: float = 90.0) -> bool:
    """Poll until something is accepting TCP connections on localhost:port."""

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout

    while loop.time() < deadline:
        try:
            with socket.create_connection(("localhost", port), timeout=0.5):
                return True
        except OSError:
            await asyncio.sleep(0.3)

    return False


def validate_and_stage_scene(scene: SceneState, output_directory: Path) -> Path:
    """Load the scene through the real renderer to validate it, then save a recipe."""

    output_directory = Path(output_directory).expanduser().resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    renderer = SceneRenderer()
    renderer.load_scene(scene)

    return renderer.save_scene(output_directory / "loader_recipe.json")


class LoaderController:
    def __init__(self, server: Any, args: argparse.Namespace) -> None:
        self.server = server
        self.state = server.state
        self.ctrl = server.controller
        self.args = args
        self.navigate_eval: client.JSEval | None = None

        self._initialize_state()
        self._register_controller_actions()

    def _initialize_state(self) -> None:
        state = self.state

        state.loader_mode = "recipe" if self.args.recipe else "individual"
        state.recipe_path = str(self.args.recipe) if self.args.recipe else ""
        state.reference_path = str(self.args.reference) if self.args.reference else ""
        state.tractogram_paths_text = "\n".join(str(path) for path in self.args.tractogram)
        state.template_path = str(self.args.template) if self.args.template else ""
        state.register_to_template = bool(self.args.template)
        state.output_directory = str(self.args.output_dir)
        state.status_message = ""
        state.status_type = "info"
        state.launching = False
        state.viewer_url = ""

    def _register_controller_actions(self) -> None:
        self.ctrl.load_demo_scene = self.load_demo_scene
        self.ctrl.use_demo_template = self.use_demo_template
        self.ctrl.browse_recipe = self.browse_recipe
        self.ctrl.browse_reference = self.browse_reference
        self.ctrl.browse_tractograms = self.browse_tractograms
        self.ctrl.browse_tractogram_folder = self.browse_tractogram_folder
        self.ctrl.browse_template = self.browse_template
        self.ctrl.browse_output_directory = self.browse_output_directory
        self.ctrl.launch = self.launch

    def _flush_state(self) -> None:
        flush = getattr(self.state, "flush", None)

        if callable(flush):
            flush()

    def load_demo_scene(self) -> None:
        self.state.loader_mode = "recipe"
        self.state.recipe_path = str(DEMO_RECIPE_PATH)
        self.state.status_message = "Demo recipe selected"
        self.state.status_type = "info"

    def use_demo_template(self) -> None:
        self.state.template_path = str(DEMO_TEMPLATE_PATH)
        self.state.register_to_template = True
        self.state.status_message = "Demo template selected"
        self.state.status_type = "info"

    def _last_tractogram_entry(self) -> str:
        lines = [line for line in self.state.tractogram_paths_text.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def browse_recipe(self) -> None:
        path = _run_native_dialog(
            filedialog.askopenfilename,
            title="Choose a recipe file",
            filetypes=ALL_FILES_FILETYPES,
            initialdir=_initial_directory(self.state.recipe_path),
        )
        if path:
            self.state.recipe_path = path

    def browse_reference(self) -> None:
        path = _run_native_dialog(
            filedialog.askopenfilename,
            title="Choose a reference image",
            filetypes=ALL_FILES_FILETYPES,
            initialdir=_initial_directory(self.state.reference_path),
        )
        if path:
            self.state.reference_path = path

    def browse_tractograms(self) -> None:
        paths = _run_native_dialog(
            filedialog.askopenfilenames,
            title="Choose tractogram files",
            filetypes=ALL_FILES_FILETYPES,
            initialdir=_initial_directory(self._last_tractogram_entry()),
        )
        if paths:
            existing = [
                line for line in self.state.tractogram_paths_text.splitlines() if line.strip()
            ]
            self.state.tractogram_paths_text = "\n".join([*existing, *paths])

    def browse_tractogram_folder(self) -> None:
        path = _run_native_dialog(
            filedialog.askdirectory,
            title="Choose a folder of tractogram files",
            initialdir=_initial_directory(self._last_tractogram_entry()),
        )
        if path:
            existing = [
                line for line in self.state.tractogram_paths_text.splitlines() if line.strip()
            ]
            self.state.tractogram_paths_text = "\n".join([*existing, path])

    def browse_template(self) -> None:
        path = _run_native_dialog(
            filedialog.askopenfilename,
            title="Choose a registration template",
            filetypes=ALL_FILES_FILETYPES,
            initialdir=_initial_directory(self.state.template_path),
        )
        if path:
            self.state.template_path = path

    def browse_output_directory(self) -> None:
        path = _run_native_dialog(
            filedialog.askdirectory,
            title="Choose an output directory",
            initialdir=_initial_directory(self.state.output_directory),
        )
        if path:
            self.state.output_directory = path

    async def launch(self) -> None:
        state = self.state
        state.launching = True
        state.status_message = "Loading scene..."
        state.status_type = "info"
        self._flush_state()

        try:
            output_directory = Path(state.output_directory).expanduser().resolve()
            template_path = state.template_path if state.register_to_template else ""

            scene = resolve_loader_scene(
                mode=state.loader_mode,
                recipe_path=state.recipe_path,
                reference_path=state.reference_path,
                tractogram_paths=state.tractogram_paths_text.splitlines(),
                template_path=template_path,
            )
            staged_path = validate_and_stage_scene(scene, output_directory)
        except Exception as error:
            state.status_message = f"{type(error).__name__}: {error}"
            state.status_type = "error"
            state.launching = False
            self._flush_state()
            return

        viewer_port = find_free_port()
        state.status_message = "Scene validated; starting viewer..."
        state.status_type = "info"
        self._flush_state()

        # Detach the viewer so it outlives this process (which exits shortly
        # after handing off) regardless of platform: start_new_session is
        # POSIX-only (a harmless no-op on Windows), so Windows instead gets
        # its own process-group flag to the same effect.
        detach_kwargs: dict[str, Any] = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if sys.platform == "win32"
            else {"start_new_session": True}
        )

        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tractfigure.gui.app_trame_v1_20260730",
                "--recipe",
                str(staged_path),
                "--output-dir",
                str(output_directory),
                "--app-port",
                str(viewer_port),
                "--no-browser",
            ],
            **detach_kwargs,
        )

        ready = await wait_for_port(viewer_port)

        if not ready:
            state.status_message = "Viewer did not start in time"
            state.status_type = "error"
            state.launching = False
            self._flush_state()
            return

        viewer_url = f"http://localhost:{viewer_port}/"
        state.viewer_url = viewer_url
        state.status_message = f"Viewer ready; opening {viewer_url}"
        state.status_type = "success"
        self._flush_state()

        self.navigate_eval.exec()

        await asyncio.sleep(1.5)
        os._exit(0)


def build_loader_ui(server: Any, controller: LoaderController) -> Any:
    ctrl = server.controller

    with SinglePageLayout(server) as layout:
        layout.title.set_text("TractFigure Studio")
        controller.navigate_eval = client.JSEval(exec="window.location.href = viewer_url;")

        with layout.content:
            with v3.VContainer(
                fluid=True,
                classes="fill-height d-flex align-center justify-center",
            ):
                with v3.VCard(width=640, classes="pa-4"):
                    v3.VCardTitle("Load a scene")

                    v3.VSwitch(
                        label="Load from recipe file",
                        v_model=("loader_mode", controller.state.loader_mode),
                        true_value="recipe",
                        false_value="individual",
                        hide_details=True,
                        density="compact",
                        classes="mb-2",
                    )

                    with v3.VContainer(
                        fluid=True,
                        classes="pa-0",
                        v_show="loader_mode === 'recipe'",
                    ):
                        with v3.VRow(classes="ma-0 align-center"):
                            with v3.VCol(cols=9, classes="pa-0 pr-2"):
                                v3.VTextField(
                                    label="Recipe JSON path",
                                    v_model=("recipe_path", controller.state.recipe_path),
                                    variant="outlined",
                                    density="compact",
                                    hide_details=True,
                                )
                            with v3.VCol(cols=3, classes="pa-0"):
                                v3.VBtn(
                                    "Browse...",
                                    click=ctrl.browse_recipe,
                                    size="small",
                                    variant="tonal",
                                )
                        v3.VBtn(
                            "Load demo scene",
                            prepend_icon="mdi-flask-outline",
                            click=ctrl.load_demo_scene,
                            size="small",
                            variant="tonal",
                            classes="mt-2",
                        )

                    with v3.VContainer(
                        fluid=True,
                        classes="pa-0",
                        v_show="loader_mode === 'individual'",
                    ):
                        with v3.VRow(classes="ma-0 align-center"):
                            with v3.VCol(cols=9, classes="pa-0 pr-2"):
                                v3.VTextField(
                                    label="Reference image (.nii/.nii.gz)",
                                    v_model=("reference_path", controller.state.reference_path),
                                    variant="outlined",
                                    density="compact",
                                    hide_details=True,
                                )
                            with v3.VCol(cols=3, classes="pa-0"):
                                v3.VBtn(
                                    "Browse...",
                                    click=ctrl.browse_reference,
                                    size="small",
                                    variant="tonal",
                                )

                        v3.VTextarea(
                            label="Tractograms (one file or folder per line)",
                            v_model=(
                                "tractogram_paths_text",
                                controller.state.tractogram_paths_text,
                            ),
                            variant="outlined",
                            density="compact",
                            hide_details=True,
                            rows=3,
                            auto_grow=True,
                            classes="mt-2",
                        )
                        v3.VBtn(
                            "Browse files...",
                            click=ctrl.browse_tractograms,
                            size="small",
                            variant="tonal",
                            classes="mt-2 mr-2",
                        )
                        v3.VBtn(
                            "Browse folder...",
                            click=ctrl.browse_tractogram_folder,
                            size="small",
                            variant="tonal",
                            classes="mt-2",
                        )

                    v3.VDivider(classes="my-3")
                    v3.VCardTitle("Registration template (optional)", classes="pl-0")

                    v3.VSwitch(
                        label="Select a registration template",
                        v_model=(
                            "register_to_template",
                            controller.state.register_to_template,
                        ),
                        hide_details=True,
                        density="compact",
                    )

                    with v3.VContainer(
                        fluid=True,
                        classes="pa-0",
                        v_if="register_to_template",
                    ):
                        with v3.VRow(classes="ma-0 align-center mt-1"):
                            with v3.VCol(cols=6, classes="pa-0 pr-2"):
                                v3.VTextField(
                                    label="Template image",
                                    v_model=("template_path", controller.state.template_path),
                                    variant="outlined",
                                    density="compact",
                                    hide_details=True,
                                )
                            with v3.VCol(cols=3, classes="pa-0 pr-2"):
                                v3.VBtn(
                                    "Browse...",
                                    click=ctrl.browse_template,
                                    size="small",
                                    variant="tonal",
                                )
                            with v3.VCol(cols=3, classes="pa-0"):
                                v3.VBtn(
                                    "Use demo template",
                                    click=ctrl.use_demo_template,
                                    size="small",
                                    variant="tonal",
                                )

                    v3.VDivider(classes="my-3")

                    with v3.VRow(classes="ma-0 align-center"):
                        with v3.VCol(cols=9, classes="pa-0 pr-2"):
                            v3.VTextField(
                                label="Output directory",
                                v_model=("output_directory", controller.state.output_directory),
                                variant="outlined",
                                density="compact",
                                hide_details=True,
                            )
                        with v3.VCol(cols=3, classes="pa-0"):
                            v3.VBtn(
                                "Browse...",
                                click=ctrl.browse_output_directory,
                                size="small",
                                variant="tonal",
                            )

                    v3.VAlert(
                        type=("status_type", "info"),
                        text=("status_message", ""),
                        v_if="status_message",
                        classes="mt-3",
                        density="compact",
                    )

                    v3.VBtn(
                        "Launch",
                        color="primary",
                        block=True,
                        classes="mt-4",
                        click=ctrl.launch,
                        loading=("launching", False),
                        disabled=("launching", False),
                    )

    return layout


def configure_loader_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Launch the TractFigure Studio pre-launch file loader.",
    )

    parser.add_argument("--reference", type=Path)
    parser.add_argument(
        "--tractogram",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--recipe", type=Path)
    parser.add_argument("--template", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs"),
    )
    parser.add_argument(
        "--app-port",
        type=int,
        default=8080,
    )

    args, _unknown = parser.parse_known_args()
    return args


def main() -> None:
    pv.OFF_SCREEN = True

    args = configure_loader_cli()

    if not 1 <= args.app_port <= 65535:
        raise ValueError("--app-port must be between 1 and 65535")

    server = get_server("tractfigure-studio-loader-v1", client_type="vue3")
    controller = LoaderController(server, args)
    build_loader_ui(server, controller)

    server.start(
        port=args.app_port,
        open_browser=True,
        show_connection_info=True,
    )


if __name__ == "__main__":
    main()
