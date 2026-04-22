# Pipeline Modification Plan: DJ Techniques Integration

## Current Pipeline (Before)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. ANALYZE PHASE                                                │
│    ├─ Spectral analysis (aubio)                                 │
│    ├─ Harmonic analysis (Camelot wheel)                         │
│    ├─ BPM detection                                             │
│    └─ Output: Track metadata + cues                             │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. GENERATE PHASE (Merlin Selector)                             │
│    ├─ Select tracks (greedy algorithm)                          │
│    ├─ Create basic transitions (8-16 bar overlap)               │
│    └─ Output: playlist.m3u + transitions.json                   │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. RENDER PHASE (Liquidsoap)                                    │
│    ├─ Generate .liq script                                      │
│    ├─ Apply EQ (current: limited)                               │
│    ├─ Execute liquidsoap                                        │
│    └─ Output: Final MP3 mix                                     │
└─────────────────────────────────────────────────────────────────┘
```

**Problem:** Transitions wait until track end (playlist behavior), no intelligent bass control

---

## New Pipeline (After)

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. ANALYZE PHASE (UNCHANGED)                                    │
│    ├─ Spectral analysis (aubio)                                 │
│    ├─ Harmonic analysis (Camelot wheel)                         │
│    ├─ BPM detection                                             │
│    └─ Output: Track metadata + cues                             │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. GENERATE PHASE (Merlin Selector + DJ TECHNIQUES)             │
│    ├─ Select tracks (greedy algorithm)                          │
│    ├─ Create base transitions (8-16 bar overlap)                │
│    │                                                            │
│    ├─ ✨ NEW: Phase 1 - Early Transitions                       │
│    │   └─ Adjust transition_start: outro_start - 16 bars       │
│    │                                                            │
│    ├─ ✨ NEW: Phase 2 - Bass Cut Control                        │
│    │   ├─ Analyze bass energy (incoming/outgoing)              │
│    │   ├─ Decide: should_apply_bass_cut()                      │
│    │   └─ Calculate: hpf_frequency, cut_intensity              │
│    │                                                            │
│    ├─ ✨ NEW: Phase 4 - Dynamic Variation                       │
│    │   ├─ 60% gradual vs 40% instant transitions               │
│    │   ├─ Vary timing ±2 bars                                  │
│    │   └─ Vary cut intensities (50-80%)                        │
│    │                                                            │
│    └─ Output: transitions.json with Phase fields                │
└────────┬────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. RENDER PHASE (Liquidsoap + EQ Automation)                    │
│    ├─ Generate .liq script                                      │
│    │                                                            │
│    ├─ ✨ NEW: Apply Phase 1 timing                              │
│    │   └─ Mix incoming at transition_start (not track end)     │
│    │                                                            │
│    ├─ ✨ NEW: Apply Phase 2 bass cut                            │
│    │   ├─ HPF filter on incoming (200 Hz cutoff)               │
│    │   └─ Fade in bass over unmask_duration_bars               │
│    │                                                            │
│    ├─ ✨ ENHANCED: EQ automation                                │
│    │   └─ More sophisticated with DJ parameters                │
│    │                                                            │
│    ├─ Execute liquidsoap                                        │
│    └─ Output: Final MP3 mix (DJ quality)                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Changes Summary

### MODIFIED (Changes Required)

#### 1. `src/autodj/generate/playlist.py`
**What changes:**
- Import Phase 1, 2, 4 calculators
- After creating base transitions, call:
  ```python
  enhanced = enhance_transition_plan_with_early_timing(trans, spectral)
  enhanced = enhance_transition_with_bass_cut(enhanced, spectral_in, spectral_out)
  enhanced = apply_dynamic_variation(enhanced, config)
  ```
- Add DJ technique configuration options (enable/disable each phase)

**Lines affected:** ~20-30 new lines (minimal)  
**Backward compatible:** YES (phases can be disabled)

#### 2. `src/autodj/render/render.py`
**What changes:**
- Import Phase 1-2 Liquidsoap generators
- In `_build_transition_script()`:
  - Read `phase1_transition_start_seconds` from transition dict
  - Adjust mixing point (instead of using default)
  - Generate bass cut filter code if `phase2_bass_cut_enabled`
  - Apply filter to incoming track stream

**Lines affected:** ~50-60 new lines (in transition building section)  
**Backward compatible:** YES (checks for presence of phase fields)

#### 3. `src/autodj/render/transitions.liq` (Liquidsoap template)
**What changes:**
- Add HPF filter application in transition overlap section
- Use cue points from Phase 1 timing
- Parameter variables for bass cut frequency/intensity

**Lines affected:** ~15-20 new lines  
**Backward compatible:** YES (template adjusts dynamically)

---

### ADDED (New Files)

#### Already Implemented:
- ✅ `src/autodj/render/phase1_early_transitions.py` (400 LOC)
- ✅ `src/autodj/render/phase2_bass_cut.py` (530 LOC)
- ✅ `src/autodj/render/phase4_variation.py` (TBD - will implement)

#### Test Files:
- ✅ `tests/test_phase1_phase2.py` (24 tests passing)

#### Documentation:
- ✅ All architecture + progress docs

---

### UNCHANGED (No Changes)

- ✅ `src/autodj/analyze/` - Spectral/harmonic analysis untouched
- ✅ `src/autodj/db.py` - Database layer
- ✅ `src/autodj/config.py` - Config (just add new options)
- ✅ `src/autodj/generate/selector.py` - Merlin selector
- ✅ FFmpeg/Liquidsoap executables - No changes needed

---

## Implementation Order

### Step 1: Phase 4 - Dynamic Variation Engine
**Why first:** Enables randomization of Phases 1-2  
**Effort:** 3-4 hours  
**Output:** `phase4_variation.py` + tests

### Step 2: Modify playlist.py
**What:** Add calls to all phase calculators  
**Effort:** 1-2 hours  
**Backward compatible:** YES

### Step 3: Modify render.py
**What:** Implement Phase 1 timing + Phase 2 bass filter  
**Effort:** 2-3 hours  
**Backward compatible:** YES

### Step 4: Integration Testing
**What:** Test on real tracks with full pipeline  
**Effort:** 2-3 hours  
**Output:** Before/after comparison

### Step 5: Rusty Chains Showcase
**What:** Generate full album mix with all phases active  
**Effort:** 1-2 hours  
**Output:** Showcase MP3 + analysis

---

## Configuration Changes

### New Config Options (in `config.py`)

```python
# DJ Techniques Configuration
DJ_TECHNIQUES_ENABLED = True  # Master switch

# Phase 1: Early Transitions
PHASE1_EARLY_START_ENABLED = True
PHASE1_BARS_BEFORE_OUTRO = 16  # 8, 16, or 32
PHASE1_TIMING_MODEL = "adaptive"  # or "fixed"

# Phase 2: Bass Cut Control
PHASE2_BASS_CUT_ENABLED = True
PHASE2_HPF_FREQUENCY = 200.0  # Hz
PHASE2_CUT_INTENSITY_MIN = 0.50
PHASE2_CUT_INTENSITY_MAX = 0.80

# Phase 4: Dynamic Variation
PHASE4_VARIATION_ENABLED = True
PHASE4_GRADUAL_RATIO = 0.60  # 60% gradual
PHASE4_INSTANT_RATIO = 0.40   # 40% instant
```

---

## Data Flow Changes

### transitions.json Schema (Before)
```json
{
  "track_id": 1,
  "next_track_id": 2,
  "bpm": 128,
  "transition_type": "bass_swap",
  "overlap_bars": 8,
  "file_path": "..."
}
```

### transitions.json Schema (After - Enhanced)
```json
{
  "track_id": 1,
  "next_track_id": 2,
  "bpm": 128,
  
  "phase1_early_start_enabled": true,
  "phase1_transition_start_seconds": 222.5,
  "phase1_transition_end_seconds": 230.0,
  "phase1_transition_bars": 16,
  
  "phase2_bass_cut_enabled": true,
  "phase2_hpf_frequency": 200.0,
  "phase2_cut_intensity": 0.65,
  "phase2_strategy": "instant",
  "phase2_unmask_delay_bars": 4,
  
  "phase4_transition_strategy": "gradual",
  "phase4_timing_variation": 1.2,
  "phase4_intensity_variation": 0.68,
  
  "file_path": "..."
}
```

---

## Performance Impact

| Operation | Before | After | Impact |
|-----------|--------|-------|--------|
| Playlist generation | ~500ms | ~600ms | +100ms (20% more, acceptable) |
| Per-transition calc | <1ms | ~2ms | Negligible |
| Render time | ~2min (30min set) | ~2min | No change (Liquidsoap bottleneck) |
| File size (transitions.json) | 15KB | 25KB | +10KB (negligible) |

---

## Rollback Plan

If issues arise:
1. Set `DJ_TECHNIQUES_ENABLED = False` in config
2. All phases check this flag and skip processing
3. Pipeline reverts to original behavior immediately
4. No data loss, no destructive changes

---

## Testing Strategy

### Unit Tests (Already Done)
✅ 24 tests for Phase 1-2 (all passing)

### Integration Tests (To Do)
1. Test full pipeline with DJ techniques enabled
2. Test with DJ techniques disabled (verify fallback)
3. Compare output: playlist-mode vs DJ-mode (spectral analysis)
4. Edge cases: weak basslines, short tracks, unusual BPMs

### Audio Validation (To Do)
1. Generate 5-minute test set
2. A/B comparison: before/after
3. Spectrogram analysis (bass frequency content)
4. Listening test (natural vs artificial feel)

---

## Summary of Changes

| Category | Count | Status |
|----------|-------|--------|
| **Modified files** | 2 | Ready |
| **New modules** | 3 | Ready (Phase 1-2 done, Phase 4 TBD) |
| **Lines added** | ~150 | Minimal footprint |
| **Breaking changes** | 0 | 100% backward compatible |
| **Config changes** | 8 new options | All optional |
| **Database changes** | 0 | None |
| **Test coverage** | 24 tests | All passing |

---

**Impact:** Professional DJ mixing behavior added to pipeline with minimal changes and zero breaking modifications. ✅
