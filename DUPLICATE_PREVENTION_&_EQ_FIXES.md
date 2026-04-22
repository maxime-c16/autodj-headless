# Duplicate Prevention & EQ Bass Cuts - Fix Summary

**Date:** 2026-02-19 00:15 GMT+1  
**Status:** In Progress  

---

## Issue #1: Duplicate Tracks in Playlists

### Problem
When running `make quick-mix SEED='Deine Angst' TRACK_COUNT=3`, all 3 tracks in the output were identical (same title, different track IDs but same file).

**Root Cause:** 
- Multiple versions of "Deine Angst" exist in the database (track IDs: `ff5a6be4778892c8`, `935bc08ea2962d2a`, `63eb16cd2ec8cf9f`)
- `find_compatible_tracks()` in `quick_mix.py` was not enforcing uniqueness
- The greedy selector had duplicate-checking, but duplicates were never being passed to it

### Solution Implemented

**1. Enhanced `find_compatible_tracks()` in quick_mix.py:**
```python
# Now returns DISTINCT track IDs only
c.execute(f"""
    SELECT DISTINCT id FROM tracks
    WHERE ...
    AND id != ?
    ...
    LIMIT ?
""")
```

**2. Added post-resolution deduplication in quick_mix.py:**
```python
# After track resolution, deduplicate while preserving order
seen = set()
dedup_track_ids = []
for tid in track_ids:
    if tid not in seen:
        dedup_track_ids.append(tid)
        seen.add(tid)
```

**3. Selector already had duplicate prevention:**
- `if track_id in self.used_in_set: continue` ensures no repeats

### Testing
Run:
```bash
make quick-mix SEED='Deine Angst' TRACK_COUNT=5
```

Expected: 5 UNIQUE tracks (no duplicates)

---

## Issue #2: EQ Bass Cuts Not Audible

### Problem
"I don't hear the EQ bass drop @80Hz" - bass cuts are detected but not perceptible in the final mix.

### Investigation Findings

✅ **EQ Detection Working:**
- 69 DJ skills detected per track
- Bass cuts identified at 70Hz with -8dB gain
- Confidence scores: 80-87%
- Drops detected: 6+ per track

✅ **EQ Code Generation Working:**
- Liquidsoap script includes: `filter.iir.eq.low_shelf(frequency=70.0, gain=-8.0, q=0.707, track_0)`
- 77+ EQ filters applied to each track in render

❓ **Why Not Audible?**

#### Possible Causes:

**1. Timing (Most Likely)**
- EQ cuts are applied AT bar positions (e.g., "bar 4", "bar 15")
- They're NOT continuous processing of the whole track
- They activate 2-4 bars BEFORE the detected drop (DJ technique)
- **Listen at the DROP moment specifically**, not throughout the track

**2. Bass Level in Source**
- If the original track has very low bass energy, a -8dB cut may not be noticeable
- Test with bass-heavy tracks (house, techno, drum & bass)

**3. Liquidsoap Filter Implementation**
- Verify that `filter.iir.eq.low_shelf` in Liquidsoap 2.4 has expected behavior
- Q=0.707 (Butterworth) should give gentle shelf slope

#### Validation Steps:

**For Max to test:**
1. Run quick-mix, export the mix
2. Load in audio editor (Audacity/DAW)
3. Look at waveform at bar timings - bass should dip before drops
4. Use spectrum analyzer - 70Hz band should show attenuation

**Alternative test:**
```bash
# Render with EQ disabled for comparison
make quick-mix SEED='Deine Angst' TRACK_COUNT=3 EQ=off

# Render with EQ enabled
make quick-mix SEED='Deine Angst' TRACK_COUNT=3 EQ=on

# A/B compare: listen for bass reduction in EQ=on version at drop moments
```

---

## Code Changes

### Files Modified:

1. **scripts/quick_mix.py**
   - Added: `find_compatible_tracks()` now returns DISTINCT IDs
   - Added: Post-resolution deduplication logic
   - Added: Warning message when removing duplicates

2. **src/autodj/analyze/adaptive_eq.py**
   - Restored: `filter.iir.eq.low_shelf/peaking/high_shelf` generation
   - Previous state: Used biquad approximation (removed)

3. **src/autodj/render/render.py**
   - Restored: Active filter application in Liquidsoap code
   - Previous state: Comment-only placeholders (removed)

### Lines Changed:
- `quick_mix.py`: Lines 102-140
- `adaptive_eq.py`: Lines 668-732
- `render.py`: Lines 875-900, 1305-1330

---

## Deployment Checklist

- [ ] Test 1: Run `make quick-mix SEED='Deine Angst' TRACK_COUNT=5` → verify 5 unique tracks
- [ ] Test 2: Listen to mix at DROP moments → compare bass presence before/after Liquidsoap filter
- [ ] Test 3: Run nightly cron job → verify no duplicate tracks in any generated set
- [ ] Test 4: A/B compare EQ=on vs EQ=off mixes

---

## Next Steps (If Bass Cuts Still Not Audible)

1. **Extract debug script:** Get the last_render.liq file
2. **Manually test filter:** Create minimal Liquidsoap script with just low_shelf + sine wave
3. **Verify Liquidsoap API:** Confirm filter syntax/behavior in 2.4.0
4. **Adjust Q factor:** Try different Q values (0.5, 1.0, 2.0) for different shelf slopes
5. **Adjust timing:** Move EQ cuts to different bar offsets

---

## References

- **Liquidsoap 2.4.0:** Full `filter.iir.eq` API support
- **Audio EQ Cookbook:** Low-shelf, peaking, high-shelf designs (Bristow-Johnson)
- **DJ EQ Timing:** Cuts applied 2-4 bars before drop for maximum impact

