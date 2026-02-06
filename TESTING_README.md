# Segment-Based Renderer Testing Resources

Complete testing package for safe evaluation of the new segment-based rendering system on Debian 12 server.

---

## Quick Access

### 🚀 Start Here
1. **[TESTING_QUICKSTART.md](TESTING_QUICKSTART.md)** - 5-minute quick reference
   - TL;DR commands to run
   - What to expect at each step
   - Emergency stop procedures

### 📖 Detailed Guides
2. **[SAFE_TESTING_GUIDE.md](SAFE_TESTING_GUIDE.md)** - Complete step-by-step
   - Pre-test checklist
   - Three test scenarios (small/medium/large)
   - Memory monitoring commands
   - Troubleshooting for each test

3. **[SEGMENTED_RENDERING.md](SEGMENTED_RENDERING.md)** - Architecture & technical details
   - How segmentation works
   - Configuration reference
   - Performance analysis
   - Future enhancements

### 🧪 Testing Tools
4. **[test_renderer.sh](test_renderer.sh)** - Automated test setup script
   ```bash
   ./test_renderer.sh 1  # Small mix (5 tracks, no segmentation)
   ./test_renderer.sh 2  # Medium mix (12 tracks, with segmentation)
   ./test_renderer.sh 3  # Large mix (18 tracks, stress test)
   ```

5. **[TEST_RESULTS.md](TEST_RESULTS.md)** - Results logging template
   - Automated form for recording measurements
   - Memory timeline tracking
   - Success/failure criteria
   - Recommendations generation

---

## Testing Overview

### Three-Level Testing Strategy

| Test | Mix Size | Tracks | Duration | Risk | Purpose |
|------|----------|--------|----------|------|---------|
| **Test 1** | Small | 5 | 5 min | Very Low | Verify system works |
| **Test 2** | Medium | 12 | 15 min | Low | Verify segmentation |
| **Test 3** | Large | 18 | 25 min | Medium | Verify OOM prevention |

### Expected Results

**Test 1 (No Segmentation):**
- Duration: 1-2 minutes
- Memory: 100-150 MiB
- Output: 20-30 MB
- Segmentation: None (expected)

**Test 2 (With Segmentation):**
- Duration: 3-4 minutes
- Memory: 150-180 MiB per segment
- Output: 40-60 MB
- Segmentation: 2-3 segments visible in logs

**Test 3 (Stress Test):**
- Duration: 6-8 minutes
- Memory: 150-200 MiB per segment (CRITICAL!)
- Output: 80-120 MB
- Segmentation: 3-4 segments
- **Result: NO OOM kills** (this is the test!)

---

## Memory Safety Rules

```
✅ SAFE:      0-200 MiB   → proceed with confidence
🟡 CAUTION: 200-300 MiB  → monitor closely, continue if stable
🔴 STOP:    > 350 MiB    → stop immediately, investigate
```

---

## Getting Started

### Prerequisites
- SSH access to server (192.168.1.57)
- Two terminals (one for monitoring, one for testing)
- 500 MB free disk space
- Server is stable (no heavy load)

### The Exact Commands

**Terminal 1** (Memory Monitor - keep open):
```bash
ssh mcauchy@192.168.1.57
cd /path/to/autodj-headless
watch -n 1 'docker stats --no-stream autodj | tail -1'
```

**Terminal 2** (Run Tests):
```bash
ssh mcauchy@192.168.1.57
cd /path/to/autodj-headless
git pull origin master

# Test 1
./test_renderer.sh 1
make dev-up
make generate
make render

# If successful, Test 2
./test_renderer.sh 2
make dev-down && make dev-up
make generate && make render

# If successful, Test 3
./test_renderer.sh 3
make dev-down && make dev-up
make generate && make render
```

---

## After Each Test

### Verification Commands

Check if segmentation worked:
```bash
docker-compose -f docker/compose.dev.yml logs autodj | grep -i segment
```

Check output was created:
```bash
ls -lh data/mixes/ | tail -5
```

Verify audio is valid:
```bash
ffprobe data/mixes/*.mp3 2>/dev/null | grep Duration
```

---

## Documentation Map

```
TESTING_README.md (this file)
    ├─ TESTING_QUICKSTART.md        ← Start here (5 min read)
    ├─ SAFE_TESTING_GUIDE.md        ← Detailed procedures
    ├─ SEGMENTED_RENDERING.md       ← Full architecture
    ├─ TEST_RESULTS.md              ← Results template
    └─ test_renderer.sh             ← Automated setup
```

---

## Key Features Being Tested

1. **Segmentation Logic**
   - Automatic threshold detection (>10 tracks)
   - Correct split strategy
   - Memory per segment

2. **Rendering Pipeline**
   - Individual segment rendering
   - FFmpeg concatenation
   - Output validation

3. **Progress Tracking**
   - Real-time updates (if interactive)
   - Logger fallback (if non-interactive)
   - Accuracy of metrics

4. **Memory Safety** ⚠️ CRITICAL
   - Peak RAM under 200 MiB per segment
   - No OOM crashes
   - Clean shutdown

---

## File Structure

```
New Implementation Files:
├── src/autodj/render/segmenter.py        (segmentation logic)
├── src/autodj/render/progress.py         (progress tracking)
└── Modifications to existing files:
    ├── src/autodj/render/render.py       (+300 lines)
    ├── src/scripts/render_set.py         (+50 lines)
    └── configs/autodj.toml               (+15 lines)

Testing Resources:
├── TESTING_QUICKSTART.md                 (quick reference)
├── SAFE_TESTING_GUIDE.md                 (detailed procedures)
├── SEGMENTED_RENDERING.md                (full documentation)
├── TEST_RESULTS.md                       (results template)
├── test_renderer.sh                      (automated setup)
└── TESTING_README.md                     (this file)
```

---

## Success Criteria

All three tests must pass:

- [ ] **Test 1**: Renders without segmentation, memory < 200 MiB
- [ ] **Test 2**: Segmentation triggers, memory < 200 MiB/segment
- [ ] **Test 3**: Large mix, memory < 200 MiB/segment, NO OOM

🎉 **If all pass**: Segment renderer is production-ready!

---

## Emergency Procedures

### If Memory Gets Too High
```bash
# In Terminal 2 (immediate):
Ctrl+C

# Then clean up:
docker-compose -f docker/compose.dev.yml down

# Investigate:
docker-compose -f docker/compose.dev.yml logs autodj | tail -50
```

### If Something Goes Wrong
```bash
# Stop everything
make dev-down

# Check what happened
docker-compose -f docker/compose.dev.yml logs autodj

# If needed, rollback
git checkout HEAD~1 -- src/autodj/render/render.py
cp configs/autodj.toml.backup configs/autodj.toml
make dev-up
make render
```

---

## Next Steps After Testing

### If All Tests Pass ✅
- Renderer is ready for production
- Tune configuration for your setup if needed
- Monitor in production use
- Record memory metrics over time

### If Issues Occur ❌
1. Check SAFE_TESTING_GUIDE.md troubleshooting section
2. Examine logs carefully
3. Consider configuration adjustments
4. Document findings in TEST_RESULTS.md
5. Escalate if needed

---

## Questions?

Each guide has different levels of detail:

- **Quick answer needed**: TESTING_QUICKSTART.md
- **Detailed steps**: SAFE_TESTING_GUIDE.md
- **Technical details**: SEGMENTED_RENDERING.md
- **Troubleshooting**: SAFE_TESTING_GUIDE.md
- **Recording results**: TEST_RESULTS.md

---

## Final Checklist

Before you start:
- [ ] Have two terminals ready
- [ ] SSH access verified
- [ ] 500 MB disk space available
- [ ] test_renderer.sh in project root
- [ ] 15-30 minutes available for testing

During testing:
- [ ] Terminal 1 memory monitor open
- [ ] Terminal 2 running tests
- [ ] Watch for memory spikes
- [ ] Record any errors

After testing:
- [ ] Fill out TEST_RESULTS.md
- [ ] Document findings
- [ ] Commit results if satisfied

---

Happy testing! 🚀
