# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AutoDJ-Headless** is an offline, resource-aware automated DJ system that generates DJ-style mixed sets from a static music library. It's designed for a Debian 12 home-lab server with constrained resources (2 CPU cores, ~4 GiB RAM).

The system has three distinct phases:
1. **MIR Analysis** (Python) — Extract BPM, key, and cue points from tracks
2. **Set Generation** (Python) — Select tracks and plan transitions algorithmically
3. **Render** (Liquidsoap) — Perform offline DSP mixing under memory constraints

## Core Architecture Principles

These are **enforced rules**, not suggestions:

### Rule 1: Images are infrastructure, code is mutable
- Docker images change rarely; source code changes constantly
- Code is **never baked into images in dev mode**
- `docker compose` bind-mounts `src/`, `configs/`, and `data/`
- Rebuilding happens only when Python, system dependencies, Liquidsoap, or DSP libraries change

### Rule 2: Every action must be runnable with `make`
- No memorizing long commands
- `make` is your interface contract with the system
- If a task cannot be run via `make`, it's not part of the supported workflow

### Rule 3: One responsibility per layer
- **Python** → decision making (analysis, set generation)
- **Liquidsoap** → DSP (mixing, transitions, time-stretching)
- **Makefile** → orchestration
- **Docker** → isolation, not logic

### Rule 4: Fast feedback beats elegance
- 5-second iteration loop preferred over "perfect" architecture
- Offline DJ allows aggressive restarts without user impact

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
├── src/
│   └── autodj/
│       ├── __init__.py
│       ├── analyze/                 # MIR analysis (BPM, key, cues)
│       │   ├── bpm.py
│       │   ├── key.py
│       │   └── cues.py
│       ├── generate/                # Set generation & playlist logic
│       │   ├── selector.py          # Track selection algorithm
│       │   ├── energy.py            # Energy continuity constraints
│       │   └── playlist.py
│       ├── render/                  # Liquidsoap glue & DSP config
│       │   ├── render.liq
│       │   └── transitions.liq
│       └── cli.py                   # Entrypoint
├── src/scripts/
│   ├── analyze_library.py           # Thin wrapper around autodj.analyze
│   ├── generate_set.py              # Thin wrapper around autodj.generate
│   └── render_set.py                # Thin wrapper around autodj.render
├── docker/
│   ├── Dockerfile.base              # Base image (Python, Liquidsoap, ffmpeg, aubio, keyfinder)
│   ├── compose.dev.yml              # Dev environment (bind-mounts, resource limits)
│   └── stack.prod.yml               # Swarm production (scheduled jobs)
├── configs/
│   ├── autodj.toml                  # Tunable parameters (no magic numbers in code)
│   └── liquidsoap.conf
├── data/
│   ├── db/metadata.sqlite           # Track metadata & cue points
│   ├── playlists/                   # Generated m3u files
│   └── mixes/                       # Output mix files
└── docs/
    └── architecture.md              # Lower-level technical details
```

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
- **Loopback-only networking:** Avoids network bottlenecks
- **Explicit file limits:** FD limit should be raised to ≥ 8192 on the host
- **Docker isolation:** CPU and memory limits must not be disabled
