#!/usr/bin/env bash
#
# autodj-structure-analyze.sh — Incremental structure analysis
#
# Analyzes tracks that don't yet have rich metadata (sections, cues, loops,
# kick patterns, vocal detection). Processes only NEW tracks each run.
#
# Runs separately from the nightly mix pipeline to avoid RAM contention.
# Each track takes ~10s and ~35 MiB RAM for the analysis itself,
# plus ~35 MiB for the ffmpeg decode buffer.
#
# Exit codes:
#   0 = success (or nothing to do)
#   1 = general error
#
# Usage:
#   ./scripts/autodj-structure-analyze.sh            # normal run
#   MAX_TRACKS=50 ./scripts/autodj-structure-analyze.sh  # limit batch size

set -euo pipefail

# PATH for cron
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# ==================== CONFIGURATION ====================

PROJECT_DIR="/home/mcauchy/autodj-headless"
COMPOSE_FILE="${PROJECT_DIR}/docker/compose.dev.yml"
CONTAINER_NAME="autodj-dev"
LOCK_FILE="/tmp/autodj-structure.lock"
LOG_DIR="${PROJECT_DIR}/data/logs"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="${LOG_DIR}/structure-${TODAY}.log"

# Max tracks per run (avoid hogging resources for hours)
MAX_TRACKS="${MAX_TRACKS:-100}"

# ==================== HELPERS ====================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

die() {
    local code=$1; shift
    log "FATAL: $*"
    exit "$code"
}

# ==================== PRE-FLIGHT ====================

mkdir -p "${LOG_DIR}"
exec > >(tee -a "${LOG_FILE}") 2>&1

log "========== AutoDJ Structure Analysis =========="
log "Date: ${TODAY}"
log "Max tracks: ${MAX_TRACKS}"

# Acquire exclusive lock (don't run alongside nightly mix)
exec 8>"${LOCK_FILE}"
if ! flock -n 8; then
    die 1 "Another structure analysis is already running (lock: ${LOCK_FILE})"
fi
log "Lock acquired: ${LOCK_FILE}"

# Also check nightly lock — don't run during mix generation
if flock -n 9 /tmp/autodj-nightly.lock; then
    # We got the nightly lock = nightly is NOT running, release it
    flock -u 9
else
    die 1 "Nightly mix pipeline is running — skipping structure analysis"
fi

# Ensure container is running
if ! docker-compose -f "${COMPOSE_FILE}" ps 2>/dev/null | grep -q "running"; then
    log "Container not running, starting..."
    docker-compose -f "${COMPOSE_FILE}" up -d
    sleep 5
fi

# ==================== ANALYSIS ====================

log "Starting incremental structure analysis..."

docker exec "${CONTAINER_NAME}" python3 -c "
import sys, subprocess, gc, time
from dataclasses import asdict
import numpy as np

sys.path.insert(0, '/app/src')
from autodj.db import Database
from autodj.analyze.structure import analyze_track_structure

MAX_TRACKS = ${MAX_TRACKS}

db = Database('/app/data/db/metadata.sqlite')
db.connect()

# Find tracks without structure analysis
all_tracks = db.list_tracks()
existing = set()
try:
    rows = db.conn.execute('SELECT track_id FROM track_analysis').fetchall()
    existing = {r[0] for r in rows}
except Exception:
    pass

pending = [t for t in all_tracks if t.track_id not in existing]
batch = pending[:MAX_TRACKS]

print(f'Tracks in library:    {len(all_tracks)}')
print(f'Already analyzed:     {len(existing)}')
print(f'Pending:              {len(pending)}')
print(f'Batch size:           {len(batch)}')
print()

if not batch:
    print('Nothing to do — all tracks have structure analysis.')
    db.disconnect()
    sys.exit(0)

analyzed = 0
errors = 0
start = time.time()

for i, track in enumerate(batch):
    t0 = time.time()
    try:
        # Decode audio via ffmpeg (mono, 22050Hz for MIR)
        result = subprocess.run(
            ['ffmpeg', '-i', track.file_path, '-f', 'f32le', '-acodec', 'pcm_f32le',
             '-ar', '22050', '-ac', '1', '-v', 'quiet', '-'],
            capture_output=True, timeout=120
        )
        if result.returncode != 0:
            print(f'  [{i+1}/{len(batch)}] SKIP {track.track_id[:8]} (ffmpeg error)')
            errors += 1
            continue

        audio = np.frombuffer(result.stdout, dtype=np.float32)
        if len(audio) < 22050:
            print(f'  [{i+1}/{len(batch)}] SKIP {track.track_id[:8]} (too short: {len(audio)/22050:.1f}s)')
            errors += 1
            continue

        # Run structure analysis
        structure = analyze_track_structure(audio, 22050, track.bpm or 0)

        # Save to database
        analysis = {
            'sections': [asdict(s) for s in structure.sections],
            'cue_points': [asdict(c) for c in structure.cue_points],
            'loop_regions': [asdict(l) for l in structure.loop_regions],
            'kick_pattern': structure.kick_pattern,
            'downbeat_seconds': structure.downbeat_position,
            'total_bars': structure.total_bars,
            'has_vocal': structure.has_vocal,
        }
        db.save_track_analysis(track.track_id, analysis)
        analyzed += 1

        elapsed = time.time() - t0
        title = (track.title or 'Unknown')[:40]
        n_sections = len(structure.sections)
        kick = structure.kick_pattern
        print(f'  [{i+1}/{len(batch)}] {title}  ({n_sections} sections, {kick}, {elapsed:.1f}s)')

        # Free memory between tracks
        del audio, structure, analysis
        gc.collect()

    except Exception as e:
        print(f'  [{i+1}/{len(batch)}] ERROR {track.track_id[:8]}: {e}')
        errors += 1
        gc.collect()
        continue

elapsed_total = time.time() - start
db.disconnect()

print()
print(f'===== Structure Analysis Summary =====')
print(f'Analyzed:  {analyzed}/{len(batch)}')
print(f'Errors:    {errors}')
print(f'Remaining: {len(pending) - analyzed}')
print(f'Time:      {elapsed_total:.0f}s ({elapsed_total/max(analyzed,1):.1f}s per track)')
print(f'Total in DB: {len(existing) + analyzed}')
" 2>&1

EXIT_CODE=$?

if [[ ${EXIT_CODE} -ne 0 ]]; then
    log "WARNING: Structure analysis exited with code ${EXIT_CODE}"
else
    log "Structure analysis complete."
fi

# Cleanup old logs
find "${LOG_DIR}" -maxdepth 1 -name "structure-*.log" -type f -mtime +30 -delete 2>/dev/null || true

log "========== Done =========="
exit ${EXIT_CODE}
