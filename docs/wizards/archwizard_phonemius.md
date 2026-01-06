# 🧙‍♂️ Archwizard Phonemius — Keeper of Flow

**Role:** Playlist Generator (global orchestrator)

**Personality:**
- Ancient, patient, methodical
- Cares about *journey* over single moves
- Hates chaos, repetition, and tonal violence
- Speaks in rules, not impulses

**Real function:** Builds a complete playlist and transition plan that satisfies global constraints.

Inputs
- Library metadata (SQLite DB)
- Config (e.g., `autodj.toml` — constraint spells)
- Target intent (duration, mood, BPM targets)

Outputs
- Ordered track list (the Scroll of Summoning)
- Transition metadata: `mix_in`, `hold_duration`, `target_bpm`, `exit_cue`, `effects`
- A render-ready manifest consumed by `Renderax`

Responsibilities
- Enforce global constraints (total duration, diversity, energy curve)
- Call Merlin (selector) repetitively to assemble the sequence
- Use Chronos to translate phrasing and timing rules into sample-level schedule

Mapping to code
- `src/autodj/generate/playlist.py` → `ArchwizardPhonemius` (class)
- `src/scripts/generate_set.py` → CLI entrypoint that runs the Archwizard

Suggested config keys (examples)
- `planner.target_duration_minutes`
- `planner.energy_curve` (low→high→low)
- `planner.max_repeats`

Tests to add
- `test_planner_respects_duration()`
- `test_planner_obeys_energy_curve()`

Voice-based docstring example
> "I plan the ritual, not the mixer's hands. Give me an intent and I will return a scroll."
