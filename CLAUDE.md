# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AutoDJ-Headless** is an offline, resource-aware automated DJ system that generates DJ-style mixed sets from a static music library. It's designed for a Debian 12 home-lab server with constrained resources (2 CPU cores, ~4 GiB RAM).

The system has three distinct phases:
1. **MIR Analysis** (Python) — Extract BPM, key, and cue points from tracks
2. **Set Generation** (Python) — Select tracks and plan transitions algorithmically
3. **Render** (Liquidsoap) — Perform offline DSP mixing under memory constraints

## Implementation Status

**Overall: ~75% complete. Analysis pipeline is production-ready. Gaps are primarily in rendering script generation and supporting script stubs.**

### What's Working ✅
- Configuration system with strict validation
- SQLite database schema and track metadata management
- BPM detection (aubio + essentia fallback, ≤150 MiB)
- Key detection (essentia + keyfinder-cli fallback, ≤200 MiB)
- Cue point detection (energy-based, ≤100 MiB)
- ID3/MP4/FLAC tag writing for all formats
- Complete analysis pipeline (`analyze_library.py`)
- Greedy track selection with multi-constraint satisfaction (BPM ±%, harmonic wheel, repeat decay)
- Energy-aware playlist generation
- M3U playlist file generation with metadata
- Transition JSON plan generation (track-by-track mixing instructions)
- Render script generation framework

### What Needs Completion 📋
- **generate_set.py**: Stub script (needs to wire database → playlist.generate() → logging)
- **render_set.py**: Stub script (needs to wire transitions JSON → render.render() → logging)
- **Liquidsoap DSP**: Template file exists but DSP functions (smart_crossfade, filter_swap, time_stretch) are not fully implemented
- Test suite (unit & integration tests)
- Navidrome API integration (optional enhancement)

## Common Development Commands

### Getting Started
```bash
make dev-up           # Start dev container with bind-mounts (required before any other commands)
make help             # Show all available targets
make logs             # Tail container output (useful for debugging)
make dev-down         # Stop container when done
```

### Running the Pipeline
```bash
make analyze          # Run MIR analysis on music library (~20 sec per track)
make generate         # Generate playlist and transition plan (≤30 sec)
make render           # Render offline mix via Liquidsoap (≤7 min for 60-min mix)
```

### Configuration & Validation
```bash
make validate-config  # Check configs/autodj.toml for errors
make clean            # Remove containers & volumes (use before troubleshooting)
```

### Testing Demo Mix (Without Full Library)
```bash
# After make dev-up, run this Python script inside container:
docker-compose -f docker/compose.dev.yml exec -T autodj python generate_demo_mix.py
# Generates a test playlist with 15 tracks from analyzed database
```

## Core Architecture Principles

These are **enforced rules**, not suggestions:

### Rule 1: Images are infrastructure, code is mutable
- Docker images change rarely; source code changes constantly
- Code is **never baked into images in dev mode**
- `docker compose` bind-mounts `src/`, `configs/`, and `data/`
- Rebuilding happens only when Python, system dependencies, Liquidsoap, or DSP libraries change
- To rebuild: `make rebuild` (only after dependency changes, never for code logic)

### Rule 2: Every action must be runnable with `make`
- No memorizing long commands
- `make` is your interface contract with the system
- If a task cannot be run via `make`, it's not part of the supported workflow
- See Makefile for target definitions

### Rule 3: One responsibility per layer
- **Python** → decision making (analysis, set generation)
- **Liquidsoap** → DSP (mixing, transitions, time-stretching)
- **Makefile** → orchestration
- **Docker** → isolation, not logic

### Rule 4: Fast feedback beats elegance
- 5-second iteration loop preferred over "perfect" architecture
- Offline DJ allows aggressive restarts without user impact
- Code edits take effect immediately (no rebuild needed)

## Development & Deployment Topology

```
macOS (dev machine)          Debian 12 server
    ↓                              ↓
  Git ←------ (git push/pull) ---- Git
  ↓                                ↓
Editor                      Docker Compose
                           (dev container)
                                  ↓
                            Makefile targets
                            (analyze, generate, render)
```

**Key principle:** Code is edited on the Mac only. The server is a runtime target, not a dev editor.

## Makefile Targets (to be implemented)

When the project reaches implementation, the Makefile should provide these targets:

```makefile
make dev-up       # Start dev container with bind-mounts
make dev-down     # Stop dev container
make rebuild      # Rebuild base Docker image (rare)
make analyze      # Run MIR analysis on library
make generate     # Generate DJ playlist and transition plan
make render       # Render offline mix via Liquidsoap
```

**Important:** Rebuilding is only needed when dependencies change, not for logic/algorithm updates.

## Repository Layout

The project follows this structure:

```
autodj-headless/
├── Makefile                          # Command interface (orchestration)
├── CLAUDE.md                         # This file
├── SPEC.md                           # Strict technical specification (read for constraints)
├── src/
│   ├── autodj/
│   │   ├── config.py               # Configuration loading & validation
│   │   ├── db.py                   # SQLite metadata storage
│   │   ├── analyze/                # MIR analysis (BPM, key, cues) ✅ COMPLETE
│   │   │   ├── bpm.py              # Aubio + essentia fallback
│   │   │   ├── key.py              # Essentia + keyfinder-cli fallback
│   │   │   └── cues.py             # Energy-based cue detection
│   │   ├── generate/               # Set generation & playlist logic ✅ COMPLETE
│   │   │   ├── selector.py         # MerlinGreedySelector (multi-constraint)
│   │   │   ├── energy.py           # Energy analysis & scoring
│   │   │   └── playlist.py         # ArchwizardPhonemius orchestrator
│   │   └── render/                 # Liquidsoap DSP integration 🟡 PARTIAL
│   │       ├── render.py           # Script generation & execution
│   │       ├── render.liq          # Liquidsoap template
│   │       └── transitions.liq     # DSP helper functions (stubs)
│   ├── scripts/
│   │   ├── analyze_library.py      # Complete analysis pipeline ✅ COMPLETE
│   │   ├── generate_set.py         # Playlist generation wrapper 📋 TODO
│   │   └── render_set.py           # Render orchestration wrapper 📋 TODO
│   └── demo_mix.py                 # Demo playlist generator (for testing)
├── docker/
│   ├── Dockerfile.base             # Base image (Python 3.11, Liquidsoap, ffmpeg, aubio, essentia, keyfinder)
│   ├── compose.dev.yml             # Dev environment (bind-mounts, resource limits per SPEC.md)
│   └── stack.prod.yml              # Swarm production (scheduled jobs)
├── configs/
│   ├── autodj.toml                 # Tunable parameters (all bounds validated against SPEC.md § 8)
│   └── liquidsoap.conf             # Liquidsoap runtime config
├── data/                           # Runtime artifacts (not committed)
│   ├── db/metadata.sqlite          # Track metadata, BPM, key, cues, timestamps
│   ├── playlists/                  # Generated .m3u files
│   └── mixes/                      # Output .mp3 or .flac files
└── docs/
    ├── architecture.md             # Lower-level technical details (when created)
    └── workflow.md                 # Dev/deployment workflow (when created)
```

## Three-Phase Pipeline

### Phase 1: MIR Analysis (make analyze)
**Status: ✅ Production-ready**

`src/scripts/analyze_library.py` orchestrates:
1. Discover audio files from library (MP3, FLAC, M4A, WAV, OGG, AIFF)
2. For each file:
   - `bpm.py:detect_bpm()` → float BPM (85-175 DJ range, aubio ≤150 MiB)
   - `key.py:detect_key()` → str key (Camelot 1A-12B, essentia ≤200 MiB)
   - `cues.py:detect_cues()` → CuePoints (energy-based, ≤100 MiB)
   - Write ID3/MP4/FLAC tags
   - Store in `metadata.sqlite` via `db.add_track()`
3. Track progress and statistics

**Key Classes:**
- `TrackMetadata`: Dataclass with file_path, duration, BPM, key, cue frames, tags
- `CuePoints`: Cue-in/cue-out frame offsets, beat-aligned

**Configuration:** `configs/autodj.toml [analysis]` section controls:
- `aubio_hop_size`, `aubio_buf_size` (frame parameters)
- `bpm_search_range` (50-200 BPM default)
- `confidence_threshold` (0.05 default, very lenient)

**Output:** `data/db/metadata.sqlite` + ID3 tags in files + summary log

### Phase 2: Set Generation (make generate)
**Status: 📋 Core logic complete, script stub needs wiring**

`src/scripts/generate_set.py` should orchestrate:
1. Load all analyzed tracks from `metadata.sqlite` via `db.list_tracks()`
2. Call `playlist.generate()` which:
   - Uses `ArchwizardPhonemius` orchestrator
   - Selects seed track (random or explicit via `seed_track_path`)
   - Builds playlist via `MerlinGreedySelector.build_playlist()`:
     - Iteratively calls `choose_next(candidates)`
     - Applies constraints: BPM ±4%, Camelot harmonic wheel, repeat decay (168 hours default)
     - Greedy selection (first valid candidate)
     - Continues until target_duration or max_tracks reached
   - Plans transitions via `_plan_transitions()`:
     - Per-track: hold_duration_bars (16), target_bpm, mix_out_seconds, effect type
     - Generates transition JSON with all DSP parameters
3. Writes `playlist.m3u` and `transitions.json` to `data/playlists/`

**Key Classes:**
- `SelectionConstraints`: BPM tolerance, energy window, min duration, repeat decay
- `MerlinGreedySelector`: Constraint satisfaction algorithm
- `TransitionPlan`: Track index, BPM, cues, effect type, duration
- `ArchwizardPhonemius`: Main orchestrator class
- `energy.py` functions: energy estimation, distance scoring, candidate ranking

**Configuration:** `configs/autodj.toml [mix]` & `[constraints]` sections:
- `target_duration_minutes` (30-120, default 60)
- `max_playlist_tracks` (10-150, default 90)
- `bpm_tolerance_percent` (2-10, default 4.0)
- `energy_window_size` (2-5 lookahead tracks)
- `max_repeat_decay_hours` (24-720, default 168)

**Output:** `data/playlists/{timestamp}.m3u` + `{timestamp}.transitions.json`

### Phase 3: Render (make render)
**Status: 🟡 Framework exists, DSP functions are stubs**

`src/scripts/render_set.py` should orchestrate:
1. Find latest `transitions.json` in `data/playlists/`
2. Call `render.render()` which:
   - Loads transitions JSON
   - Generates Liquidsoap script via `_generate_liquidsoap_script()`:
     - Load each track with cue points (cue-in frame to cue-out frame)
     - Time-stretch to target BPM (if needed)
     - Apply transitions between tracks (smart_crossfade, filter_swap, etc.)
     - Compile to offline script
   - Execute via `subprocess.run(['liquidsoap', script])`
   - Validate output file (check size, duration, format)
   - Write ID3 metadata (playlist ID, timestamp)
3. Log rendering speed, output stats

**Key Classes:**
- `TransitionPlan`: Loaded from JSON (rehydrated)
- `render.py` module functions

**Configuration:** `configs/autodj.toml [render]` section:
- `output_format` ("mp3" or "flac")
- `mp3_bitrate` (128-320 kbps, default 192)
- `crossfade_duration_seconds` (2-8, default 4.0)
- `time_stretch_quality` ("low"/"medium"/"high")
- `enable_ladspa_eq` (bool)

**Output:** `data/mixes/{timestamp}.mp3` or `.flac` with ID3 metadata

**Known Gaps:**
- `transitions.liq` functions (smart_crossfade, filter_swap, time_stretch) are stubs that return unchanged audio
- Liquidsoap script generation is basic (template-based, needs dynamic assembly)
- No beat-aligned crossfading implemented yet

## Conceptual Separation of Concerns

| Layer        | Responsibility                                      |
|--------------|-----------------------------------------------------|
| Python       | Logic: track selection, constraint satisfaction    |
| Liquidsoap   | DSP: beatmatching, harmonic mixing, transitions    |
| Makefile     | Workflow: orchestration and entry points          |
| Docker       | Environment: Python, Liquidsoap, ffmpeg, tools    |

## Key Implementation Details

### MIR Analyzer
- **Tools:** aubio (BPM), essentia/keyfinder (key), custom cue detection
- **Model:** One file at a time; hard RAM cap enforced via Docker
- **Output:** BPM and key written to ID3 tags; cue points to SQLite
- **Constraint:** No analysis during rendering (pre-computed only)

### Set Generator
- **Algorithm:** Greedy graph traversal with constraints
  - BPM within ±4%
  - Camelot-compatible harmonic keys
  - Energy continuity
  - No track repeats
- **Output:** `playlist.m3u` and `transition_map.json` describing mix instructions

### Render Engine (Liquidsoap)
- **Mode:** Offline (no real-time clock)
- **Key features:** smart_crossfade, time-stretch, IIR filters, optional LADSPA EQ
- **Memory:** Very low footprint; streaming decode/encode
- **Reliability:** Proven headless stability

## Resource Constraints (Critical)

The system is designed within tight server limits:

| Resource | Available | Design Budget |
|----------|-----------|---------------|
| CPU      | 2 cores   | ≤ 0.5–1 core burst |
| RAM      | 3.7 GiB   | ≤ 512 MiB per job   |
| Disk     | 600+ GiB  | Disk-first buffering |

**Enforcement:** Resource limits are applied via Docker (`--cpus`, `--memory`) and systemd nice/ionice settings.

## Development Workflow

### Day-to-day iteration (Mac → Server)

1. Edit code on Mac
2. `git commit` changes
3. SSH into server: `ssh mcauchy@192.168.1.57`
4. `git pull` latest changes
5. Run via `make analyze`, `make generate`, or `make render`
6. Get feedback in seconds (no image rebuild)

### When to rebuild Docker image

**Rebuild only when:**
- Python version changes
- System dependencies (ffmpeg, aubio, Liquidsoap) change
- DSP libraries are updated

**Never rebuild for:**
- Logic/algorithm changes
- Config tuning
- Transition parameter tweaks
- Playlist rule adjustments

If you run `make rebuild` often, something is wrong.

## Mental Model for Future Development

> Docker isolates *where* code runs
> Make decides *what* happens
> Python decides *why* (logic)
> Liquidsoap decides *how audio sounds* (DSP)

## Config Philosophy

All tunable parameters belong in `configs/autodj.toml`:
- Mix duration targets
- BPM tolerance
- Energy curve preferences
- RAM budget per job

This separation allows experimentation without code changes or rebuilds.

## Key Algorithms & Data Structures

### Harmonic Compatibility (Camelot Wheel)
Located in `selector.py:_is_harmonically_compatible()`. Implements DJ harmonic mixing rules:
- **Same key:** Always compatible (e.g., 8B → 8B)
- **Adjacent keys:** Compatible (e.g., 8B → 9B or 7B)
- **Parallel mode:** Compatible (e.g., 8B → 8A, opposite major/minor)
- **Unknown key:** Always compatible (treated as wildcard)

This ensures smooth harmonic transitions without dissonance.

### Greedy Track Selection (MerlinGreedySelector)
Located in `selector.py:build_playlist()`. Simple but effective:
1. Start with random/explicit seed track
2. For each iteration:
   - Get all remaining unplayed tracks
   - Filter by: BPM tolerance, harmonic compatibility, repeat decay, min duration
   - Pick first valid candidate (deterministic, no backtracking)
   - Add to playlist, update runtime duration
3. Stop when target_duration or max_tracks reached

**Determinism:** Same library + config = same playlist (useful for testing). Change seed track to vary output.

### Energy Scoring (energy.py)
Used for candidate ranking within harmonic/BPM constraints:
- `estimate_track_energy()`: Multi-fallback strategy
  - Explicit energy value (if set in metadata)
  - Average of cue-in/cue-out energy (from RMS analysis)
  - Computed from loudness dB (LUFS)
  - Fallback to BPM (higher BPM ≈ higher energy)
- `compute_energy_distance()`: Euclidean distance between adjacent tracks
- `compute_energy_score()`: 70% distance + 30% variance (lookahead smoothness)

Higher-scoring candidates = smoother energy progression.

### Camelot Wheel Key Conversion
Located in `key.py`. Converts standard notation (C major, A minor, etc.) to Camelot (1A-12B):
- Major keys: 1A (C) → 12A (B)
- Minor keys: 1B (A minor) → 12B (G# minor)
- Mappings in `STANDARD_TO_CAMELOT_MAJOR` & `STANDARD_TO_CAMELOT_MINOR` dicts

Essential for harmonic mixing compatibility checks.

## Common Development Patterns

### Adding a New Configuration Parameter
1. Add to `configs/autodj.toml` with range bounds and default
2. Add to appropriate config class in `src/autodj/config.py`
3. Add validation in `Config._validate()` (check bounds, type)
4. Reference via `config['section']['param']` in code

Example: If you need a new BPM analysis parameter:
```toml
[analysis]
new_param = 42  # Range: 10-100
```
Then in code: `config['analysis']['new_param']`

### Memory Management Pattern (Important for resource constraints)
1. Process **one track at a time** (never batch)
2. **Explicitly free** after each track:
   ```python
   import gc
   del audio_data, features
   gc.collect()  # Force garbage collection
   ```
3. Monitor with Docker limits: `--memory=512m` (hard OOM kill)
4. Logging: Log peak memory before cleanup

See `analyze_library.py:analyze_track()` for example.

### Adding a New Detection Algorithm
Create fallback chain in analyze module:
1. Primary method (preferred, memory-efficient)
2. Fallback method (if primary fails)
3. Fallback value (if both fail)

Example in `bpm.py`:
```python
def detect_bpm(audio_path):
    try:
        return _detect_bpm_aubio(audio_path)  # Try aubio first
    except Exception:
        return _detect_bpm_essentia(audio_path)  # Fallback to essentia
    except Exception:
        return None  # Mark as undetected in DB
```

### Testing Without Full Library
Use `generate_demo_mix.py` at root level:
```bash
make dev-up
docker-compose -f docker/compose.dev.yml exec -T autodj python generate_demo_mix.py
```
Generates a 15-track test playlist from whatever tracks are in the database.

## Scheduling Model (Production)

| Task           | Frequency | Example Time |
|----------------|-----------|--------------|
| MIR scan       | Nightly   | 02:30        |
| Set generation | Weekly    | 03:00        |
| Rendering      | Weekly    | Immediately after |

All jobs are short-lived and exit cleanly to free memory. Navidrome is unaffected by failures.

## Important Constraints

- **Stateless jobs:** Safe to restart at any point
- **No long-running daemons:** Everything runs offline in bounded time
- **Sequential execution:** Never run multiple analysis/render jobs in parallel (SQLite locking, RAM contention)
- **Explicit file limits:** FD limit should be raised to ≥ 8192 on host (`ulimit -n`)
- **Docker isolation:** CPU (0.5 cores) and memory (512 MiB) limits must not be disabled
- **No swap:** Disable or minimize swap; no paging to disk during jobs
- **Resource budgets:** See SPEC.md § 2 for per-component limits

## Troubleshooting

### Container won't start
```bash
make clean           # Remove old containers
make dev-up          # Retry
docker-compose -f docker/compose.dev.yml logs  # Check error
```

### Out of memory (OOM kill)
- Job exceeded 512 MiB limit (hard Docker kill)
- Check logs for which component failed
- Reduce mix duration in `configs/autodj.toml [mix] target_duration_minutes`
- Or reduce track length analysis if processing large files

### BPM/key detection fails
- Check confidence threshold in `configs/autodj.toml [analysis] confidence_threshold`
- Review output in DB: `SELECT path, bpm, key FROM tracks WHERE bpm IS NULL`
- Manually check problematic files with aubio/essentia CLI tools

### Liquidsoap script generation errors
- Logs in container: `make logs | grep -i liquidsoap`
- Check `transitions.json` format (must match `TransitionPlan` schema)
- Verify track paths in playlist are absolute or relative to `/music`

### SQLite "database is locked"
- Only one analysis/generation job can run at a time
- Kill any stuck processes: `docker-compose -f docker/compose.dev.yml down`
- Check for open transactions in other terminals

## References

- **SPEC.md**: Strict technical specification (constraints, budgets, resource limits)
- **README.md**: User-facing overview and quick start
- **Makefile**: All available commands
- **configs/autodj.toml**: All tunable parameters with bounds
- **generate_demo_mix.py**: Example of how to use the generation API
