#!/usr/bin/env bash
#
# autodj-nightly.sh — Nightly AutoDJ pipeline orchestration
#
# Runs the three pipeline phases (analyze, generate, render) inside the Docker
# container, validates the output, and copies the final mix to the NAS.
#
# Exit codes:
#   0 = success (or skipped because today's mix already exists)
#   1 = general error
#   2 = analyze phase failed
#   3 = generate phase failed
#   4 = render phase failed
#   5 = copy/validation failed
#
# Usage:
#   ./scripts/autodj-nightly.sh          # normal run
#   DRY_RUN=1 ./scripts/autodj-nightly.sh  # log actions without executing

set -euo pipefail

# ==================== PATH (required for cron) ====================
export PATH="/usr/local/bin:/usr/bin:/bin:$PATH"

# ==================== CONFIGURATION ====================

PROJECT_DIR="/home/mcauchy/autodj-headless"
COMPOSE_FILE="${PROJECT_DIR}/docker/compose.dev.yml"
CONTAINER_NAME="autodj-dev"
LOCK_FILE="/tmp/autodj-nightly.lock"
OUTPUT_DIR="/srv/nas/shared/automix"
LOG_DIR="${PROJECT_DIR}/data/logs"
MIXES_DIR="${PROJECT_DIR}/data/mixes"
TODAY=$(date +%Y-%m-%d)
OUTPUT_FILENAME="autodj-mix-${TODAY}.mp3"
LOG_FILE="${LOG_DIR}/nightly-${TODAY}.log"
DRY_RUN="${DRY_RUN:-0}"

# Seed track for playlist generation (Deine Angst - Klangkuenstler)
# Override via: SEED_TRACK_ID=<id> ./scripts/autodj-nightly.sh
SEED_TRACK_ID="${SEED_TRACK_ID:-ff5a6be4778892c8}"

# Size bounds for output validation (bytes)
MIN_SIZE=$((1 * 1024 * 1024))       # 1 MB
MAX_SIZE=$((500 * 1024 * 1024))     # 500 MB

# Retention
MAX_MIXES_KEPT=3
LOG_RETENTION_DAYS=30

# ==================== HELPERS ====================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

die() {
    local code=$1; shift
    log "FATAL: $*"
    exit "$code"
}

cleanup() {
    # flock FD is closed automatically when the script exits,
    # releasing the lock. Nothing else to clean up.
    :
}
trap cleanup EXIT

# ==================== PRE-FLIGHT ====================

# Ensure log directory exists
mkdir -p "${LOG_DIR}"

# Redirect all output to log file (and still print to stdout for cron capture)
exec > >(tee -a "${LOG_FILE}") 2>&1

log "========== AutoDJ Nightly Pipeline =========="
log "Date: ${TODAY}"
log "Project: ${PROJECT_DIR}"

# 1. Idempotency check: skip if today's mix already exists
if [[ -f "${OUTPUT_DIR}/${OUTPUT_FILENAME}" ]]; then
    log "Mix already exists: ${OUTPUT_DIR}/${OUTPUT_FILENAME} — skipping."
    exit 0
fi

# 2. Acquire exclusive lock (non-blocking)
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    die 1 "Another nightly run is already in progress (lock: ${LOCK_FILE})"
fi
log "Lock acquired: ${LOCK_FILE}"

# 3. Ensure container is running
if ! docker-compose -f "${COMPOSE_FILE}" ps 2>/dev/null | grep -q "running"; then
    log "Container not running, starting..."
    docker-compose -f "${COMPOSE_FILE}" up -d
    sleep 5
fi

# 4. Wait for Python environment to be ready
log "Checking container Python environment..."
MAX_WAIT=60
WAITED=0
until docker exec "${CONTAINER_NAME}" python3 -c "import numpy; print('ready')" 2>/dev/null | grep -q "ready"; do
    if (( WAITED >= MAX_WAIT )); then
        die 1 "Container Python environment not ready after ${MAX_WAIT}s"
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    log "Waiting for container... (${WAITED}s)"
done
log "Container ready."

# ==================== PIPELINE PHASES ====================

if [[ "${DRY_RUN}" == "1" ]]; then
    log "[DRY RUN] Would execute pipeline phases — exiting."
    exit 0
fi

# Phase 1: Analyze (basic BPM/key/cue detection)
log ""
log "===== Phase 1: Analyze Library ====="
if ! docker exec \
    -e MUSIC_LIBRARY_PATH=/srv/nas/shared \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.analyze_library; then
    die 2 "Phase 1 (analyze) failed"
fi
log "Phase 1 complete."

# Phase 2: Generate
log ""
log "===== Phase 2: Generate Set ====="
if ! docker exec \
    -e SEED_TRACK_ID="${SEED_TRACK_ID}" \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.generate_set; then
    die 3 "Phase 2 (generate) failed"
fi
log "Phase 2 complete."

# Build pretty filename from transitions metadata
# Format: AutoDJ-{SeedArtist}-{MinBPM}to{MaxBPM}bpm-{TrackCount}trk-{Date}.mp3
PRETTY_FILENAME=""
LATEST_TRANSITIONS=$(find "${PROJECT_DIR}/data/playlists" -maxdepth 1 -name "transitions-*.json" -type f -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | head -1 | awk '{print $2}')

if [[ -n "${LATEST_TRANSITIONS}" ]]; then
    log "Extracting metadata from: ${LATEST_TRANSITIONS}"

    # Extract seed artist (first track), BPM range, and track count via Python
    PRETTY_FILENAME=$(docker exec "${CONTAINER_NAME}" python3 -c "
import json, re, sys
try:
    with open('${LATEST_TRANSITIONS}') as f:
        plan = json.load(f)
    transitions = plan.get('transitions', [])
    if not transitions:
        sys.exit(1)
    # Seed artist
    artist = transitions[0].get('artist', '') or ''
    artist = re.sub(r'[^a-zA-Z0-9]', '', artist)[:20]
    if not artist:
        artist = 'Mix'
    # BPM range
    bpms = [t.get('bpm') for t in transitions if t.get('bpm')]
    if bpms:
        min_bpm = int(min(bpms))
        max_bpm = int(max(bpms))
        bpm_str = f'{min_bpm}to{max_bpm}bpm'
    else:
        bpm_str = 'nobpm'
    count = len(transitions)
    print(f'AutoDJ-{artist}-{bpm_str}-{count}trk')
except Exception:
    sys.exit(1)
" 2>/dev/null) || true

    if [[ -n "${PRETTY_FILENAME}" ]]; then
        OUTPUT_FILENAME="${PRETTY_FILENAME}-${TODAY}.mp3"
        log "Pretty filename: ${OUTPUT_FILENAME}"
    else
        log "Could not extract metadata, using default filename"
    fi
fi

# Phase 3: Render
log ""
log "===== Phase 3: Render Mix ====="
if ! docker exec \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.render_set; then
    die 4 "Phase 3 (render) failed"
fi
log "Phase 3 complete."

# ==================== VALIDATION ====================

log ""
log "===== Validation ====="

# Find the newest .mp3 in data/mixes/
NEWEST_MIX=$(find "${MIXES_DIR}" -maxdepth 1 -name "*.mp3" -type f -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn | head -1 | awk '{print $2}')

if [[ -z "${NEWEST_MIX}" ]]; then
    die 5 "No .mp3 files found in ${MIXES_DIR}"
fi

# Check file was created today (within last 2 hours to allow for long renders)
FILE_AGE_SEC=$(( $(date +%s) - $(stat -c %Y "${NEWEST_MIX}") ))
if (( FILE_AGE_SEC > 7200 )); then
    die 5 "Newest mix is ${FILE_AGE_SEC}s old — no new mix was produced"
fi

# Size validation (catches the known 23GB Liquidsoap runaway bug)
FILE_SIZE=$(stat -c %s "${NEWEST_MIX}")
log "Output file: ${NEWEST_MIX}"
log "File size: $(( FILE_SIZE / 1024 / 1024 )) MB"

if (( FILE_SIZE < MIN_SIZE )); then
    die 5 "Output too small (${FILE_SIZE} bytes < ${MIN_SIZE} bytes) — likely corrupt"
fi

if (( FILE_SIZE > MAX_SIZE )); then
    die 5 "Output too large (${FILE_SIZE} bytes > ${MAX_SIZE} bytes) — Liquidsoap runaway detected"
fi

log "Size validation passed."

# ==================== DELIVERY ====================

log ""
log "===== Delivery ====="

mkdir -p "${OUTPUT_DIR}"

cp "${NEWEST_MIX}" "${OUTPUT_DIR}/${OUTPUT_FILENAME}"
log "Copied to: ${OUTPUT_DIR}/${OUTPUT_FILENAME}"

# Verify the copy
COPY_SIZE=$(stat -c %s "${OUTPUT_DIR}/${OUTPUT_FILENAME}")
if (( COPY_SIZE != FILE_SIZE )); then
    die 5 "Copy verification failed: source=${FILE_SIZE} bytes, dest=${COPY_SIZE} bytes"
fi

log "Delivery verified."

# ==================== CLEANUP ====================

log ""
log "===== Cleanup ====="

# Keep only the N most recent mixes in data/mixes/
MIX_COUNT=$(find "${MIXES_DIR}" -maxdepth 1 -name "*.mp3" -type f | wc -l)
if (( MIX_COUNT > MAX_MIXES_KEPT )); then
    REMOVE_COUNT=$(( MIX_COUNT - MAX_MIXES_KEPT ))
    log "Pruning ${REMOVE_COUNT} old mixes (keeping ${MAX_MIXES_KEPT})..."
    find "${MIXES_DIR}" -maxdepth 1 -name "*.mp3" -type f -printf '%T@ %p\n' \
        | sort -n | head -"${REMOVE_COUNT}" | awk '{print $2}' \
        | xargs -r rm -v
fi

# Purge old log files
OLD_LOGS=$(find "${LOG_DIR}" -maxdepth 1 -name "nightly-*.log" -type f -mtime +${LOG_RETENTION_DAYS} | wc -l)
if (( OLD_LOGS > 0 )); then
    log "Purging ${OLD_LOGS} log files older than ${LOG_RETENTION_DAYS} days..."
    find "${LOG_DIR}" -maxdepth 1 -name "nightly-*.log" -type f -mtime +${LOG_RETENTION_DAYS} -delete
fi

# ==================== DONE ====================

log ""
log "========== Nightly pipeline complete =========="
log "Output: ${OUTPUT_DIR}/${OUTPUT_FILENAME} ($(( FILE_SIZE / 1024 / 1024 )) MB)"
exit 0
