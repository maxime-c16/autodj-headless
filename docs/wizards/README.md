# 🧙‍♂️ The Order of the Turning Decks — Grimoire

This folder contains the canonical descriptions of each "wizard" in the AutoDJ system — a cognitive interface for reasoning about the architecture.

Why this exists
- Helps debug and reason about components by mapping behaviours to personalities
- Makes responsibilities and inputs/outputs explicit for tests and extension
- Provides a lightweight design doc for new contributors

Files in this folder
- `archwizard_phonemius.md` — Playlist generator (global planner)
- `merlin.md` — Greedy selector (local oracle)
- `brother_beatus.md` — Analyzer (MIR extractor)
- `chronos.md` — Transition & timing planner
- `auralion.md` — DSP and filter logic
- `golem_renderax.md` — Offline renderer (executor)
- `blastxcss.md` — High-energy techno/hardset persona (opt-in selector mode)

Quick usage
- Reference these docs when changing selection heuristics, planner rules, or render parameters.
- Use the `Personality` sections to create docstrings, test names, and config keys (spells).

> Tip: When debugging a playlist issue, name the wizard in your issue instead of vague module names. It points to the right place immediately.
