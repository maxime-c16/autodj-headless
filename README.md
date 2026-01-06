# AutoDJ-Headless

**Offline algorithmic DJ system for resource-constrained servers**

AutoDJ-Headless generates DJ-style mixed audio sets from a static music library, optimized for low-resource Debian 12 home-lab servers (2 CPU cores, ~4 GB RAM). The system performs all processing offline and headlessly, with no real-time audio or GUI.

## Quick Start

```bash
# Start development container
make dev-up

# Run the analysis → generation → rendering pipeline
make analyze   # Extract BPM, key, cues from library
make generate  # Create playlist and transition plan
make render    # Render offline mix via Liquidsoap

# Stop when done
make dev-down
```

For more commands, see:
```bash
make help
```

## Architecture Overview

```
Music Library (Navidrome/NAS)
         ↓
    [Analyzer] (Python) — Extract BPM, key, cues
         ↓
[Generator] (Python) — Select tracks, plan transitions
         ↓
    [Renderer] (Liquidsoap) — Offline DSP mixing
         ↓
    Output Mix (MP3/FLAC)
```

**Three distinct phases:**

1. **MIR Analysis** — Extracts musical features (BPM, harmonic key, structural cues) once per track, stored in SQLite
2. **Set Generation** — Selects tracks and plans transitions using greedy graph traversal with constraints (BPM ±4%, harmonic compatibility, energy continuity)
3. **Render Engine** — Offline Liquidsoap-based mixing with beatmatching, harmonic transitions, and optional EQ/filtering

**Key design principles:**
- Sequential, not parallel (no multiprocessing — respects tight resource budgets)
- Offline, not real-time (safe to restart without audio dropouts)
- Stateless jobs (safe to interrupt and resume)
- Code is mutable, Docker images are frozen (bind-mounted source code in dev)
- Every action runs via `make` (no tribal knowledge)

## Repository Structure

```
autodj-headless/
├── Makefile                      # Command interface (dev-up, analyze, generate, render, etc.)
├── SPEC.md                       # Strict technical specification (resource budgets, constraints)
├── CLAUDE.md                     # Guidance for Claude Code instances
├── README.md                     # This file
│
├── src/
│   ├── autodj/
│   │   ├── config.py            # Config loading & validation
│   │   ├── analyze/             # BPM, key, cues extraction
│   │   │   ├── bpm.py
│   │   │   ├── key.py
│   │   │   └── cues.py
│   │   ├── generate/            # Playlist & transition planning
│   │   │   ├── selector.py      # Greedy track selection
│   │   │   ├── energy.py        # Energy continuity
│   │   │   └── playlist.py      # M3U and JSON output
│   │   └── render/              # Liquidsoap integration
│   │       ├── render.py        # Engine entrypoint
│   │       ├── render.liq       # Template script
│   │       └── transitions.liq  # Helper functions
│   └── scripts/
│       ├── analyze_library.py   # Thin entrypoint
│       ├── generate_set.py      # Thin entrypoint
│       └── render_set.py        # Thin entrypoint
│
├── docker/
│   ├── Dockerfile.base          # Base image (Python, Liquidsoap, ffmpeg, aubio, etc.)
│   ├── compose.dev.yml          # Dev environment (bind-mounts, resource limits)
│   └── stack.prod.yml           # Production Swarm stack (scheduled jobs)
│
├── configs/
│   ├── autodj.toml              # Tunable parameters (bounds-checked)
│   └── liquidsoap.conf          # Liquidsoap offline rendering config
│
├── data/                         # Runtime artifacts (never committed)
│   ├── db/metadata.sqlite       # Track metadata, cues, BPM, key
│   ├── playlists/               # Generated .m3u and .transitions.json
│   └── mixes/                   # Output MP3/FLAC files
│
└── docs/
    ├── architecture.md          # Lower-level technical details (when created)
    └── workflow.md              # Dev/deployment workflow (when created)
```

## Resource Constraints (SPEC.md § 2)

AutoDJ-Headless is designed within strict server limits:

| Resource | Available | Budget |
|----------|-----------|--------|
| CPU | 2 cores | ≤ 0.5–1 core per job |
| RAM | 3.7 GB total | ≤ 512 MB per job |
| Disk | ~600 GB | Disk-first I/O |

**Enforcement:**
- Docker limits: `--cpus=0.5`, `--memory=512m`
- OS limits: `ulimit -n 8192` (file descriptors), `nice -n 19` (low priority)
- Liquidsoap offline clock (no real-time constraints)

## Development Workflow

### Local Mac Editing
```bash
# On your Mac (authoritative)
git clone git@github.com:maxime-c16/autodj-headless.git
cd autodj-headless
# Edit code, commit, push
git push
```

### Server Deployment
```bash
# On the Debian 12 server
ssh mcauchy@192.168.1.57
cd ~/autodj-headless
git pull

# Run jobs via make
make dev-up
make analyze
make generate
make render
make dev-down
```

**Key workflow rules:**
- Code is edited on Mac only (source of truth)
- Server pulls latest via Git
- Docker images rarely rebuild (only when dependencies change)
- All commands go through `make` (no direct docker/shell)
- Jobs run sequentially (never in parallel)

## Configuration

All tunable parameters are in `configs/autodj.toml`. Examples:

```toml
[mix]
target_duration_minutes = 60          # 30-120 min
max_playlist_tracks = 90              # 10-150 tracks

[constraints]
bpm_tolerance_percent = 4.0           # 2-10%
energy_window_size = 3                # 2-5 tracks

[render]
output_format = "mp3"                 # or "flac"
mp3_bitrate = 192                     # 128-320 kbps
crossfade_duration_seconds = 4.0      # 2-8 seconds
```

All values are validated at startup against SPEC.md bounds. Invalid configs fail with clear error messages.

## Performance Targets (SPEC.md § 6)

| Phase | Budget | Max |
|-------|--------|-----|
| Analyze (per track) | 20 sec | 30 sec |
| Analyze (1000 tracks) | 333 min | 500 min |
| Generate | 20 sec | 30 sec |
| Render (60-min mix) | 360 sec | 420 sec (7 min) |

If jobs exceed these limits, they are logged and can be restarted.

## Scheduling (Production)

Jobs are scheduled via cron or systemd timers:

```
02:30 UTC   analyze      (nightly)
03:00 UTC   generate     (weekly)
03:05 UTC   render       (immediately after generate)
```

Each job is short-lived and exits cleanly. Navidrome is never blocked.

## Error Handling

All jobs are stateless and safe to restart. On failure:

1. **Analysis:** Skip problem tracks, mark as "error" in DB, continue
2. **Generation:** Fallback to shorter mix (45 min, 30 min, or previous valid output)
3. **Render:** Truncate output or use fallback mix

No long-running daemons. Everything exits when done.

## Testing

### Unit Tests
```bash
# TODO: Implement test fixtures
pytest tests/
```

### Integration Tests
```bash
# TODO: Dry-run on full library
make test-integration
```

### Load Tests
```bash
# TODO: Profile on production server with real library
make test-load
```

## Dependencies

- **Python 3.11.x** — Logic and orchestration
- **Liquidsoap 2.2.x** — Offline DSP mixing
- **ffmpeg 6.1.x** — Audio decoding
- **aubio ≥ 0.4.9** — BPM detection
- **essentia ≥ 2.1.0** — Key detection
- **mutagen ≥ 1.46.0** — ID3 tag writing
- **SQLite** — Track metadata storage

All installed in `docker/Dockerfile.base`.

## Documentation

- **SPEC.md** — Strict technical specification (constraints, resource budgets, error handling, monitoring)
- **CLAUDE.md** — Guidance for Claude Code instances
- **project_layout.md** — High-level design rationale (why the structure is shaped this way)
- **project_auto_dj_headless_cross_checked_design.md** — Initial architecture cross-check against research paper
- **workflow.md** — Dev/deployment workflow (Mac ↔ Server)

## Troubleshooting

### Container won't start
```bash
make clean          # Remove old containers
make dev-up         # Try again
```

### Out of memory
Container has 512 MB hard limit. If jobs fail with OOM:
1. Check for memory leaks in code
2. Reduce mix duration in configs/autodj.toml
3. Break library analysis into smaller batches

### Network issues
Ensure:
- Server is on wired LAN (192.168.1.57)
- Navidrome running on localhost:4533
- Music library mounted at /music

### Liquidsoap script errors
Check `/app/data/logs/liquidsoap.log` inside the container:
```bash
docker compose -f docker/compose.dev.yml logs -f autodj
```

## Contributing

1. **Code style:** Python PEP 8, limit lines to 88 chars (black)
2. **Testing:** Unit tests required for new modules
3. **Logging:** All INFO/ERROR messages should be clear and actionable
4. **Memory:** Every function should document peak memory usage
5. **Timing:** Every function should document max runtime

Follow constraints in SPEC.md strictly. If you find a constraint too tight, propose a change with data (profiling results).

## License

TBD

## Author

AutoDJ-Headless is designed for maxime's home-lab Debian 12 server and Navidrome music library.

---

**Status:** Bootstrap phase — Core structure in place, modules awaiting implementation.

**Quick Links:**
- [SPEC.md](SPEC.md) — Strict resource & interface constraints
- [CLAUDE.md](CLAUDE.md) — For Claude Code instances
- [make help](Makefile) — Available commands
