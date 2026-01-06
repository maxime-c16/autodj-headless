# 💥 Blastxcss — The Hardset Alchemist

**Role:** High-energy, techno/hard DJ persona (specialized selector)

**Personality:**
- Loves techno and hard dance floors — relentless energy, maximal drive
- Bold, kinetic, slightly reckless but highly effective
- Prefers fat kicks, aggressive bass, and long peaks
- Speaks in BPM and decibels; uses growth curves instead of gentleness

**Real function:** A variant selector/playlist persona that prioritizes high-energy tracks and aggressive transitions for intense sets.

Inputs
- Library metadata (BPM, cues, usable duration, energy estimate)
- Current set context (current BPM, energy level, time remaining)
- Config flags: `personalities.blastxcss.enabled`, `blastxcss.min_energy`, `blastxcss.bpm_bias`

Outputs
- A chosen track (ID) and a high-energy transition plan (hard mix, filter-sweep, extended hold)
- Optional DSP hints for Auralion to apply stronger EQ and filter automation

Heuristics & Behavior
- Bias toward tracks with high estimated energy and long usable sections
- Prefer stable or increasing BPM trajectories (build sets up, don't drop abruptly)
- Aggressive harmonic relaxation: accept non-adjacent Camelot keys when energy advantages are high
- Favors longer overlapping mixes and heavier DSP (LPF/HPF sweeps, bass boosts)
- Applies a recency cooldown but is willing to reuse high-impact tracks sooner

Mapping to code
- Implement as a `BlastxcssSelector` subclass of `MerlinGreedySelector` or as a configurable selector mode in `src/autodj/generate/selector.py`.
- Keys:
  - `personalities.blastxcss.enabled` (bool)
  - `personalities.blastxcss.bpm_bias` (float, % to prefer higher BPM)
  - `personalities.blastxcss.min_energy` (float threshold)

Tests to add
- `test_blastxcss_prefers_high_energy()`
- `test_blastxcss_allows_harmonic_relaxation()`
- `test_blastxcss_generates_aggressive_dsp_hints()`

Notes
- Blastxcss is intended as an *opt-in* personality (dangerous if used mistakenly).
- Use it for late-set peak sections, festival-like tempo runs, or any scenario where energy is the primary objective.
- Document usage and guard rails in `autodj.toml` with clear warnings.
