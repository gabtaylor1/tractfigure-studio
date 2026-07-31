# Implementation order

The complete procedure is in `PREHACKATHON_GUIDE.md`. The required order is:

1. Back up and replace the canonical starter files from this bundle.
2. Install CPython 3.12 and synchronize the frozen environment.
3. Fetch and verify all demonstration data.
4. create the portable five-bundle scene recipe.
5. Generate deterministic registration fixtures.
6. Run lint, unit, registration, rendering, and integration tests.
7. Generate and inspect reference renders.
8. Push only after local validation, then require the four-platform CI matrix.
9. Prepare labeled issues and reference images.
10. Run a clean-install rehearsal and tag `v0.1.0-starter` only after every gate passes.

All commands are ordinary `python` commands inside the activated virtual
environment. Platform-specific activation and temporary-directory commands are
listed in `PREHACKATHON_GUIDE.md`.
