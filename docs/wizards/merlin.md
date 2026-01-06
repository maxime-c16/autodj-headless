# 🎯 Merlin — The Greedy Selector (The Impatient Oracle)

**Role:** Local track selector (greedy heuristic)

**Personality:**
- Fast, decisive, short-tempered
- Optimizes the immediate next step
- Prefers "good enough" and immediate throughput

**Real function:** Evaluates a candidate pool and returns the single next-best track along with minimal transition hints.

Inputs
- Candidate pool (from DB/Archwizard constraints)
- Current track context (bpm, key, energy)
- Selector config: `bpm_tolerance_percent`, `recency_decay`, `harmonic_rules`

Outputs
- A chosen track (ID) and transition hints (target BPM, effect)

Heuristics
- BPM within ±X%
- Camelot harmonic compatibility (adjacent keys preferred)
- Energy continuity (avoid sudden spikes/drops)
- Repeat decay (penalize recently played tracks)

Mapping to code
- `src/autodj/generate/selector.py` → `MerlinGreedySelector`

Tests to add
- `test_merlin_prefers_harmonic_matches()`
- `test_merlin_respects_bpm_tolerance()`
- `test_merlin_applies_recency_penalty()`

Notes
- Merlin must not be trusted to finish a full playlist — let Phonemius supervise.
- Keep Merlin deterministic for reproducible debugging (seedable randomness).
