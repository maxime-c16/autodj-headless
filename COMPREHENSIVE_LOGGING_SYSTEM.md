# 🎛️ DJ EQ COMPREHENSIVE LOGGING SYSTEM

## Overview

A production-grade logging system designed specifically for debugging DJ EQ automation, filter calculations, and nightly pipeline execution. Captures detailed information at every stage for easy diagnosis of issues.

---

## Log Files Generated

### 1. Debug Log (Everything)
**File:** `dj-eq-debug-<timestamp>.log`

- **Content:** All DEBUG, INFO, WARNING, ERROR messages
- **Purpose:** Complete audit trail of execution
- **Format:** `[timestamp] [level] [module:function:line] message`
- **Use Case:** Full trace of what happened when something failed

**Example:**
```
[2026-02-16 01:45:23,456] [DEBUG] [autodj.render.render:render:125] Beat detection complete
[2026-02-16 01:45:23,789] [INFO] [autodj.render.render:render:130] ✅ Track 0: 19 DJ skills @ 110 BPM
[2026-02-16 01:45:24,123] [WARNING] [autodj.render.render:render:135] Low confidence skill filtered
[2026-02-16 01:45:24,456] [ERROR] [autodj.render.render:render:140] Filter calculation failed
```

### 2. Analysis Log (Track & Skill Analysis)
**File:** `dj-eq-analysis-<timestamp>.log`

- **Content:** Beat detection, drops, energy profiles, DJ skill generation
- **Purpose:** Understand track analysis and what skills were generated
- **Format:** Structured with phase markers
- **Use Case:** Debug track analysis issues, verify beat detection worked

**Example:**
```
[2026-02-16 01:45:23,456] [INFO] [autodj.analyze] 🔍 ANALYZING TRACK: ff5a6be4778892c8
[2026-02-16 01:45:23,500] [INFO] [autodj.analyze]    ✅ Beat detection: 110.0 BPM (1200 beats)
[2026-02-16 01:45:23,600] [INFO] [autodj.analyze]    ✅ Drop detection: 5 drops found
[2026-02-16 01:45:23,700] [INFO] [autodj.skills]    Generated 19 DJ skills (avg confidence: 78.5%)
```

### 3. Filters Log (DSP & Filter Details)
**File:** `dj-eq-filters-<timestamp>.log`

- **Content:** RBJ filter coefficients, frequency responses, stability checks
- **Purpose:** Verify filter calculations are correct
- **Format:** Detailed DSP parameters
- **Use Case:** Debug audio artifacts, verify filter math

**Example:**
```
Track: ff5a6be4778892c8, Skill: 0
  Peaking Filter: 70.0Hz @ -9.00dB (Q=0.7071)
  b=[0.95831628, -1.89893568, 0.95831628]
  a=[1.00000000, -1.91735149, 0.95662928]
  Stability: ✅ (max pole: 0.977)

Track: ff5a6be4778892c8, Skill: 1
  Peaking Filter: 3000.0Hz @ -6.00dB (Q=0.7071)
  b=[0.97091274, -1.92948106, 0.97091274]
  a=[1.00000000, -1.92948106, 0.94182548]
  Stability: ✅ (max pole: 0.971)
```

### 4. JSON Analysis Output (Structured Data)
**File:** `dj-eq-analysis-<timestamp>.jsonl`

- **Content:** One JSON object per line, structured analysis data
- **Purpose:** Machine-parseable analysis for reporting & metrics
- **Format:** JSONL (one JSON object per line)
- **Use Case:** Generate reports, metrics, automated analysis

**Example:**
```json
{"phase": "track_analysis_start", "track_id": "ff5a6be4778892c8", "file_path": "/path/to/track.mp3", "duration": 300.5, "timestamp": "2026-02-16T01:45:23.456Z"}
{"phase": "beat_detection", "track_id": "ff5a6be4778892c8", "bpm": 110.0, "beat_count": 1200, "confidence": 0.92, "timestamp": "2026-02-16T01:45:23.500Z"}
{"phase": "dj_skills_generated", "track_id": "ff5a6be4778892c8", "total_skills": 19, "by_type": {"bass_cut": 6, "high_swap": 2, "filter_sweep": 2, "blend": 1, "structural": 8}, "avg_confidence": 0.785, "timestamp": "2026-02-16T01:45:23.700Z"}
```

---

## Log File Locations

```
data/logs/
├─ dj-eq-debug-2026-02-16T01-45-23.log          ← Full debug trace
├─ dj-eq-analysis-2026-02-16T01-45-23.log       ← Track analysis details
├─ dj-eq-filters-2026-02-16T01-45-23.log        ← Filter DSP details
└─ dj-eq-analysis-2026-02-16T01-45-23.jsonl     ← Structured JSON output

nightly-2026-02-16.log                           ← Nightly pipeline log (existing)
```

---

## What Gets Logged at Each Stage

### Stage 1: Track Analysis

**What:** Beat detection, drop detection, energy profiles

**Logs:**
- Track file path and duration
- Auto-detected BPM (actual value, not hardcoded!)
- Beat count and confidence score
- Drop detection results (time, energy, confidence)
- Energy profile (min/max/mean values)

**Debug:**
```
🔍 ANALYZING TRACK: ff5a6be4778892c8
   File: /srv/nas/shared/ALAC/Never Enough.m4a
   Duration: 280.50s
   ✅ Beat detection: 110.0 BPM (1200 beats)
      Confidence: 92.00%
      Sample beat times: [0.27, 0.55, 0.82, ...]
   ✅ Drop detection: 5 drops found
      Drop 0: 45.23s (energy: 0.85, conf: 0.91)
      Drop 1: 90.45s (energy: 0.92, conf: 0.88)
   📊 Energy profile: min=0.12, max=0.98, mean=0.65
```

### Stage 2: DJ Skill Generation

**What:** Skills detected, confidence scores, filtering

**Logs:**
- Total skills generated per track
- Skills by type (bass cuts, high swaps, etc.)
- Average confidence score
- Filtered skills (why they were skipped)

**Debug:**
```
🎚️  GENERATING DJ SKILLS: ff5a6be4778892c8
   BPM: 110.0, Drops: 5
   🎯 Skill 0: bass_cut @ 45.23s (conf: 89.50%)
      Details: {'freq': 70.0, 'mag': -9.0, 'q': 0.7071}
   🎯 Skill 1: high_swap @ 45.50s (conf: 85.30%)
   ⏭️  Skipped: filter_sweep (conf: 0.42 < min: 0.65) - low confidence
   ✅ Generated 19 DJ skills (avg confidence: 78.50%)
      bass_cut: 6
      high_swap: 2
      filter_sweep: 2
      three_band_blend: 1
      structural: 8
```

### Stage 3: Filter Calculations

**What:** RBJ filter coefficients, frequency response, stability

**Logs:**
- Frequency, magnitude, Q factor
- Numerator and denominator coefficients
- Attack/release envelopes
- Bar/sample timing
- Stability verification (pole magnitudes)

**Debug (Filters Log):**
```
Track: ff5a6be4778892c8, Skill: 0
  Peaking Filter: 70.0Hz @ -9.00dB (Q=0.7071)
  b=[0.95831628, -1.89893568, 0.95831628]
  a=[1.00000000, -1.91735149, 0.95662928]
  Envelope: Attack=0.0010s, Release=0.0001s (instant=true)
  Timing: Start bar 40 (sample 1958400), Duration 8 bars (352000 samples)
  ✅ STABLE - Max pole magnitude: 0.977
```

### Stage 4: Annotation Storage

**What:** EQ metadata stored in transitions.json

**Logs:**
- Track ID and skill count
- Metadata keys stored
- Ready for rendering

**Debug:**
```
📌 ANNOTATION STORED: ff5a6be4778892c8
   Skills: 19
   Metadata keys: ['detected_bpm', 'detected_drops', 'total_eq_skills', 'skills_by_type', ...]
```

### Stage 5: Rendering

**What:** Liquidsoap execution, output progress

**Logs:**
- Output file path
- Liquidsoap script size
- Progress messages
- Completion status and file size

**Debug:**
```
🎬 RENDERING START
   Output: /home/mcauchy/autodj-headless/data/mixes/autodj-mix-2026-02-16.mp3
   Tracks: 7
📜 Liquidsoap script: 45KB
[liquidsoap] Decoding /path/to/track1.mp3...
[liquidsoap] Applied EQ automation (19 skills)
[liquidsoap] Mixing with aggressive DJ automation...
✅ RENDERING COMPLETE
   File: autodj-mix-2026-02-16.mp3
   Size: 65.3 MB
   Duration: 245.5s
```

### Stage 6: Validation

**What:** Output file verification

**Logs:**
- File exists check
- Size validation
- Bitrate verification
- Completeness check

**Debug:**
```
✔️  VALIDATING OUTPUT
   File: autodj-mix-2026-02-16.mp3
   ✅ PASS: File exists
      File exists: True
   ✅ PASS: Size valid
      Size: 65.3 MB (valid: 50-300 MB)
   ✅ PASS: Format valid
      Format: MP3, Bitrate: 320 kbps
✅ VALID - 6/6 checks passed
```

---

## How to Use Logs for Debugging

### Problem: "No EQ automation applied"

1. **Check Analysis Log:**
   ```bash
   grep -E "Beat detection|Drop detection|Generated.*DJ skills" dj-eq-analysis-*.log
   ```
   - If BPM not detected: beat detection failed
   - If no skills generated: threshold too high

2. **Check Debug Log:**
   ```bash
   grep -E "Track.*not found|annotation error|low confidence" dj-eq-debug-*.log
   ```

3. **Check JSON Output:**
   ```bash
   grep "dj_skills_generated" dj-eq-analysis-*.jsonl | jq '.total_skills'
   ```

### Problem: "Audio sounds wrong (artifacts/clicks)"

1. **Check Filters Log:**
   ```bash
   grep -E "Stability|UNSTABLE|pole magnitude" dj-eq-filters-*.log
   ```
   - If unstable filters: pole magnitude > 0.999
   - If clicks: check envelope times

2. **Check Filter Parameters:**
   ```bash
   grep -E "Peaking Filter|b=\[|a=\[" dj-eq-filters-*.log
   ```
   - Verify coefficients are reasonable (< 2.0)

3. **Check Timing:**
   ```bash
   grep -E "Start bar|Duration|samples" dj-eq-filters-*.log
   ```

### Problem: "Specific track not processed"

1. **Find track in debug log:**
   ```bash
   grep "Track.*ff5a6be4778892c8" dj-eq-debug-*.log
   ```

2. **Check what happened:**
   ```bash
   grep -A 10 "Track.*ff5a6be4778892c8" dj-eq-debug-*.log
   ```

3. **Check JSON for details:**
   ```bash
   grep "ff5a6be4778892c8" dj-eq-analysis-*.jsonl | jq '.'
   ```

---

## Log Analysis Commands

### Get Overall Summary
```bash
# How many tracks processed?
grep "ANALYZING TRACK" dj-eq-debug-*.log | wc -l

# How many skills generated?
grep "Generated.*DJ skills" dj-eq-debug-*.log | awk '{sum+=$2} END {print sum}'

# Any errors?
grep ERROR dj-eq-debug-*.log
```

### Get BPM Information
```bash
# What BPMs were detected?
grep "Beat detection:" dj-eq-debug-*.log | awk '{print $NF}'

# Average BPM?
grep "Beat detection:" dj-eq-debug-*.log | awk '{sum+=$(NF-1); count++} END {print sum/count}'
```

### Get Filter Statistics
```bash
# Count filters applied
grep "Peaking Filter:" dj-eq-filters-*.log | wc -l

# Check any unstable filters
grep "UNSTABLE\|pole magnitude: 0.9[89][0-9]" dj-eq-filters-*.log

# Get frequency distribution
grep "Peaking Filter:" dj-eq-filters-*.log | awk -F'[@ ]' '{print $(NF-2)}' | sort | uniq -c
```

### Get Confidence Scores
```bash
# Min/max confidence
grep "avg confidence" dj-eq-debug-*.log | awk '{print $NF}' | sort

# Low confidence skills
grep "Low confidence\|Skipped" dj-eq-debug-*.log
```

---

## Integration with Nightly Pipeline

The logger is automatically initialized when:
1. `EQ_ENABLED=true` (default)
2. Render phase begins
3. Saves logs to `/home/mcauchy/autodj-headless/data/logs/`

All logs are created with UTC timestamps and organized by phase.

---

## Performance Monitoring

The logger tracks:
- **Per-track time:** How long analysis took
- **Skills/second:** Speed of DJ skill generation
- **Filter calculations:** Time spent on DSP
- **Total rendering time:** End-to-end duration

Access via JSON output:
```bash
grep "performance\|timing\|duration" dj-eq-analysis-*.jsonl | jq '.duration_sec'
```

---

## Error Context

When an error occurs, logs include:
- **Track ID:** Which track failed
- **File path:** Where the file is
- **Error type:** What kind of error
- **Full traceback:** Where it happened
- **Context:** What was being processed

Example error log:
```
❌ ERROR: Beat detection failed
   Track: ff5a6be4778892c8
   Context:
      file_path: /srv/nas/shared/ALAC/Never Enough.m4a
      sr: 44100
      error_type: RuntimeError
      message: Could not decode audio file
```

---

## Log Retention

- **Debug logs:** Kept for 30 days
- **Analysis logs:** Kept for 30 days
- **JSON outputs:** Kept for debugging (manual cleanup needed)
- **Nightly logs:** Kept per nightly run (separate from EQ logs)

---

## Next Steps

When nightly runs tomorrow (02:30 UTC), check logs at:
```
/home/mcauchy/autodj-headless/data/logs/dj-eq-*.log
```

To monitor rendering:
```bash
# Watch logs live
tail -f /home/mcauchy/autodj-headless/data/logs/dj-eq-debug-*.log

# Or after completion, analyze
grep "SUMMARY\|COMPLETE\|ERROR" /home/mcauchy/autodj-headless/data/logs/dj-eq-debug-*.log
```

**All systems ready for production debugging!** 🎛️
