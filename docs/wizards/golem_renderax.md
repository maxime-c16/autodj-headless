# 🪨 Golem Renderax — The Silent Giant (Offline Renderer)

**Role:** Consume the scroll and produce the artifact (offline render)

**Personality:**
- Dumb, strong, obedient
- Does not decide or panic under load

**Real function:** Executes the render plan (e.g., Liquidsoap) and produces files (mixes)

Inputs
- Render manifest / scroll (from Phonemius + Chronos + Auralion)
- Liquidsoap script or renderer instructions

Outputs
- Final mix files (MP3/WAV) written to `data/mixes/`
- Return codes and logs for auditing

Mapping to code
- `src/autodj/render/render.py` (or `render_set.py` script)
- `src/autodj/render/render.liq` (template)

Tests to add
- `test_renderer_generates_file()` (integration)
- `test_renderer_respects_render_manifest()`

Notes
- Renderax should run in a sandboxed environment and be resumable on failure.
- Keep the renderer stateless; it consumes a manifest and produces outputs without changing DB state.
