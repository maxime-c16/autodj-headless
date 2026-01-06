# AutoDJ-Headless: Technical Specification Sheet

**Status:** Strict enforcement specification for Debian 12 home-lab server
**Last Updated:** 2026-01-06

---

## 1. HARD CONSTRAINTS (Non-negotiable)

### 1.1 Server Hardware
```
CPU:     2 cores (Pentium 3550M @ 2.3–3.3 GHz)
RAM:     3.7 GiB total (usable after OS)
Disk:    ~600 GiB free on NAS mount
Network: Gigabit LAN (shared with Navidrome, Docker pulls)
```

**Implication:** No parallelization. Jobs run sequentially. Memory must be released immediately after job completion.

### 1.2 Host OS Configuration (Debian 12)
```
File Descriptor Limit:  MUST be ≥ 8192
                        Default is 1024 (too low for ffmpeg + Liquidsoap)
                        Action: ulimit -n 8192 (add to /etc/security/limits.conf)

Nice Level:             Run analysis/render at nice +19 (lowest priority)
                        Prevents blocking Navidrome or other services

IO Class:               Use ionice -c 3 (idle I/O priority)
                        Disk I/O does not starve other processes

Swap:                   MUST be disabled or minimized
                        No memory paging to disk during critical operations
```

### 1.3 Docker Runtime Isolation
```
CPU cap:                --cpus=0.5
                        Max 50% of one core during analysis/render
                        Protects against runaway processes

RAM cap:                --memory=512m
                        Hard limit per container
                        Will OOM if exceeded; process terminates cleanly

Memory reservation:     --memory-reservation=256m
                        Soft limit; allows burst to 512m if needed

Swap limit:             --memory-swap=512m
                        Total swap + memory must equal 512m
                        No paging to host disk

PID limit:              --pids-limit=256
                        Prevent fork bombs
```

**Verification:** Every `docker compose` command MUST enforce these limits.

---

## 2. COMPONENT RESOURCE BUDGETS

### 2.1 MIR Analyzer (Python)

**Maximum Runtime:** 120 seconds per track

**Memory Budget:**
```
Peak:    ≤ 512 MiB (hard limit via Docker)
Target:  ≤ 256 MiB (normal operation)
Fail:    Terminate if > 512 MiB (OOM Kill)
```

**I/O Pattern:**
```
Read:   Audio file (10–50 MiB) once, streamed
Write:  SQLite insert (per track: ~500 bytes)
        ID3 tags (updated in place)
```

**Tool Allocation:**
```
aubio:       ≤ 150 MiB (BPM detection, streaming)
essentia:    ≤ 200 MiB (key detection, streaming) OR
keyfinder:   ≤ 100 MiB (keyfinder-cli, subprocess)
```

**One file at a time.** No batch processing.

### 2.2 Set Generator (Python)

**Maximum Runtime:** 30 seconds for typical library

**Memory Budget:**
```
Peak:    ≤ 512 MiB (hard limit via Docker)
Target:  ≤ 300 MiB (load library metadata, search)
```

**I/O Pattern:**
```
Read:   SQLite metadata (streaming query)
        Library index in memory (sorted BPM, key, energy)
Write:  playlist.m3u
        transition_map.json (both < 1 MiB)
```

**Algorithm Constraint:**
- Greedy graph traversal (no backtracking or branch-and-bound)
- Maximum playlist length: 90 minutes
- No re-scanning disk during generation

### 2.3 Render Engine (Liquidsoap)

**Maximum Runtime:** 5× mix duration + 60 seconds overhead
```
Example: 60-min mix = max 360 seconds (6 minutes real-time)
Reason:  Offline clock runs at normal speed, no real-time constraints
```

**Memory Budget:**
```
Peak:    ≤ 512 MiB (hard limit via Docker)
Target:  ≤ 400 MiB (2–3 tracks decoded at once)
```

**I/O Pattern:**
```
Read:   Tracks from NAS mount (streamed via ffmpeg)
        Transition map JSON
Write:  Output mix file (MP3 or FLAC, to data/mixes/)
        Temporary buffers on /tmp (must be cleaned)
```

**No real-time audio input/output.** Offline file-to-file rendering only.

---

## 3. SEQUENTIAL JOB MODEL

### 3.1 No Parallelization

```
┌─────────────────────────────────────────────┐
│ NEVER run these simultaneously:             │
├─────────────────────────────────────────────┤
│ • Two analysis jobs (locks SQLite)          │
│ • Analysis + render (RAM contention)        │
│ • Multiple renders (disk thrashing)         │
│ • Render + Navidrome (I/O blocking)         │
└─────────────────────────────────────────────┘
```

### 3.2 Job Scheduling

```
Cron Job (system level):

02:30 UTC   analyze      (15–30 min max, runs once)
03:00 UTC   generate     (≤ 30 sec)
03:05 UTC   render       (6–10 min max for 60-min mix)

Gap between jobs: ≥ 5 minutes
Each job must complete before next starts.
If a job exceeds max runtime, it is killed and logged.
```

### 3.3 Safety Semantics

```
All jobs are:
  • Stateless (safe to restart)
  • Short-lived (exit cleanly)
  • Failure-isolated (do not affect Navidrome or host)
  • Resumable (partial outputs discarded on restart)
```

---

## 4. DATA PERSISTENCE MODEL

### 4.1 SQLite Metadata Database

**Location:** `data/db/metadata.sqlite`

**Schema (minimal):**
```sql
tracks (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  filename TEXT,
  bpm REAL,                    -- ≥ 50, ≤ 200
  key TEXT,                    -- Camelot notation: "1A", "1B", ..., "12B"
  cue_in INTEGER,              -- Frame offset (@ 44.1 kHz)
  cue_out INTEGER,
  loop_start INTEGER,          -- Optional
  loop_length INTEGER,         -- Optional (bars, typically 16–32)
  duration_seconds INTEGER,
  analyzed_at TIMESTAMP,
  error TEXT                   -- Last error, if any
);

playlists (
  id INTEGER PRIMARY KEY,
  name TEXT,
  created_at TIMESTAMP,
  duration_seconds INTEGER,
  track_count INTEGER
);

playlist_tracks (
  playlist_id INTEGER,
  track_id INTEGER,
  position INTEGER,
  PRIMARY KEY (playlist_id, position)
);
```

**Locking:** SQLite uses file-level locks. Only one analyzer or generator runs at a time.

### 4.2 Playlist Output Format

**File:** `data/playlists/{timestamp}.m3u`

```
#EXTM3U
#EXT-INF:180,Artist - Track Name
/path/to/track_1.mp3
#EXT-INF:240,Artist - Track Name
/path/to/track_2.mp3
```

**Constraint:** All paths must be absolute or relative to `/music` (NAS mount point).

### 4.3 Transition Plan (Generator → Renderer)

**File:** `data/playlists/{timestamp}.transitions.json`

```json
{
  "playlist_id": "abc123",
  "mix_duration_seconds": 3600,
  "transitions": [
    {
      "track_index": 0,
      "track_id": 42,
      "entry_cue": "cue_in",
      "hold_duration_bars": 16,
      "target_bpm": 126,
      "exit_cue": "cue_out",
      "mix_out_seconds": 16,
      "effect": "smart_crossfade",
      "next_track_id": 43
    },
    {
      "track_index": 1,
      "track_id": 43,
      "entry_cue": "cue_in",
      "hold_duration_bars": 20,
      "target_bpm": 124,
      "exit_cue": "cue_out",
      "mix_out_seconds": 12,
      "effect": "filter_swap",
      "next_track_id": 44
    }
  ]
}
```

**Critical:** All timings must be sample-accurate (no floating-point rounding).

### 4.4 Output Mix File

**Location:** `data/mixes/{timestamp}.mp3` (or `.flac`)

**Format Requirements:**
```
Codec:      MP3 (128–256 kbps) or FLAC (lossless)
Sample Rate: 44.1 kHz (match library)
Channels:   Stereo
Duration:   30–90 minutes
Metadata:   ID3v2.4
              TALB = "AutoDJ Mix {timestamp}"
              TCON = "DJ Mix"
              TDRC = {generation_year}
```

---

## 5. EXTERNAL INTERFACE CONTRACTS

### 5.1 Navidrome Integration

**Assumption:** Navidrome runs on `localhost:4533` (default)

**API Endpoint:**
```
GET /rest/getScan.view?u=api&p=pass&c=autodj&rest=json
GET /rest/getBrowse.view?id=...
GET /rest/getAlbumList.view?...
GET /rest/getFile.view?id=... (stream audio)
```

**Constraint:** AutoDJ must NEVER:
- Write to Navidrome database
- Interrupt Navidrome's scan or serving
- Consume > 50% of network bandwidth
- Block on Navidrome availability (timeouts ≤ 5 sec)

### 5.2 Music Library (NAS Mount)

**Mount Point:** `/music` (read-only expected)

**Supported Formats:**
```
MP3, FLAC, OGG, M4A (anything ffmpeg can decode)
```

**Constraint:** Library must be mounted over SMB/NFS. Analyze reads tracks once and caches metadata. Do not re-scan disk during render.

### 5.3 Output Location

**Mount Point:** `/music/autodj-mixes/` (or equivalent write-accessible path)

**Constraint:** Generated mixes must be writable and served by Navidrome afterward.

---

## 6. STRICT PERFORMANCE TARGETS

### 6.1 Analysis Phase

| Task | Time Budget | Must Not Exceed |
|------|-------------|-----------------|
| Single track BPM | 10 sec | 15 sec |
| Single track key | 8 sec | 12 sec |
| Single track cues | 5 sec | 8 sec |
| Total per track | 20 sec | 30 sec |
| Batch (1000 tracks) | 333 min | 500 min |

**Feedback:** If any track takes > 30 sec, log and skip (mark error in DB).

### 6.2 Generation Phase

| Task | Time Budget | Must Not Exceed |
|------|-------------|-----------------|
| Load library metadata | 3 sec | 5 sec |
| Select seed track | 1 sec | 2 sec |
| Traverse graph (60-track mix) | 15 sec | 25 sec |
| Write outputs | 2 sec | 3 sec |
| **Total** | 20 sec | 30 sec |

**Feedback:** If generation exceeds 30 sec, log warning and use last valid output.

### 6.3 Render Phase

| Task | Time Budget | Must Not Exceed |
|------|-------------|-----------------|
| Read transition map | 1 sec | 2 sec |
| Compile Liquidsoap script | 3 sec | 5 sec |
| Render 60-min mix | 360 sec (6 min) | 420 sec (7 min) |
| **Total** | 364 sec | 427 sec |

**Feedback:** If render exceeds max, kill job and log.

---

## 7. SOFTWARE VERSIONS (Locked)

### 7.1 Container Base

```
OS:           Debian 12 (bookworm)
Python:       3.11.x (3.11.8 minimum)
Liquidsoap:   2.2.x (2.2.0 minimum, NOT 2.1.x)
ffmpeg:       6.1.x (concurrent safe)
```

### 7.2 Python Dependencies

```
essentia-streaming  ≥ 2.1.0  (Music Information Retrieval)
aubio               ≥ 0.4.9  (BPM detection alternative)
numpy               ≥ 1.24.0 (matrix ops)
scipy               ≥ 1.10.0 (signal processing)
librosa             ≤ 0.10.x (if used; otherwise omit—RAM heavy)
mutagen             ≥ 1.46.0 (ID3 tag writing)
toml                ≥ 0.10.2 (config parsing)
```

**Constraint:** No machine learning models (TensorFlow, PyTorch). All analysis must be offline DSP.

### 7.3 Liquidsoap Dependencies

```
libfdk-aac          (AAC encoding, optional)
libmp3lame          (MP3 encoding, required)
libflac             (FLAC encoding, optional)
ladspa              (EQ filters, optional but recommended)
```

---

## 8. CONFIG PARAMETER RANGES (Tunable, But Bounded)

### 8.1 Mix Generation Parameters

```toml
[mix]
target_duration_minutes = 60              # Range: 30–120 min
max_playlist_tracks = 90                  # Range: 10–150
seed_track_path = ""                      # Override; empty = random

[constraints]
bpm_tolerance_percent = 4.0               # Range: 2–10 %
                                          # ±4% = ±5 BPM at 126 BPM
energy_window_size = 3                    # Range: 2–5 (tracks)
                                          # Lookahead for energy continuity
min_track_duration_seconds = 120          # Range: 60–300 sec
max_repeat_decay_hours = 168              # Range: 24–720 hours
```

### 8.2 Analysis Parameters

```toml
[analysis]
aubio_hop_size = 512                      # Samples between frames
aubio_buf_size = 4096                     # Frame size (44.1 kHz)
bpm_search_range = [50, 200]              # BPM boundaries
confidence_threshold = 0.5                # Reject low-confidence detections

[key_detection]
method = "essentia"                       # or "keyfinder-cli"
window_size = 4096
                                          # Camelot key must resolve to 1A–12B
```

### 8.3 Render Parameters

```toml
[render]
output_format = "mp3"                     # or "flac"
mp3_bitrate = 192                         # kbps; Range: 128–320
crossfade_duration_seconds = 4            # Range: 2–8 sec
time_stretch_quality = "high"             # rubber band; high = slower
enable_ladspa_eq = false                  # Conditional on DSP load
```

**Constraint:** Any config value outside its range must be rejected at startup with a clear error.

---

## 9. ERROR HANDLING & SAFETY

### 9.1 Analysis Failures

```
Per-track error:
  • Timeout (> 30 sec)         → Mark error in DB, skip, continue
  • OOM (> 512 MiB)            → Docker kills, auto-restart failed job
  • Unrecognizable format      → Skip, log, continue
  • BPM detection failed       → Mark as "unknown", skip
  • Key detection failed       → Mark as "unknown", skip

Batch error:
  • Library file unmounted     → Fail fast, exit with code 1
  • SQLite locked              → Retry with exponential backoff (max 3 min)
  • Disk full                  → Fail fast, exit with code 1
```

### 9.2 Generation Failures

```
  • Library metadata unavailable → Fail fast
  • No valid seed track         → Fail fast
  • Graph traversal stuck       → Use greedy fallback (shorter mix)
  • JSON write failed           → Retry; fail if all retries exhaust
  • Disk full                   → Fail fast, clean partial files
```

### 9.3 Render Failures

```
  • Track file missing/unreadable → Skip track, continue (shorter mix)
  • Liquidsoap crash             → Auto-restart, increment attempt counter
  • Timeout (> 7 min)            → Kill job, mark render failed
  • Output file write failed     → Fail fast, remove partial file
  • Memory limit hit             → Docker kills; log and move to next job
```

### 9.4 Fallback Strategies

```
If render cannot complete a 60-min mix:
  1. Truncate to 45 min (drop last 2–3 tracks)
  2. Truncate to 30 min (drop last 4–5 tracks)
  3. Use previous valid mix (if available)
  4. Fail and wait for next scheduled job
```

---

## 10. MONITORING & LOGGING

### 10.1 Required Log Output

```
All jobs must log to:  /var/log/autodj/{date}.log

Format:
  [YYYY-MM-DD HH:MM:SS] [LEVEL] [COMPONENT] Message

Example:
  [2026-01-06 03:00:45] [INFO] [analyzer] Starting track 42/1000
  [2026-01-06 03:01:15] [WARN] [analyzer] Track timeout; skipping
  [2026-01-06 03:15:30] [INFO] [generator] Playlist complete: 62 tracks, 58 min
  [2026-01-06 03:15:45] [INFO] [renderer] Liquidsoap: 87% complete
  [2026-01-06 03:22:10] [INFO] [renderer] Mix complete: /music/autodj-mixes/xyz.mp3
```

### 10.2 Success Metrics to Log

```
Per analyzer run:
  • Tracks processed / total
  • Success rate (%)
  • Avg time per track (sec)
  • Peak memory usage (MiB)
  • SQLite insert count

Per generator run:
  • Tracks selected
  • Mix duration (sec)
  • Seed BPM
  • Output files written

Per renderer run:
  • Liquidsoap startup time (sec)
  • Rendering speed (% of real-time)
  • Output file size (MiB)
  • Peak memory usage (MiB)
  • Audio peaks (dB, for clipping detection)
```

### 10.3 Alerting Thresholds

```
WARN if:
  • Any job > 1.5× its time budget
  • Peak memory > 400 MiB
  • SQLite locked for > 30 sec
  • NAS read error on track file

ERROR if:
  • Any job fails
  • Output file size < 1 MiB (likely corrupted)
  • Peak memory > 512 MiB (OOM risk)
  • Disk < 500 MiB free
```

---

## 11. TESTING REQUIREMENTS

### 11.1 Unit Tests

```
Every module must have:
  • Test fixtures (minimal library: 5–10 test tracks)
  • Edge case tests (silence, missing BPM, no key)
  • Memory usage tests (peak allocation assertions)
  • Timing tests (single-track operations ≤ 30 sec)
```

### 11.2 Integration Tests

```
Mock the full pipeline:
  1. Ingest 50-track test library
  2. Analyze all tracks (expect < 20 min)
  3. Generate 30-min playlist
  4. Render to output
  5. Verify output is valid MP3/FLAC
  6. Assert peak memory never exceeds 512 MiB
```

### 11.3 Load Tests

```
Dry-run on production server with:
  • Full library (1000+ tracks)
  • Measure real time and memory per phase
  • Confirm no Navidrome interference
```

---

## 12. DEPLOYMENT CHECKLIST

- [ ] Host OS: Debian 12, kernel ≥ 6.1
- [ ] File descriptor limit: `ulimit -n` ≥ 8192
- [ ] Docker daemon: Version ≥ 24.0
- [ ] NAS mount: Read at `/music`, write at `/music/autodj-mixes/`
- [ ] SQLite: Writable at `data/db/metadata.sqlite`
- [ ] Navidrome: Accessible at `localhost:4533`
- [ ] Cron jobs: Configured with 5-min gaps, staggered times
- [ ] Logging: `/var/log/autodj/` writable, rotated weekly
- [ ] Disk space: ≥ 500 MiB free (checked before each job)
- [ ] Memory: Available post-Navidrome ≥ 512 MiB
- [ ] Liquidsoap: Version ≥ 2.2.0, built with libmp3lame
- [ ] ffmpeg: Version ≥ 6.1, multi-threaded safe

---

## 13. VERSIONING & COMPATIBILITY

### 13.1 Image Versioning

```
Docker image tag: autodj-base:v{major}.{minor}-{date}

Example: autodj-base:v1.0-20260106

Increment:
  • major: Architecture change (Liquidsoap major version, Python 3.10→3.11)
  • minor: Dependency update (ffmpeg 6.0→6.1, library upgrade)
  • date:  Rebuild date (YYYYMMDD)
```

### 13.2 Config Versioning

```
autodj.toml version field: config_version = "1.0"

If a new parameter is added (e.g., "enable_ladspa_eq"):
  • Update config_version to "1.1"
  • Provide default value in code
  • Log warning on first run with old config
```

---

## 14. STRICT DO's AND DON'Ts

### DO
- ✅ Run jobs sequentially (one at a time)
- ✅ Enforce resource limits via Docker
- ✅ Log all timing, memory, and errors
- ✅ Use absolute paths (never relative)
- ✅ Clean up temp files after each job
- ✅ Validate config parameters at startup
- ✅ Implement exponential backoff for transient failures
- ✅ Test on the actual server before deploying to cron

### DON'T
- ❌ Parallelize analysis or rendering
- ❌ Bake config or code into Docker images
- ❌ Use floating-point for timing/sample counts
- ❌ Write directly to Navidrome database
- ❌ Disable Docker resource limits
- ❌ Use swap for memory-critical jobs
- ❌ Assume library mount is always available
- ❌ Run long-lived processes (everything must exit)
- ❌ Log sensitive paths or credentials
- ❌ Silence errors; always log and escalate

---

## CHANGE LOG

| Date | Change |
|------|--------|
| 2026-01-06 | Initial spec sheet creation |

---

**Document Owner:** Debian 12 Home Lab (AutoDJ-Headless Project)
**Last Reviewed:** 2026-01-06
**Next Review:** 2026-02-06 (post-implementation)
