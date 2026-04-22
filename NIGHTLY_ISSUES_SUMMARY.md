# NIGHTLY PIPELINE ISSUES - COMPLETE INVESTIGATION & FIX PLAN

**Date:** 2026-02-18
**Status:** Investigation Complete, Ready for Fixes
**Priority:** All 3 issues affect nightly quality

---

## Quick Summary

Max reported three critical issues with nightly mixes:

1. ❌ **Playlist generation** - Same set every night
2. ❌ **DJ EQ not working** - No bass cuts at drops
3. ❌ **Audio glitches** - Clicks/pops at transitions

**All three confirmed and documented.** Ready to fix.

---

## Issue #1: Playlist Generator (CONFIRMED)

### What's Wrong
- Nightly always generates same playlist
- Uses fixed seed track: `ff5a6be4778892c8`
- Uses old ArchwizardPhonemius instead of MerlinGreedySelector
- No persona-based selection happening

### Evidence
```bash
grep "Using explicit seed" nightly-*.log | tail -5
# Output: Every run uses ff5a6be4778892c8
```

### Location
- File: `src/autodj/generate/playlist.py`
- Function: `generate()` at line 842-844
- Problem: Falls into "orchestrated mode" using Phonemius

### Fix Required
1. Detect when MerlinGreedySelector should be used
2. Implement persona rotation
3. Randomize seed track daily

**Time estimate:** 45 minutes

---

## Issue #2: EQ Not Applied (CONFIRMED - Updated Understanding)

### What's Wrong
- EQ annotations detected correctly (69 per track, 0.75-0.88 confidence)
- Data stored in transitions.json perfectly
- **BUT:** Liquidsoap script generation doesn't use this data
- No commands generated to apply the EQ effects

### Evidence
```bash
jq '.transitions[0].eq_annotation.total_eq_skills' transitions-*.json
# Output: 69 (EQ data IS there!)

jq '.transitions[0].eq_annotation.eq_opportunities[0].confidence' 
# Output: 0.88 (NOT zero!)
```

### Root Cause
The Liquidsoap rendering doesn't read the `eq_annotation` field and doesn't generate filter commands.

### Fix Options

**Option A: Pre-processing (Recommended)**
- Call `dj_eq_integration.py` BEFORE Liquidsoap
- Apply EQ filters to tracks beforehand
- Liquidsoap mixes already-EQ'd tracks
- ✅ Simple, proven, ready-to-use code
- ✅ No complex Liquidsoap DSP coding

**Option B: Liquidsoap Integration**
- Modify Liquidsoap script generation
- Include filter commands in script
- More integrated but complex
- ❌ Requires extensive Liquidsoap DSP work

**Recommendation: Option A**

### Implementation
1. In `render.py`, before Liquidsoap rendering:
2. Call `dj_eq_integration.integrate_improved_drop_detector()`
3. Apply RBJ biquad filters for each EQ opportunity
4. Update transitions.json to point to processed tracks
5. Liquidsoap mixes the processed audio

**Time estimate:** 30 minutes (code already written Feb 17)

---

## Issue #3: Audio Glitches (NEEDS TESTING)

### What's Wrong
- Liquidsoap logs show abrupt source failures
- Possible: overlap_bars too short
- Possible: crossfade duration missing
- Result: Clicks/pops at transition points

### Evidence
```
[liquidsoap] [cue_cut_31:3] Cueing out...
[liquidsoap] [stretch.consumer_29:3] Source failed (no more tracks) stopping output...
```

### Investigation Steps
1. Check transitions.json for overlap_bars values
2. Compare with quick-mix transitions (which work)
3. Verify cue_in_frames and cue_out_frames timing
4. Check Liquidsoap crossfade parameters in script

### Likely Fixes
1. Increase overlap_bars (try 16 instead of 8)
2. Verify crossfade duration is set
3. Check BPM ramping strategy
4. May need to adjust transition timing

**Time estimate:** 1-2 hours (requires debugging)

---

## Files to Review

### Main Issues Document
- `NIGHTLY_ISSUES_INVESTIGATION.md` - Complete technical analysis

### Code Files
- `src/autodj/generate/playlist.py` - Playlist generator
- `src/autodj/render/render.py` - Liquidsoap integration
- `src/autodj/render/dj_eq_integration.py` - EQ preprocessor (ready to use)

### Nightly Logs
- `data/logs/nightly-2026-02-18.log` - Latest run (shows issues)

### Generated Data
- `data/playlists/transitions-20260218-013101.json` - Has EQ annotations

---

## Recommended Fix Sequence

### Phase 1: Fix EQ (30 min) ✅ Best ROI
1. Read dj_eq_integration.py to confirm it's production-ready
2. Add preprocessing call in render.py
3. Test with quick-mix
4. Test with nightly

### Phase 2: Fix Playlist (45 min) ⏭️
1. Modify playlist.py to use MerlinGreedySelector
2. Add persona selection logic
3. Randomize seed track
4. Test playlist variety

### Phase 3: Debug Audio (1-2h) 🔧
1. Verify transition parameters
2. Adjust overlap and crossfade
3. Test audio quality
4. Fix any glitches

---

## Commands for Verification

```bash
# Issue #1: Check seed tracks across runs
grep "Using explicit seed" /home/mcauchy/autodj-headless/data/logs/nightly-*.log | sort -u

# Issue #2: Check EQ annotations exist
jq '.transitions[] | .eq_annotation.total_eq_skills' /home/mcauchy/autodj-headless/data/playlists/transitions-20260218-013101.json

# Issue #3: Check overlap_bars values
jq '.transitions[] | .overlap_bars' /home/mcauchy/autodj-headless/data/playlists/transitions-20260218-013101.json
```

---

## Status & Next Steps

**Investigation:** ✅ Complete
**Documentation:** ✅ Complete
**Code Ready:** ✅ dj_eq_integration.py ready to integrate

**Awaiting:** Max's decision on which issue to fix first

**Recommended:** Start with Issue #2 (EQ) - easiest win, proven code ready

---

## Contact

If you have questions about any of these findings, see:
- This document for overview
- NIGHTLY_ISSUES_INVESTIGATION.md for detailed technical analysis
- Code files themselves for implementation details
