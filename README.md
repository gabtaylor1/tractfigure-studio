# TractFigure Studio

Figure-oriented tractography visualization and registration starter for a
cross-platform student hackathon.

The validated runtime is CPython 3.12. The committed `uv.lock` resolves native
wheels for Windows, macOS Apple Silicon, macOS Intel, and Linux. VTK is held at
9.3.x because FURY 0.12 requires VTK below 9.4.

## Start here

Follow `PREHACKATHON_GUIDE.md` from beginning to end. It contains:

- Windows/MobaXTerm, macOS, and Linux installation commands
- the exact order for replacing and adding bundle files
- data download and verification
- unit, integration, registration, rendering, and CI gates
- reference-render and release procedures
- the prepared hackathon issue set

The stable coordinate, transform-direction, scene-state, and rendering rules are
summarized in `docs/ARCHITECTURE.md`.

Do not rename the canonical v1 modules. In particular, keep:

- `src/tractfigure/scene_state_v1_20260730.py`
- `src/tractfigure/renderer_trame_v1_20260730.py`
- `src/tractfigure/gui/app_trame_v1_20260730.py`

## After installing and activating the environment

```bash
python scripts/fetch_demo_data.py
python scripts/verify_demo_data.py
python scripts/create_demo_recipe.py
python scripts/generate_registration_demo.py
python scripts/preflight.py
```

Launch the validated five-bundle scene:

```bash
python -m tractfigure.gui.app_trame_v1_20260730 \
  --recipe examples/recipes/five_bundle_trame_v1_20260730.json \
  --output-dir outputs \
  --app-port 8080
```

Open `http://localhost:8080` if the browser does not open automatically.
