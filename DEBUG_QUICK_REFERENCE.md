# 🎛️ DJ EQ DEBUGGING QUICK REFERENCE

## Log Files Location
```
/home/mcauchy/autodj-headless/data/logs/
```

## Log Files Generated Each Run

| File | Content | Use Case |
|------|---------|----------|
| `dj-eq-debug-*.log` | Complete trace | Full audit trail |
| `dj-eq-analysis-*.log` | Track analysis | Beat/drop detection |
| `dj-eq-filters-*.log` | DSP parameters | Filter math verification |
| `dj-eq-analysis-*.jsonl` | Structured JSON | Metrics & reporting |

---

## Quick Debugging Commands

### 1. Check If EQ Was Applied
```bash
# Look for annotation summary
tail -50 /home/mcauchy/autodj-headless/data/logs/dj-eq-debug-*.log | grep "DJ skills\|✅ Track"

# Or check JSON for total skills
grep "dj_skills_generated" dj-eq-analysis-*.jsonl | jq '.total_skills' | tail -1
```

### 2. Check Beat Detection (BPM)
```bash
# What BPMs were detected?
grep "Beat detection:" dj-eq-debug-*.log

# Or from JSON:
grep "beat_detection" dj-eq-analysis-*.jsonl | jq '.bpm'
```

### 3. Check Filter Stability
```bash
# Any unstable filters?
grep -i "unstable\|error" dj-eq-filters-*.log

# All pole magnitudes (should be < 1.0)
grep "Max pole magnitude:" dj-eq-debug-*.log
```

### 4. Check for Errors
```bash
# All errors/warnings
grep -E "ERROR|WARNING|FAILED" dj-eq-debug-*.log

# Filter-specific issues
grep -E "UNSTABLE|artifact|click" dj-eq-filters-*.log
```

### 5. Get Skills Summary
```bash
# How many skills per track?
grep "Generated.*DJ skills" dj-eq-debug-*.log

# Total skills across all tracks
grep "dj_skills_generated" dj-eq-analysis-*.jsonl | jq '.total_skills' | awk '{sum+=$0} END {print sum}'
```

### 6. Check Confidence Scores
```bash
# Average confidence per track
grep "avg confidence:" dj-eq-debug-*.log

# Low confidence items
grep "Low confidence\|Skipped" dj-eq-debug-*.log
```

### 7. Get Filter Details
```bash
# All RBJ filters applied
grep "Peaking Filter:" dj-eq-filters-*.log

# Frequencies used
grep "Peaking Filter:" dj-eq-filters-*.log | awk '{print $3}'

# Magnitudes applied
grep "Peaking Filter:" dj-eq-filters-*.log | awk '{print $5}' | sed 's/@//g'
```

### 8. Check Rendering Progress
```bash
# Rendering start/complete
grep -E "RENDERING|COMPLETE" dj-eq-debug-*.log

# Output file and size
tail -5 dj-eq-debug-*.log | grep "File:\|Size:"
```

---

## Common Issues & Fixes

### "No EQ automation"

**Check 1:** Was EQ enabled?
```bash
grep "EQ_ENABLED\|AGGRESSIVE DJ EQ" nightly-*.log | tail -1
```
- Should show: `EQ_ENABLED: true`

**Check 2:** Beat detection worked?
```bash
grep "Beat detection:" dj-eq-debug-*.log
```
- Should see: `✅ Beat detection: XXX.X BPM`

**Check 3:** Skills generated?
```bash
grep "Generated.*DJ skills" dj-eq-debug-*.log
```
- Should see: `✅ Generated 19 DJ skills`

**Check 4:** Track analysis logs present?
```bash
ls -lh dj-eq-analysis-*.log
```
- Should have files with recent timestamp

### "Audio has artifacts/clicks"

**Check 1:** Filter stability
```bash
grep "Max pole magnitude:" dj-eq-debug-*.log
```
- All should be < 0.999
- If > 0.995: potential instability

**Check 2:** Envelope times
```bash
grep -A 2 "Envelope:" dj-eq-filters-*.log
```
- Release should be very small (0.0001s typical)
- Attack should be minimal (0.001s)

**Check 3:** Filter coefficients
```bash
grep "b=\[\|a=\[" dj-eq-filters-*.log | head -5
```
- All values should be -2 to +2 (normal range)
- Values > 10: possible instability

### "Wrong BPM detected"

**Check 1:** What BPM was detected?
```bash
grep "Beat detection:" dj-eq-debug-*.log | awk '{print $(NF-1)}'
```

**Check 2:** Check confidence
```bash
grep -A 1 "Beat detection:" dj-eq-debug-*.log | grep "Confidence"
```
- Should be > 80%
- If < 60%: low confidence, might be wrong

**Check 3:** Check beat count
```bash
grep -A 1 "Beat detection:" dj-eq-debug-*.log | grep "beats"
```
- Should be reasonable for track length
- Formula: beats = duration_seconds * (BPM/60)

### "Specific track not processed"

**Check 1:** Track in analysis?
```bash
grep "ANALYZING TRACK.*your_track_name" dj-eq-debug-*.log
```

**Check 2:** If not found:
```bash
grep -i "not found\|does not exist\|error" dj-eq-debug-*.log | grep -i "your_track"
```

**Check 3:** File path correct?
```bash
grep "File:" dj-eq-debug-*.log | grep "your_track"
```

---

## Performance Metrics

### How Long Did It Take?
```bash
# First log entry timestamp
head -1 dj-eq-debug-*.log | grep -o "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]"

# Last log entry timestamp
tail -1 dj-eq-debug-*.log | grep -o "[0-9][0-9]:[0-9][0-9]:[0-9][0-9]"
```

### Tracks Per Second
```bash
# Track count
TRACKS=$(grep "ANALYZING TRACK" dj-eq-debug-*.log | wc -l)

# Extract timestamps and calculate time
# Then: tracks_per_sec = $TRACKS / total_seconds
```

---

## Filter Math Verification

### Verify RBJ Implementation
```bash
# Check all filter types used
grep "Filter:" dj-eq-filters-*.log | grep -o "Peaking" | sort | uniq -c

# Verify Q values are sane (typically 0.7071)
grep "Q=" dj-eq-filters-*.log | awk '{print $(NF-1)}' | sort | uniq -c
```

### Verify Frequency Targeting
```bash
# Bass cuts (70Hz)
grep "70.0Hz" dj-eq-filters-*.log | wc -l

# High swaps (3000Hz)
grep "3000.0Hz" dj-eq-filters-*.log | wc -l

# Filter sweeps (5000Hz)
grep "5000.0Hz" dj-eq-filters-*.log | wc -l
```

### Check Magnitude Distribution
```bash
# All magnitudes
grep "Peaking Filter:" dj-eq-filters-*.log | awk -F'@' '{print $2}' | sort | uniq -c

# Should see: -3dB, -4dB, -6dB, -7dB, -8dB, -9dB (typical range)
```

---

## JSON Analysis

### Parse JSONL Output
```bash
# Pretty print all entries
jq '.' dj-eq-analysis-*.jsonl

# Get only error entries
grep "error\|failed" dj-eq-analysis-*.jsonl | jq '.'

# Get only successful tracks
grep "dj_skills_generated" dj-eq-analysis-*.jsonl | jq '.track_id, .total_skills'

# Get average confidence across all tracks
grep "dj_skills_generated" dj-eq-analysis-*.jsonl | jq '.avg_confidence' | awk '{sum+=$0; count++} END {print sum/count}'
```

---

## Detailed Analysis Template

When reporting an issue, gather:

```bash
#!/bin/bash
# Gather full debug info

LOG_DATE=$(date +%Y-%m-%d)
LOG_DIR="/home/mcauchy/autodj-headless/data/logs"

echo "=== DJ EQ Debug Info ===" >> debug_report.txt
echo "Date: $LOG_DATE" >> debug_report.txt
echo "" >> debug_report.txt

echo "=== Beat Detection ===" >> debug_report.txt
grep "Beat detection:" $LOG_DIR/dj-eq-debug-*.log >> debug_report.txt

echo "" >> debug_report.txt
echo "=== Skills Generated ===" >> debug_report.txt
grep "Generated.*DJ skills" $LOG_DIR/dj-eq-debug-*.log >> debug_report.txt

echo "" >> debug_report.txt
echo "=== Errors ===" >> debug_report.txt
grep -E "ERROR|UNSTABLE|FAILED" $LOG_DIR/dj-eq-debug-*.log >> debug_report.txt

echo "" >> debug_report.txt
echo "=== Filter Stability ===" >> debug_report.txt
grep "Max pole magnitude" $LOG_DIR/dj-eq-debug-*.log >> debug_report.txt

cat debug_report.txt
```

---

## What to Check First (In Order)

1. **Is EQ enabled?**
   ```bash
   grep "EQ_ENABLED: true" nightly-*.log
   ```

2. **Do log files exist?**
   ```bash
   ls -lh /home/mcauchy/autodj-headless/data/logs/dj-eq-*.log | tail -1
   ```

3. **Any errors?**
   ```bash
   grep ERROR dj-eq-debug-*.log
   ```

4. **BPM detected correctly?**
   ```bash
   grep "Beat detection:" dj-eq-debug-*.log
   ```

5. **Skills generated?**
   ```bash
   grep "Generated.*DJ skills" dj-eq-debug-*.log
   ```

6. **Filters stable?**
   ```bash
   grep "Max pole magnitude" dj-eq-debug-*.log
   ```

7. **Rendering completed?**
   ```bash
   grep "RENDERING COMPLETE" dj-eq-debug-*.log
   ```

---

## Live Monitoring (During Nightly Run)

```bash
# Watch logs in real-time
watch -n 2 "tail -20 /home/mcauchy/autodj-headless/data/logs/dj-eq-debug-*.log | tail -10"

# Or separate terminal:
tail -f /home/mcauchy/autodj-headless/data/logs/dj-eq-debug-*.log | grep -E "✅|❌|ERROR|COMPLETE"
```

---

## Support Scripts

Save this as `debug_dj_eq.sh`:
```bash
#!/bin/bash
LOG_DIR="/home/mcauchy/autodj-headless/data/logs"
LATEST_DEBUG=$(ls -t $LOG_DIR/dj-eq-debug-*.log 2>/dev/null | head -1)

if [ ! -f "$LATEST_DEBUG" ]; then
    echo "No debug logs found"
    exit 1
fi

echo "Latest log: $LATEST_DEBUG"
echo ""
echo "=== Summary ==="
echo "Tracks analyzed: $(grep 'ANALYZING TRACK' $LATEST_DEBUG | wc -l)"
echo "Total skills: $(grep 'Generated.*DJ skills' $LATEST_DEBUG | awk '{sum+=$2} END {print sum}')"
echo "Errors: $(grep ERROR $LATEST_DEBUG | wc -l)"
echo "Unstable filters: $(grep UNSTABLE $LATEST_DEBUG | wc -l)"
```

Run with: `bash debug_dj_eq.sh`

---

## Remember

✅ **All logging is automatic** - just let it run  
✅ **Logs saved to `/home/mcauchy/autodj-headless/data/logs/`**  
✅ **4 separate files** for different types of analysis  
✅ **Easy to grep** for quick debugging  
✅ **Structured JSON** for programmatic analysis  
✅ **Production-grade** logging for reliability tracking  

**Everything you need to debug is in the logs!** 🎯
