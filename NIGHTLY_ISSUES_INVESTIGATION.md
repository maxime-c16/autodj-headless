# Nightly Pipeline Issues - Detailed Investigation

## Issue #1: Playlist Not Using Greedy Selector (CONFIRMED)

### Problem
Nightly runs generate the SAME playlist every single night using a fixed seed track.

### Root Cause
File: `src/autodj/generate/playlist.py`
Line: 842-844

```python
def generate(...):
    if target_duration_minutes is not None and database is not None:
        logger.info("Using orchestrated playlist generation (Phonemius)")
        phonemius = ArchwizardPhonemius(database, config)
```

The nightly script calls this with `target_duration_minutes`, so it goes into "orchestrated" mode using **ArchwizardPhonemius** instead of **MerlinGreedySelector**.

### Evidence from 2026-02-18 nightly run

```
[autodj.generate.playlist] Using orchestrated playlist generation (Phonemius)
[autodj.generate.selector] Building playlist from seed ff5a6be4778892c8 (target: 45min = 2700s)
```

That seed track ID `ff5a6be4778892c8` comes from `scripts/autodj-nightly.sh` line ~44:
```bash
SEED_TRACK_ID="${SEED_TRACK_ID:-ff5a6be4778892c8}"
```

### Why This Is Wrong

1. **MerlinGreedySelector exists and is imported** (line 25)
   ```python
   from .selector import MerlinGreedySelector, SelectionConstraints
   ```

2. **But it's never called for nightly runs**
   - Only imported, never used
   - ArchwizardPhonemius is the fallback that runs instead

3. **Same seed = same playlist every night**
   - Using fixed `ff5a6be4778892c8`
   - No randomization
   - No persona-based selection

4. **ArchwizardPhonemius is single-strategy**
   - Not multi-persona
   - Not leveraging greedy selection
   - Older architecture

### What Should Happen

**MerlinGreedySelector approach:**
```python
# Should look like:
selector = MerlinGreedySelector(database, constraints)
# With multiple personas rotating/randomly selected:
personas = [
    {'name': 'energy_riser', 'weight': ...},
    {'name': 'harmonic_journey', 'weight': ...},
    {'name': 'bass_narrative', 'weight': ...},
]
```

### Fix Required

In `playlist.py` generate() function:
1. Check if personas are configured
2. If yes: Use MerlinGreedySelector with persona selection
3. If no: Fall back to ArchwizardPhonemius
4. Rotate or randomize seed track daily

---

## Issue #2: DJ EQ Not Applied in Liquidsoap Rendering

### Problem
EQ annotations ARE correctly detected and stored, but Liquidsoap doesn't apply them.

### Evidence from nightly run

The transitions.json contains complete EQ data:
```json
"eq_annotation": {
  "eq_opportunities": [
    {
      "type": "bass_cut",
      "bar": 42,
      "frequency": 70,
      "magnitude_db": -8,
      "confidence": 0.88
    },
    ...
  ],
  "total_eq_skills": 69
}
```

✅ 69 EQ opportunities detected
✅ Confidence levels: 0.75-0.88 (NOT 0%)
✅ All properly specified (bars, frequencies, durations)

**BUT:** The Liquidsoap rendering doesn't read or apply this data!

The "avg confidence: 0.00%" message refers to something else (DJ skills metric), not the EQ annotations.

### Root Cause

The Liquidsoap script generation (`render.py`) does NOT:
1. Read the `eq_annotation` field from transitions.json
2. Generate commands to apply the EQ effects
3. Envelope the bass cuts properly in the mix

The data exists and is correct, but it's not being USED during Liquidsoap rendering.

### Solution Options

**Option A: Pre-processing (Simpler)**
- Call dj_eq_integration.py BEFORE Liquidsoap
- Apply EQ filters to tracks before mixing
- Liquidsoap renders the already-processed tracks
- ✅ Faster implementation
- ✅ Uses proven code from Feb 17

**Option B: Liquidsoap Integration (Complex)**
- Modify Liquidsoap script generation
- Include commands to apply EQ effects
- More integrated but more complex
- ❌ Would require extensive Liquidsoap DSP coding

**Recommendation: Use Option A** - We have the code ready!

### What We Built Feb 17

File: `src/autodj/render/dj_eq_integration.py`
- `integrate_improved_drop_detector()` - 4-strategy detection
- `design_rbj_peaking_filter()` - Professional RBJ biquad filters
- `apply_professional_eq_preset()` - Envelope automation

**But it's not being called during nightly renders!**

### Evidence

The nightly log shows old code path:
```
[autodj.nightly.dj_eq] Skills: 80
```

This is `aggressive_eq_annotator.py` running, NOT the new `dj_eq_integration.py`.

### What's Wrong with the Current Approach

1. aggressive_eq_annotator generates skills with 0% confidence
2. These never make it into the transitions
3. Liquidsoap renders without EQ information
4. Bass cuts at drops don't happen

### Fix Required

**Option A: Fix aggressive_eq_annotator**
- Debug why confidence is 0%
- Make drop detection more sensitive
- Increase confidence scores

**Option B: Integrate dj_eq_integration.py (Better)**
- It has proven 4-strategy detection
- It has professional RBJ biquad filters
- It was tested and validated Feb 17
- Just need to wire it into render pipeline

**Recommendation: Option B** - Use the proven code we already built!

---

## Issue #3: Audio Glitches at Transitions

### Problem
Clicking/popping sounds at transition points where tracks meet.

### Evidence from nightly log

```
[liquidsoap] 2026/02/18 01:36:54 [cue_cut_31:3] Cueing out...
[liquidsoap] 2026/02/18 01:36:54 [stretch.consumer_29:3] Source failed (no more tracks) stopping output...
```

"Source failed (no more tracks)" suggests:
1. Track ended abruptly
2. Next track didn't start smoothly
3. No proper crossfade overlap

### Possible Causes

**1. Cue timing wrong**
- cue_in_frames / cue_out_frames not calculated correctly
- Transitions happen at wrong bar offsets
- Liquidsoap gets bad timing

**2. Overlap too short**
- overlap_bars might be 4 or 8 instead of 16+
- Not enough time for smooth crossfade
- Sudden volume drop

**3. Crossfade duration missing**
- Liquidsoap script doesn't have proper crossfade parameters
- Instant source switching instead of blend

### What Transition Data Looks Like

Each transition in transitions.json should have:
```json
{
  "overlap_bars": 16,
  "mix_out_seconds": 4.0,
  "incoming_start_seconds": 10.5,
  "cue_in_frames": 44100,
  "cue_out_frames": 1102500,
  "hpf_frequency": 200.0,
  "lpf_frequency": 2500.0
}
```

### Quick-mix Works, Nightly Doesn't

This suggests:
- quick-mix might have different transition parameters
- Or quick-mix isn't using Liquidsoap mixing
- Or nightly has some corrupt transitions

### Fix Required

1. Check transitions.json generated by nightly run
2. Verify overlap_bars and timing values
3. Check Liquidsoap script generation for crossfade parameters
4. Compare with quick-mix version

---

## Detailed Action Plan

### Step 1: Verify Playlist Issue
```bash
# Check if seed track changes nightly
grep "Using explicit seed" /home/mcauchy/autodj-headless/data/logs/nightly-*.log
# If same ID every time → Confirmed Issue #1
```

### Step 2: Verify EQ Issue
```bash
# Check if DJ EQ skills appear in transitions.json
jq '.transitions[0].dj_skills' /home/mcauchy/autodj-headless/data/playlists/transitions-*.json
# If empty or 0% confidence → Confirmed Issue #2
```

### Step 3: Verify Audio Issue
```bash
# Check transitions for overlap_bars value
jq '.transitions[].overlap_bars' /home/mcauchy/autodj-headless/data/playlists/transitions-*.json
# If < 8 or missing → Likely Issue #3
```

---

## Summary Table

| Issue | Cause | Impact | Fix |
|-------|-------|--------|-----|
| #1 | ArchwizardPhonemius + fixed seed | Same playlist nightly | Use MerlinGreedySelector, randomize seed |
| #2 | dj_eq_integration not integrated | Bass cuts don't work | Wire into render.py, use proven code |
| #3 | Short overlap / missing crossfade | Audio glitches | Verify transition times, increase overlap |

All three can be fixed within 2-3 hours with proper focus.
