# DEPLOYMENT CHECKLIST & MONITORING GUIDE

## PRE-DEPLOYMENT VERIFICATION ✅

- [x] Issue #1 (BPM Fallback) code verified in place
- [x] Issue #2 (Stability Scoring) code verified in place
- [x] All 8 stability tests PASS
- [x] Production validation tests PASS
- [x] No breaking changes
- [x] Backwards compatible
- [x] Error handling in place

---

## DEPLOYMENT STEPS

### Step 1: Backup (Optional but Recommended)
```bash
cp data/tracks.db data/tracks.db.backup-$(date +%Y%m%d-%H%M%S)
```

### Step 2: Verify Deployment Files
```bash
# Check code changes are in place
grep "bpm_confidence_low" src/scripts/analyze_library.py
grep "_compute_loop_stability" src/autodj/analyze/structure.py
```

### Step 3: Run Tests (Final Verification)
```bash
cd /home/mcauchy/autodj-headless
python3 -m pytest tests/test_stability_fix.py -v
```

### Step 4: Start Library Analysis
```bash
cd /home/mcauchy/autodj-headless

# Run analysis with logging
make analyze 2>&1 | tee /tmp/analysis-$(date +%Y%m%d-%H%M%S).log

# OR with timestamp for monitoring
make analyze 2>&1 | tee /tmp/multiloop-analysis-$(date +%s).log
```

### Step 5: Monitor Progress (In Separate Terminal)
```bash
python3 monitor.py --interval 5

# OR check specific log file
python3 monitor.py /tmp/multiloop-analysis-*.log
```

---

## WHAT TO MONITOR

### Issue #1: BPM Fallback Recovery

**Look for in logs:**
```
✅ BPM detected: 120.5 BPM       <- Normal detection
⚠️ BPM detection failed          <- Fallback triggered
ℹ️ BPM set to fallback value 120.0 - NEEDS MANUAL VERIFICATION
```

**Expected ratio:**
- Normal BPM detections: ~70-80%
- Fallback BPM: ~20-30%
- This is the RECOVERY we're looking for!

**Verify recovery:**
```bash
# Count fallback tracks
grep "fallback value" /tmp/analysis.log | wc -l

# Should be positive number (these are previously skipped tracks now recovered)
```

### Issue #2: Stability Scoring

**Look for in logs:**
```
LoopRegion(start_seconds=..., stability=0.XX, label='drop_loop')
```

**Expected behavior:**
- Stability scores should range 0.0-1.0
- NO all-zero values (0.00) for real loops
- Drop loops typically 0.6-0.95
- Identical sections should be 0.95+

**Verify scoring:**
```bash
# Extract stability scores
grep "stability=" /tmp/analysis.log | head -20
```

---

## SUCCESS CRITERIA

✅ **Deployment Successful If:**
1. Analysis completes without crashes
2. Track count increases (20-30% recovery from BPM fallback)
3. Stability scores are in 0.0-1.0 range
4. Log shows clear "BPM set to fallback value" entries for recovered tracks
5. No audio glitches in test mixes
6. Mix quality remains excellent

⚠️ **Watch For:**
- Analysis crashes (indicates regression)
- All tracks with fallback BPM (indicates BPM detection broken)
- Stability scores outside [0.0, 1.0] range (indicates algorithm issue)
- Performance degradation (>2x slower analysis)

---

## POST-DEPLOYMENT ACTIONS

### Immediate (During Analysis)
1. Monitor progress with `monitor.py`
2. Watch for BPM fallback entries
3. Verify track count is increasing
4. Check for errors in log

### Short-term (After Analysis)
1. Review "NEEDS MANUAL VERIFICATION" tracks
2. Test mix generation with recovered tracks
3. Verify no audio glitches in output
4. Confirm loop quality in mixes

### Optional Manual Review
```bash
# Extract tracks that need manual BPM verification
grep "NEEDS MANUAL VERIFICATION" /tmp/analysis.log > /tmp/bpm-review.txt

# Get list of unique tracks
sort -u /tmp/bpm-review.txt

# Can manually correct BPM values if desired
```

---

## ROLLING BACK (If Issues)

If deployment causes problems:

```bash
# Restore database backup
cp data/tracks.db.backup data/tracks.db

# Revert code changes
git checkout src/scripts/analyze_library.py

# Verify rollback
grep -q "bpm_confidence_low" src/scripts/analyze_library.py && echo "NOT reverted" || echo "Reverted"

# Re-analyze with old code
make analyze
```

---

## KEY FILES

| File | Purpose |
|------|---------|
| `deploy.sh` | Verification script (run this first) |
| `monitor.py` | Real-time monitoring dashboard |
| `src/scripts/analyze_library.py` | BPM fallback implementation |
| `src/autodj/analyze/structure.py` | Stability scoring (verified working) |
| `tests/test_stability_fix.py` | Validation tests |

---

## SUPPORT DOCUMENTATION

- `/memory/2026-02-11-PRODUCTION-IMPLEMENTATION-REPORT.md` - Complete technical report
- `/memory/2026-02-11-FINAL-STATUS.md` - Final status summary

---

## MONITORING COMMANDS

```bash
# Start monitoring from fresh
python3 /home/mcauchy/autodj-headless/monitor.py

# Monitor specific log
python3 /home/mcauchy/autodj-headless/monitor.py /tmp/multiloop-analysis-*.log

# Print snapshot once
python3 /home/mcauchy/autodj-headless/monitor.py --once

# Custom update interval
python3 /home/mcauchy/autodj-headless/monitor.py --interval 10

# Count recovered tracks
grep "fallback value" /tmp/multiloop-analysis-*.log | wc -l
```

---

## EXPECTED TIMELINE

| Phase | Duration | Activity |
|-------|----------|----------|
| Verification | 1 min | Run tests, verify code |
| Analysis | 30+ min | Process library (depends on size) |
| Monitoring | Continuous | Watch progress and metrics |
| Review | 10 min | Check results and verify success |

---

**Deployment is straightforward and safe. Code is tested and verified.** ✅

Ready to proceed? Run:
```bash
cd /home/mcauchy/autodj-headless
./deploy.sh
```
