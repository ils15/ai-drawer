# Viewport validation

Live validation passed on 2026-09-06 with Autodesk Fusion 2705.1.11,
its bundled Python 3.14.0, and the development worktree based on `79b4fc9c`.
Requests used the real HTTP endpoint and Fusion's main-thread dispatcher.

The test created a temporary unsaved document with a 4 × 3 × 2 cm solid.
All 35 checks passed:

- Modern `tools/list` returned all 13 tools.
- Orthographic fit produced positive extents; zoom by 2 halved them.
- Camera snapshots restored the reported state within numerical tolerance.
- Orbit changed the eye while preserving target and eye-to-target distance.
- Pan moved the target by the expected screen-plane distance.
- Both perspective modes supported zoom and snapshot restoration; zoom
  halved eye-to-target distance without changing the perspective angle.
- All 11 standard-view names were accepted and produced valid fitted cameras.
- Default, transparent, cropped solid-background, non-antialiased, and native
  viewport-size captures returned readable PNGs with the expected dimensions.
- Transparent PNGs contained both fully transparent background and opaque
  geometry. The solid background contained the exact requested RGB bytes
  and every output pixel was opaque. Representative images were inspected.
- Capture preserved the camera, including when using a temporary standard
  view and fit. Invalid camera combinations and out-of-bounds crops returned
  errors without changing the camera.
- `get_viewport`, `set_viewport`, and `capture_viewport` succeeded through
  MCP 2025-11-25, 2025-06-18, and 2025-03-26 after their initialization
  handshakes, as well as through stateless MCP 2026-07-28 requests.
- The temporary document was closed without saving, the original document
  was reactivated, and its original camera was restored and checked.

After testing, the ordinary add-in `v1.3.0 (5c43aa2a)` was restarted.
Its startup setting is enabled; the development add-in is stopped and its
startup setting is disabled.

The automated suite also passed all 108 tests before live validation.
Those tests cover additional failure paths, PNG filters, and malformed input.
Live testing covered macOS; it does not establish live Windows behavior.
