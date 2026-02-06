# Safe Testing Guide - Segment-Based Rendering

⚠️ **SAFETY FIRST**: This guide prioritizes memory safety over speed. We'll test incrementally.

---

## Pre-Test Checklist

- [ ] Server is stable (no heavy processes running)
- [ ] Sufficient disk space in `data/mixes/` (at least 500 MB free)
- [ ] Music library is accessible
- [ ] You can SSH into server
- [ ] Terminal ready for monitoring

---

## Step 0: Pull Changes and Prepare Server

```bash
# SSH to server
ssh mcauchy@192.168.1.57

# Navigate to project
cd /path/to/autodj-headless

# Pull latest changes
git pull origin master

# Verify new files exist
ls -la src/autodj/render/segmenter.py
ls -la src/autodj/render/progress.py

# Verify config updated
grep "max_tracks_before_segment" configs/autodj.toml
```

---

## Step 1: Test with VERY SMALL Mix (Safety Baseline)

**Goal**: Verify system works without segmentation, measure baseline memory.

### Setup Safe Config

```bash
# Edit configs/autodj.toml - use MINIMAL settings
cat > configs/autodj.toml.test1 << 'EOF'
[mix]
target_duration_minutes = 5       # VERY SHORT
max_playlist_tracks = 5           # VERY FEW TRACKS

[render]
max_tracks_before_segment = 10    # Won't trigger (only 5 tracks)
segment_size = 5
enable_progress_display = true

[constraints]
bpm_tolerance_percent = 4.0
energy_window_size = 3
min_track_duration_seconds = 120
max_repeat_decay_hours = 168

[analysis]
aubio_hop_size = 512
aubio_buf_size = 4096
bpm_search_range = [50, 200]
confidence_threshold = 0.05

[key_detection]
method = "essentia"
window_size = 4096

[system]
library_path = "/music"
playlists_path = "data/playlists"
mixes_path = "data/mixes"
database_path = "data/db/metadata.sqlite"
log_level = "INFO"

[resources]
max_memory_mb = 256
max_cpu_cores = 0.5
max_analyze_time_sec = 30
max_generate_time_sec = 30
max_render_time_sec = 420

[navidrome]
host = "192.168.1.57"
port = 4533
api_path = "/rest"
username = ""
password = ""
connect_timeout_sec = 5
EOF

# Backup original config
cp configs/autodj.toml configs/autodj.toml.backup

# Use test config
cp configs/autodj.toml.test1 configs/autodj.toml
```

### Test 1: Small Mix (No Segmentation)

```bash
# Start dev container
make dev-up

# In separate terminal, monitor memory
# Watch container memory in real-time:
watch -n 1 'docker stats --no-stream | grep autodj'

# In original terminal, generate small mix
make generate

# Check how many tracks were generated
ls -la data/playlists/*transitions*.json
cat data/playlists/*transitions*.json | grep -c '"track_id"'

# Now render - monitor the other terminal for memory usage
make render
```

**Expected Result**:
- ✅ No segmentation (too few tracks)
- ✅ Memory stays ~100-150 MiB
- ✅ Render completes in 1-2 minutes
- ✅ Output file created (~20-30 MB)

**Watch for**:
- Memory climbing above 300 MiB → stop immediately
- Process taking longer than 5 minutes → potential hang
- Error messages about memory → investigate

---

## Step 2: Test with SMALL-MEDIUM Mix (Monitor Segmentation Trigger)

**Goal**: Verify segmentation triggers correctly at 11+ tracks.

### Setup Medium Config

```bash
cat > configs/autodj.toml.test2 << 'EOF'
[mix]
target_duration_minutes = 15      # Slightly longer
max_playlist_tracks = 12          # WILL trigger segmentation (>10)

[render]
max_tracks_before_segment = 10    # Will trigger at 11+ tracks
segment_size = 5                  # 5 tracks per segment
enable_progress_display = true

# ... rest same as test1 ...
EOF

cp configs/autodj.toml.test2 configs/autodj.toml
```

### Test 2: Medium Mix (With Segmentation)

```bash
# In monitoring terminal, watch memory
watch -n 1 'docker stats --no-stream | grep autodj'

# In main terminal
make dev-up

# Generate medium mix
make generate

# Verify it created 11+ tracks
cat data/playlists/*transitions*.json | grep -c '"track_id"'

# Render with segmentation
make render
```

**Expected Result**:
- ✅ Logs show "Large mix detected...using segmented rendering"
- ✅ Progress tracker shows "Segment 1/2" or "Segment 1/3"
- ✅ Memory peaks at ~150-180 MiB (NOT 512+ MiB)
- ✅ See segment concatenation in logs
- ✅ Render completes without OOM

**Segmentation Check**:
```bash
# After render, check logs for segmentation
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "segment"
# Should see: "Large mix detected", "Split into X segments", "Segment X/Y"
```

---

## Step 3: Test with MEDIUM-LARGE Mix (Memory Stress Test)

**Goal**: Verify 20+ minute mixes work without crashing.

### Setup Large Config

```bash
cat > configs/autodj.toml.test3 << 'EOF'
[mix]
target_duration_minutes = 20      # Medium-large mix
max_playlist_tracks = 15          # 15 tracks = 3 segments (5 each)

[render]
max_tracks_before_segment = 10
segment_size = 5                  # Keep segment size small for safety
enable_progress_display = true

# ... rest same as test1 ...
EOF

cp configs/autodj.toml.test3 configs/autodj.toml
```

### Test 3: Medium-Large Mix

```bash
# CRITICAL: Watch memory very closely
watch -n 1 'docker stats --no-stream | grep autodj'

# Main terminal
make dev-up

make generate

# Verify track count
cat data/playlists/*transitions*.json | grep -c '"track_id"'

# Before rendering, check Docker memory limit
docker inspect autodj | grep -A 5 "Memory"

# Render - WATCH MEMORY TERMINAL CLOSELY
make render
```

**Memory Safety Checks**:
- ✅ Memory per segment: 150-200 MiB
- ✅ Memory never exceeds 350 MiB
- ❌ STOP if memory exceeds 400 MiB
- ❌ STOP if container killed (OOM)

**If Memory Gets Too High**:
```bash
# Stop render immediately
docker-compose -f docker/compose.dev.yml down

# Check for errors
docker-compose -f docker/compose.dev.yml logs autodj | tail -50
```

---

## Step 4: Monitor Wizard Progress UI (Optional)

**Goal**: Verify progress tracker displays correctly.

```bash
# Make sure container is running
make dev-up

# In main terminal, watch render with progress tracker
make render

# Expected output:
# ╔════════════════════════════════════════════╗
# ║ 🎵 AutoDJ Mix Rendering Wizard 🎧        ║
# ╚════════════════════════════════════════════╝
#
#   Phase: Rendering Segment 1/3
#   Progress: [████████░░░░░░░░░░░░░░░░░░] 33.3%
#   ...
```

---

## Emergency Stop Procedure

If anything goes wrong:

```bash
# Option 1: Stop container immediately
docker-compose -f docker/compose.dev.yml down

# Option 2: Kill render process
docker exec autodj pkill -f liquidsoap

# Option 3: Nuclear option - stop everything
make dev-down

# Restore original config
cp configs/autodj.toml.backup configs/autodj.toml

# Check what went wrong
docker-compose -f docker/compose.dev.yml logs autodj | tail -100
```

---

## Memory Monitoring Commands

### Real-Time Memory Watch
```bash
# Watch Docker container memory every second
watch -n 1 'docker stats --no-stream autodj | tail -1'

# More detailed memory info
docker stats --no-stream autodj
# Output format: NAME CPU% MEM% MEMUSAGE / LIMIT ...
```

### Peak Memory Detection
```bash
# Check logs for memory usage spikes
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "memory\|mb\|mib"

# Monitor with timeout (stop after 10 min)
timeout 600 watch -n 1 'docker stats --no-stream autodj'
```

### Container Inspection
```bash
# Check Docker memory limit
docker inspect autodj | grep -A 10 "Memory"

# Current container stats
docker stats autodj --no-stream
```

---

## What to Expect at Each Stage

### Test 1 (5 min mix, 5 tracks)
```
✅ Render time: 1-2 minutes
✅ Peak memory: 100-150 MiB
✅ Output size: 20-30 MB
✅ No segmentation
✅ Status: Simple logger (non-interactive)
```

### Test 2 (15 min mix, 12 tracks)
```
✅ Render time: 3-4 minutes
✅ Peak memory: 150-180 MiB per segment
✅ Output size: 40-60 MB
✅ Segmentation: 2-3 segments
✅ Status: Wizard progress tracker (if interactive)
```

### Test 3 (20 min mix, 15 tracks)
```
✅ Render time: 5-7 minutes
✅ Peak memory: 150-200 MiB per segment
✅ Output size: 60-100 MB
✅ Segmentation: 3 segments
✅ Status: Real-time progress updates
```

---

## Success Criteria

✅ **Test 1 Passes** → Basic rendering works
✅ **Test 2 Passes** → Segmentation triggers correctly
✅ **Test 3 Passes** → Memory stays under control

🎉 **All 3 Pass** → Safe to use on production

---

## Rollback Plan

If segmentation causes issues:

```bash
# Revert to previous version
git checkout HEAD~1 -- src/autodj/render/render.py

# Restore original config
cp configs/autodj.toml.backup configs/autodj.toml

# Restart container
make dev-down
make dev-up

# Render with original code
make render
```

---

## Log Analysis

### Check for Segmentation in Logs
```bash
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "segment\|segmented"
```

Expected output:
```
Large mix detected (15 tracks), using segmented rendering
Split into 3 segments
Rendering segment 0: tracks 0-5
Rendering segment 1: tracks 4-9
Rendering segment 2: tracks 8-15
Concatenating 3 segments with 4.0s crossfade
```

### Check for Errors
```bash
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "error\|failed\|exception"
```

Should be empty (or only informational messages).

### Memory Usage Verification
```bash
# Look for memory estimates in logs
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "memory_mb\|estimated"
```

---

## Next Steps After Successful Testing

1. **Document Results**
   - Note peak memory per mix size
   - Record render times
   - Any issues encountered

2. **Adjust Configuration** (if needed)
   - Increase segment_size if memory is very low
   - Decrease segment_size if memory gets too high
   - Tune max_tracks_before_segment threshold

3. **Deploy to Production**
   - Use validated configuration
   - Document any custom tuning

---

## Questions During Testing?

Check these resources:
- **SEGMENTED_RENDERING.md** - Full architecture details
- **configs/autodj.toml** - Configuration reference
- **docker-compose logs** - Real-time diagnostics

Good luck with testing! 🚀
