# AutoDJ Professional DJ Techniques - Implementation Architecture

## Overview
Implementing 5 phases of professional DJ mixing techniques into the autodj-headless pipeline to make generated sets sound like authentic DJ mixes rather than playlists.

**Research Base:** `/home/mcauchy/autodj-headless-research.md`  
**Current Status:** Planning + Subagent Implementation (Session ID: 7cc85180-9d89-45fe-9727-d95f1abf087b)

---

## Phase Architecture

### Phase 1: Early Transitions ⏳
**Goal:** Start mixing Track B 16+ bars before Track A's outro ends  
**Current Behavior:** Transitions happen at track end (playlist mode)  
**Target Behavior:** Transitions start at -16 bars, complete by -8 bars

**Key Changes:**
- Detect outro start point (currently in spectral analysis)
- Calculate: `transition_start = outro_start - (16_bars_in_seconds)`
- Begin mixing incoming track at calculated point
- Overlap window: 16-32 bars before outro

**Dependencies:**
- `autodj.analyze.spectral.py` - Already detects outro boundaries
- `autodj.generate.playlist.py` - Needs to adjust `overlap_bars` and timing

**Files to Modify:**
- `src/autodj/generate/playlist.py` - Transition timing logic
- `src/autodj/render/render.py` - Incorporate early start times

---

### Phase 2: Bass Cut Control ⏳
**Goal:** Apply 50-80% bass frequency cut to incoming track during overlap  
**Current Behavior:** Bass might be playing at full volume or unevenly  
**Target Behavior:** Controlled bass swap (HPF on incoming, fade in as outro releases)

**Key Changes:**
- Apply High-Pass Filter (HPF) at ~200Hz to incoming track
- Gradually unmask bass over 8-16 bars at phrase boundaries
- Intensity: 50-80% cut (not always full mute)
- Every transition should have bass management

**Dependencies:**
- `autodj.render.segment_eq_strategies.py` - Already has LADSPA/FFmpeg patterns
- Liquidsoap 2.1.3 - Has `filter.iir.butterworth.high_pass` available
- FFmpeg anequalizer - Available in container

**Files to Modify/Create:**
- `src/autodj/render/bass_swap_engine.py` (new) - Dedicated bass control
- `src/autodj/render/render.py` - Integrate bass swap into transitions
- `src/autodj/generate/playlist.py` - Add bass swap parameters

---

### Phase 3: Layered EQ ⏳
**Goal:** Frequency layering (highs → mids → bass over time)  
**Current Behavior:** No structured frequency separation during transitions  
**Target Behavior:** Progressive unmask by frequency band (professional DJ technique)

**Key Changes:**
- Mix order: Highs first (5+ kHz) → Mids (200Hz-5kHz) → Bass (20-200Hz)
- Each band unmasks over different bar counts
  - Highs: Immediate (first 2 bars)
  - Mids: Medium (4-8 bars)
  - Bass: Last (8-16 bars)
- Detect dominant frequencies in each track (spectral analysis)
- Reduce overlapping mids/highs on outgoing when incoming has strong vocals

**Dependencies:**
- `autodj.analyze.spectral.py` - Frequency band analysis
- `src/autodj/render/segment_eq_strategies.py` - FFmpeg anequalizer for 3-band control
- Liquidsoap 2.1.3 - Butterworth filters for selective bands

**Files to Modify/Create:**
- `src/autodj/render/layered_eq_engine.py` (new) - 3-band EQ sequencing
- `src/autodj/render/render.py` - Integrate into transition rendering
- `src/autodj/analyze/spectral.py` - Enhance frequency detection (if needed)

---

### Phase 4: Dynamic Variation ⏳
**Goal:** Randomize technique types to avoid repetitive patterns  
**Current Behavior:** All transitions use same technique  
**Target Behavior:** 
- 60% of transitions: Gradual EQ adjustments (8-16 bar sweep)
- 40% of transitions: Instant/quick bass swaps (4 bar or less)
- Occasional creative EQ moves (mids-only phase before drop)

**Key Changes:**
- Transition type selection: Weighted random distribution
- Vary bass swap timing ±2 bars around phrase boundary
- Vary EQ adjustment speed (gradual vs instant)
- Vary cut intensities (50-80% range, not fixed value)
- Skip bass swap occasionally on weak-bassline tracks

**Dependencies:**
- `random` module (stdlib)
- `src/autodj/analyze/spectral.py` - Detect weak basslines
- All previous phases' infrastructure

**Files to Modify/Create:**
- `src/autodj/render/variation_engine.py` (new) - Randomization logic
- `src/autodj/generate/playlist.py` - Integration with transition plan
- `src/autodj/render/render.py` - Apply variation at render time

---

### Phase 5: Integration & Testing ⏳
**Goal:** Combine all phases into cohesive pipeline with validation  
**Current Behavior:** Phases work independently  
**Target Behavior:** All phases coordinated, tested, production-ready

**Key Changes:**
- Integration point: Transition generation (playlist.py) → Rendering (render.py)
- Schema update: Add phase-specific fields to transitions.json
- Validation: Check all EQ moves make sense musically
- Testing: Unit tests + A/B comparison samples
- Documentation: Before/after audio examples

**Dependencies:**
- All previous phases
- `unittest` + `pytest`
- Audio comparison tools (spectral visualization, loudness analysis)

**Files to Modify/Create:**
- `tests/test_dj_phases_1_5.py` (new) - Comprehensive test suite
- `src/autodj/render/transitions.json.schema` (new) - Updated schema
- `docs/DJ_TECHNIQUES_IMPLEMENTATION.md` - Full documentation

---

## Implementation Timeline (Estimated)

| Phase | Effort | Status | Dependencies |
|-------|--------|--------|--------------|
| Phase 1 (Early Transitions) | 6-8 hours | ⏳ | Spectral analysis working |
| Phase 2 (Bass Control) | 5-6 hours | ⏳ | FFmpeg/LADSPA patterns verified |
| Phase 3 (Layered EQ) | 7-8 hours | ⏳ | Phase 1 + 2, spectral enhanced |
| Phase 4 (Variation) | 4-5 hours | ⏳ | All above phases |
| Phase 5 (Integration) | 6-8 hours | ⏳ | All phases complete |
| **Total** | **28-35 hours** | ⏳ | **Sequential implementation** |

---

## Data Flow

```
1. ANALYSIS PHASE (existing)
   ├─ Spectral Analysis: Detect outro, kicks, frequency content
   ├─ Harmonic Analysis: Key compatibility
   └─ BPM Detection: Tempo + confidence

2. PLAYLIST GENERATION (Phase 1 + 4)
   ├─ Select tracks (Merlin selector)
   ├─ Generate base transitions (16 bars overlap)
   └─ Apply dynamic variation (60% gradual / 40% instant)
   
3. TRANSITION PLANNING (Phase 2 + 3)
   ├─ Enhance with bass swap parameters (Phase 2)
   ├─ Add EQ layering scheme (Phase 3)
   └─ Output: transitions.json with all DJ technique fields

4. RENDERING (Phase 1-4 all applied)
   ├─ Early transition starts: Mix incoming at -16 bars
   ├─ Bass swap: Apply HPF to incoming, fade in over time
   ├─ Layered EQ: Progressive unmask (highs→mids→bass)
   ├─ Dynamic variation: Choose gradual vs instant based on plan
   └─ Output: Final mixed MP3 (DJ-quality)
```

---

## Key Decisions Made

### 1. Bass Filter Approach
**Decision:** Use FFmpeg anequalizer + Liquidsoap integration  
**Why:** Already available, 128-band control, professional quality  
**Alternative:** LADSPA CMT 1-pole HPF (simpler but less control)  
**No Changes:** Avoid Calf upgrade (not needed, FFmpeg sufficient)

### 2. Transition Timing
**Decision:** Detect outro boundaries from spectral analysis, calculate -16 bar start  
**Why:** Matches professional DJ behavior, uses existing spectral tools  
**Alternative:** Static 8-bar overlap (current, too rigid)  
**No Changes:** Keep existing overlap_bars parameter as baseline

### 3. EQ Frequency Priorities
**Decision:** Highs → Mids → Bass unmask order  
**Why:** Professional DJ standard, smoothest blends  
**Alternative:** Simultaneous unmask (muddy)  
**No Changes:** Flexible per-track based on spectral content

### 4. Variation Strategy
**Decision:** Weighted random (60% gradual, 40% instant) + parameter jitter  
**Why:** Naturalistic without being chaotic  
**Alternative:** Alternating pattern (predictable)  
**No Changes:** Allow override via config per transition

### 5. Integration Point
**Decision:** Modify playlist.py → render.py pipeline  
**Why:** Minimal changes to existing architecture  
**Alternative:** Rewrite entire render engine (risky, time-consuming)  
**No Changes:** Keep existing code structure, add new modules

---

## Testing Strategy

### Unit Tests (Phase 5)
```python
# Test early transition timing
assert transition_start == outro_start - (16 * bars_to_seconds)

# Test bass swap intensity
assert 0.50 <= bass_cut_intensity <= 0.80

# Test EQ layering order
assert eq_apply_order == ['highs', 'mids', 'bass']

# Test variation distribution
assert 0.55 < (gradual_count / total) < 0.65
assert 0.35 < (instant_count / total) < 0.45
```

### Integration Tests
- Render a 30-minute set with all 5 phases
- Compare spectrograms: Current vs DJ Techniques version
- A/B listening test: Playlist feel vs DJ set feel
- Validate no audio artifacts (clipping, phase issues)

### Validation Metrics
- ✅ Transitions start 16+ bars before outro
- ✅ Bass is cut 50-80% on incoming track
- ✅ EQ unmasks in order: highs → mids → bass
- ✅ Variation appears natural (not repetitive)
- ✅ No audio artifacts, clean audio
- ✅ Set duration correct (no cumulative drift)

---

## Dependencies Research (In Progress)

### Liquidsoap 2.1.3
- ✅ `filter.iir.butterworth.high_pass(frequency, input)` - Available
- ✅ `filter.iir.butterworth.low_pass(frequency, input)` - Available
- ⏳ Automation/envelope control for time-varying EQ - Research needed

### FFmpeg 5.9
- ✅ `anequalizer` filter - 128 bands, full control
- ⏳ Parameter automation - Research if supported

### Python Audio Libraries
- ✅ `scipy.signal` - FFT, spectral analysis (existing)
- ✅ `numpy` - Array operations (existing)
- ⏳ Audio rendering timing - Liquidsoap handles via script generation

---

## Subagent Task Delegation

**Assigned to:** `agent:main:subagent:7cc85180-9d89-45fe-9727-d95f1abf087b`

**Tasks:**
1. ✅ Read research doc + current codebase
2. ⏳ Research Liquidsoap/FFmpeg docs for EQ automation
3. ⏳ Design Phase 1 implementation (early transitions)
4. ⏳ Create `bass_swap_engine.py` module
5. ⏳ Create `layered_eq_engine.py` module
6. ⏳ Create `variation_engine.py` module
7. ⏳ Update `playlist.py` to integrate all phases
8. ⏳ Create comprehensive test suite
9. ⏳ Generate before/after comparison samples

**Expected Output:**
- Complete source code (5 new modules + modifications)
- Updated `transitions.json` schema
- Unit tests (≥80% coverage)
- Integration tests with sample output
- Documentation with code examples
- Progress report with findings

---

## Risk Mitigation

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Liquidsoap envelope limitations | Medium | High | Have LADSPA fallback ready |
| FFmpeg filter timing sync | Low | Medium | Test extensively, use Liquidsoap timing |
| Audio artifacts (clipping) | Medium | High | Gain staging + validation tests |
| Performance regression | Low | Medium | Benchmark current + new code |
| Integration complexity | Medium | High | Modular design, comprehensive tests |

---

## Success Criteria

✅ All 5 phases implemented and tested  
✅ Render output sounds like DJ mix, not playlist  
✅ No audio quality regression  
✅ ≥80% test coverage  
✅ Complete documentation + examples  
✅ Before/after comparison shows clear improvement  
✅ Config allows enabling/disabling each phase independently  

---

**Status:** Architecture documented, subagent implementing  
**Next Step:** Await subagent progress report  
**Owner:** Max + Subagent (DSP engineer)  
**Created:** 2026-02-23 12:35 GMT+1
