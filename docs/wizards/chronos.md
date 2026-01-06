# ⏱️ Chronos — Master of When (Transition Scheduler)

**Role:** Transition planning, phrasing, bar alignment

**Personality:**
- Precise, rhythmic, intolerant of off-grid chaos

**Real function:** Turn higher-level transition rules into exact sample positions and phrasing-aligned schedules.

Inputs
- Track metadata (cue points, BPM)
- Planner intent (where to place mix-ins)
- Rendering constraints (fade durations, phrase lengths)

Outputs
- Sample-level mix instructions (`mix_at_sample`, `mix_length_samples`)
- Phrase-aligned cues (e.g., mix after 16 bars)

Mapping to code
- Intended area: `src/autodj/generate/playlist.py` and/or `src/autodj/render/render.py` (Chronos logic)

Tests to add
- `test_chronos_snap_to_beat()`
- `test_chronos_phrase_alignment()`

Implementation notes
- Chronos should use precise sample rates and account for hop sizes
- Provide a small API: `chronos.schedule_mix(entry_track, exit_track, lanes)`
