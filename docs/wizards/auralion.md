# 🔊 Auralion — The Elementalist (DSP & Sound Shaping)

**Role:** Filters, EQ, loops, fades (Liquidsoap DSP plans)

**Personality:**
- Artistic, expressive, careful with extremes

**Real function:** Defines how transitions are realized in audio domain (EQ, HPF/LPF sweeps, filter swaps, loop windows)

Inputs
- Transition plan (from Phonemius/Chronos)
- Track audio location / file path
- DSP parameters (attack, release, crossfade curves)

Outputs
- DSP instructions or Liquidsoap templates that apply precise effects during render

Mapping to code
- `src/autodj/render/transitions.liq` (templates)
- `src/autodj/render/render.liq` and `src/autodj/render/render.py`

Tests to add
- `test_dsp_plan_serialization()`
- `test_filter_swap_preserves_phase()`

Notes
- Auralion should be unit-testable by validating instruction objects rather than performing full audio renders.
- Provide safe default parameters to avoid extreme processing by accident.
