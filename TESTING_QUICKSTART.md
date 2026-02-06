# Segment Renderer Testing - Quick Start

## TL;DR - Test in 3 Steps

### Step 1: Prepare Server
```bash
ssh mcauchy@192.168.1.57
cd /path/to/autodj-headless
git pull origin master

# Verify new files exist
ls src/autodj/render/segmenter.py src/autodj/render/progress.py
```

### Step 2: Choose Test Level
```bash
# TEST 1: Small mix (safe baseline) - 5 tracks, 5 min, ~150 MiB peak
./test_renderer.sh 1

# TEST 2: Medium mix (with segmentation) - 12 tracks, 15 min, ~180 MiB per segment
./test_renderer.sh 2

# TEST 3: Large mix (memory stress) - 18 tracks, 25 min, watch memory closely
./test_renderer.sh 3
```

### Step 3: Run Test with Memory Monitoring

**Terminal 1: Memory Monitor** (open FIRST)
```bash
# Watch memory every 1 second - KEEP THIS OPEN
watch -n 1 'docker stats --no-stream autodj | tail -1'

# Expected format:
# autodj  0.10%  18.5MiB / 512MiB  1.25% / ...
```

**Terminal 2: Run Renderer** (open SECOND)
```bash
make dev-up
make generate        # Generate playlist with X tracks
make render          # Render with monitoring

# You should see:
# - Progress tracker (if Test 2/3)
# - "Segment X/Y" messages if segmented
# - Memory staying under control in Terminal 1
```

---

## Safety Rules

🟢 **SAFE** (proceed):
- Memory: 100-200 MiB
- Render running smoothly
- No error messages

🟡 **CAUTION** (monitor closely):
- Memory: 200-300 MiB
- Render taking longer than expected
- Some debug messages

🔴 **STOP** (stop immediately):
- Memory: > 350 MiB
- Container being killed
- "OOM" or "killed" messages

### Emergency Stop
```bash
# Immediately stop render
docker-compose -f docker/compose.dev.yml down

# Check what happened
docker-compose -f docker/compose.dev.yml logs autodj | tail -50
```

---

## Expected Results by Test

### TEST 1: Small Mix (5 tracks)
```
Duration: 1-2 minutes
Memory Peak: 100-150 MiB
Output: 20-30 MB
Segmentation: NONE (too few tracks)
Status: Simple logger (non-interactive)
```

✅ **Success if**: Renders completely, memory < 200 MiB

### TEST 2: Medium Mix (12 tracks)
```
Duration: 3-4 minutes
Memory Peak: 150-180 MiB per segment
Output: 40-60 MB
Segmentation: 2-3 segments (automatic)
Status: Wizard progress tracker (track status icons)
```

✅ **Success if**: Shows segmentation, memory < 200 MiB per segment, audio quality OK

### TEST 3: Large Mix (18 tracks)
```
Duration: 6-8 minutes
Memory Peak: 150-200 MiB per segment
Output: 80-120 MB
Segmentation: 3-4 segments
Status: Real-time progress updates, segment timing
```

✅ **Success if**: Memory never exceeds 250 MiB, no OOM, no crashes

---

## Verifying Segmentation

### Check if Segmentation Triggered
```bash
# After render completes:
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "segment"

# You should see:
# "Large mix detected (X tracks), using segmented rendering"
# "Split into Y segments"
# "Rendering segment 0: tracks 0-5"
# "Concatenating Y segments"
```

### Check Memory Per Segment
```bash
# Look for memory estimates
docker-compose -f docker/compose.dev.yml logs autodj | grep -i "memory_mb"

# Expected output:
# "~150 MB RAM, ~200 MB RAM" etc per segment
```

### Verify Audio Quality
```bash
# Check output file exists and has metadata
ffprobe data/mixes/*.mp3 2>/dev/null | head -20

# Expected:
# Duration: 00:XX:XX
# Sample rate: 44100 Hz
# Bitrate: 192k
```

---

## Troubleshooting

### Memory Too High
```
Symptom: Memory exceeds 250 MiB during segment render
Solution: Reduce segment_size in configs/autodj.toml
  segment_size = 3  # Smaller segments = lower peak RAM
```

### Segmentation Not Triggering
```
Symptom: Mix has 15 tracks but doesn't segment
Solution: Check max_tracks_before_segment setting
  grep max_tracks_before_segment configs/autodj.toml
  Should be 10 (default)
```

### Slow Concatenation
```
Symptom: Render completes segments quickly but concatenation is slow
Note: This is normal - ffmpeg acrossfade takes time
Solution: None needed - just wait
```

### Progress Tracker Not Showing
```
Symptom: Just see logs, no ASCII wizard UI
Reason: Running in non-interactive mode (expected in SSH)
Solution: Enable interactive mode
  # In logs, should see progress via logger instead
  # Check: grep "Rendering\|Segment" in logs
```

---

## Test Results Checklist

For each test, verify:

- [ ] Config loaded correctly (no errors)
- [ ] Playlist generated with expected track count
- [ ] Render started
- [ ] Memory stayed under 250 MiB
- [ ] No container killed / OOM messages
- [ ] Output file created
- [ ] Render completed successfully
- [ ] If segmented: logs show segment messages

---

## Full Testing Timeline

```
Step 1: Test 1 (Small Mix)
  Time: 5 minutes
  Risk: Very low
  Purpose: Verify system works

  ↓ (If passes) ↓

Step 2: Test 2 (Medium Mix)
  Time: 10 minutes
  Risk: Low
  Purpose: Verify segmentation triggers correctly

  ↓ (If passes) ↓

Step 3: Test 3 (Large Mix)
  Time: 15 minutes
  Risk: Medium (watch memory closely!)
  Purpose: Verify large mixes work without OOM

  ↓ (If all pass) ↓

✅ READY FOR PRODUCTION
```

---

## After Testing

### If All Tests Pass ✅
```bash
# Keep using new segment-based renderer
# Configure for your server:
#   max_playlist_tracks = your max mix size
#   segment_size = tune based on available RAM
#   enable_progress_display = true (or false for non-interactive)

# Commit your custom config
git add configs/autodj.toml
git commit -m "Tune segment rendering for production"
```

### If Issues Occur ❌
```bash
# Restore original renderer
git checkout HEAD~1 -- src/autodj/render/render.py
cp configs/autodj.toml.backup configs/autodj.toml

# Restart and use old system
make dev-down
make dev-up
make render

# Document issue for investigation
```

---

## Quick Reference

| Test | Mix Size | Tracks | Duration | Peak RAM | Segmentation |
|------|----------|--------|----------|----------|--------------|
| 1 | Small | 5 | 5 min | 100-150 MB | No |
| 2 | Medium | 12 | 15 min | 150-180 MB/seg | Yes (2-3) |
| 3 | Large | 18 | 25 min | 150-200 MB/seg | Yes (3-4) |

---

## Support

If you need help:
1. Check **SAFE_TESTING_GUIDE.md** for detailed step-by-step instructions
2. Check **SEGMENTED_RENDERING.md** for architecture details
3. Check logs: `docker-compose -f docker/compose.dev.yml logs autodj`

Good luck! 🚀
