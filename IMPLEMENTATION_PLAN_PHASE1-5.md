# Phase 1/5 v2 Script Generator - Implementation Plan

**Status:** 🔍 DIAGNOSTIC PHASE  
**Subagent:** Implementation Manager  
**Created:** 2026-02-25  
**Target Completion:** TBD  

---

## Executive Summary

This plan outlines the fixes needed to fully integrate Phase 1 (Early Transitions) and Phase 5 (Micro-Techniques) into the v2 Liquidsoap script generator.

### Current State
- ✅ Phase 1 module exists: `src/autodj/render/phase1_early_transitions.py`
- ✅ Phase 5 module exists: `src/autodj/render/phase5_micro_techniques.py`
- ✅ Entry point exists: `render_with_all_phases.py`
- ❌ **Phase 1 not rendering:** Early transition timing parsed but not applied to script generation
- ❌ **Phase 5 not rendering:** Micro-techniques structures exist but not applied to DSP effects
- ❌ **Numpy issue:** Potential shape mismatch in audio processing (needs confirmation)

### Target Outcome
By completion:
1. Phase 1: 16-bar early transitions render with proper timing in Liquidsoap
2. Phase 5: Bar-level micro-techniques (bass cuts, rolls, sweeps) render with DSP automation
3. No audio errors or numpy broadcasting issues
4. All three phases (0, 1, 5) work seamlessly together in single render

---

## ISSUE #1: Numpy Broadcasting Error

### Details
- **Error Pattern:** "operands could not be broadcast together with shapes (260124,2) (260124,)"
- **Likely Location:** Audio processing with mono/stereo channel mismatch
- **Candidate Files:**
  - `src/autodj/render/eq_applier.py` (line ~350-400)
  - `src/autodj/render/eq_preprocessor.py`
  - Any audio filter applying to multi-channel audio

### Root Cause Analysis
The error `(260124,2) (260124,)` suggests:
- Audio array: shape (260124, 2) = 130,062 stereo samples (mono channels)
- Operation: trying to broadcast with shape (260124,) = single dimension
- **Problem:** Likely applying a 1D filter to 2D stereo audio without proper channel handling

### Examples of Problematic Code Patterns
```python
# ❌ WRONG: Applies 1D array to 2D stereo
filtered = filter.iir.butterworth.high(audio)  # audio is (260124, 2)
result = audio * envelope  # envelope is (260124,)

# ✅ CORRECT: Process channels separately or expand envelope
filtered = np.apply_along_axis(lambda ch: filter_func(ch), 0, audio)
# OR
result = audio * envelope[:, np.newaxis]  # Expand to (260124, 1)
```

### Investigation Steps
1. **Search for numpy operations** on multi-channel audio
2. **Identify all filter applications** (scipy.signal, custom filters)
3. **Check audio loading** - confirm stereo vs mono handling
4. **Trace envelope application** - ensure broadcast-compatible shapes

### Fix Approach
- Add channel-aware filtering functions
- Test with both mono and stereo files
- Validate shape compatibility before all operations
- Add unit tests for edge cases

---

## ISSUE #2: Phase 1 Not Rendering

### Details
- **Early Transition Enabled Flag:** Parsed from JSON but not used in script generation
- **Missing:** 16-bar vs 32-bar timing calculation
- **Missing:** Script generation for early blend timing

### What Phase 1 Should Do
1. **Read** `early_transition_enabled` flag from transition metadata
2. **Calculate** transition start time: `outro_start - (16 bars in seconds)`
3. **Calculate** transition duration: 16-32 bars based on config
4. **Render** Liquidsoap script with early blend timing

### Current Code Status
```
✅ Module exists:
   - EarlyTransitionParams class
   - EarlyTransitionCalculator class
   - calculate_early_transition() method

❌ NOT USED:
   - phase1_enabled flag checked but not applied in render.py
   - transition timing not passed to Liquidsoap script generation
   - 16-bar calculation exists but never called
```

### Expected Liquidsoap Script Changes
**BEFORE (current):**
```liquidsoap
# Transition at track end (standard playlist behavior)
outgoing = single("track1.mp3")  # Start playing
# ... (track plays for 3+ minutes)
incoming = single("track2.mp3")  # Start when track1 ends
# Fade out/in at phrase boundaries
```

**AFTER (with Phase 1):**
```liquidsoap
# Early blend: Start track2 while track1 still playing (16 bars before outro)
outgoing = single("track1.mp3")  # Starts at 0:00
incoming = single("track2.mp3")  # Starts at ~2:45 (16 bars before outro at 3:00)
# Both playing simultaneously for 16-32 bars
# Track1 fades out while Track2 blends in
```

### Implementation Tasks
1. **Modify render.py** line ~800:
   - Check `phase1_enabled` flag
   - Call `EarlyTransitionCalculator.calculate_early_transition()`
   - Pass timing to script generation

2. **Modify v2 script generator** (render.py ~1200-1400):
   - Accept phase1_transition_start_bar parameter
   - Generate `begin()` timing for incoming track
   - Adjust fade timing based on early_start offset

3. **Test with actual transitions:**
   - Verify 16-bar calculation
   - Confirm script timing is correct
   - Listen for clean blend point

---

## ISSUE #3: Phase 5 Micro-Techniques Not Rendering

### Details
- **Data Structure:** Exists in `phase5_micro_techniques.py`
- **Database:** 10 peer-approved techniques defined
- **Missing:** Rendering to actual Liquidsoap DSP automation

### What Phase 5 Should Do
1. **Read** `phase5_micro_techniques` array from transition metadata
2. **For each technique:**
   - Extract type (STUTTER_ROLL, BASS_CUT_ROLL, FILTER_SWEEP, etc.)
   - Extract timing (bar, duration)
   - Extract parameters (frequencies, automation curve)
3. **Render** Liquidsoap filter effects at precise bar positions

### Current Code Status
```
✅ Module exists:
   - MicroTechniqueDatabase class
   - 10 technique specifications
   - Duration/timing definitions
   - Liquidsoap templates

❌ NOT USED:
   - phase5_enabled flag checked but not applied
   - Micro-techniques metadata read but never passed to script generator
   - Templates exist but never instantiated or rendered
```

### Expected Liquidsoap Script Changes
**BEFORE (current):**
```liquidsoap
# Simple crossfade, no effects
fade(type="sin", 4.0, from_db=-inf, to_db=0.0, incoming)
```

**AFTER (with Phase 5 micro-techniques):**
```liquidsoap
# 16 bars in: Bass Cut + Roll (2-4 bars)
incoming = filter.iir.butterworth.high(cutoff = 350.0)(incoming)  # Remove bass
incoming = stutter(duration = 2.0, loop_length = 0.25)(incoming)  # Add rolls

# 24 bars in: Filter Sweep (4 bars)
def sweep_lp(s) =
  lpf_curve = envelope with sweep from 2000Hz to 20000Hz over 4 bars
  filter.iir.butterworth.low(cutoff = lpf_curve)(s)
end
incoming = sweep_lp(incoming)

# Mix with crossfade
fade(type="sin", 4.0, from_db=-inf, to_db=0.0, incoming)
```

### 10 Techniques to Implement
| Technique | Duration | Implementation |
|-----------|----------|-----------------|
| Stutter Roll | 1-2 bars | `stutter()` with variable loop_length |
| Bass Cut Roll | 2-4 bars | `hpf()` + `stutter()` combined |
| Filter Sweep | 4-8 bars | `lpf()` with automation envelope |
| Echo Out Return | 2-4 bars | `delay()` with feedback automation |
| Quick Cut Reverb | 1 bar | `filter()` with sharp cutoff |
| Loop Stutter Accel | 1-4 bars | `stutter()` with accelerating tempo |
| Mute Dim | 1-2 bars | Volume automation or silence |
| High Mid Boost | 2 bars | Peaking EQ on 2-6kHz |
| Ping Pong Pan | 1 bar | `panning()` with rapid automation |
| Reverb Tail Cut | 1-2 bars | `reverb()` with fade-out |

### Implementation Tasks
1. **Create Phase5Renderer class** in render.py:
   - Read phase5_micro_techniques from metadata
   - Select applicable techniques based on track type
   - Generate Liquidsoap code for each technique

2. **Implement each technique** as Liquidsoap codegen:
   - `generate_stutter_roll(duration_bars, loop_length)`
   - `generate_bass_cut_roll(duration_bars, hpf_freq)`
   - `generate_filter_sweep(duration_bars, start_freq, end_freq)`
   - ... etc for all 10

3. **Integrate into v2 script generation:**
   - Accept phase5_techniques parameter in render()
   - Apply each technique at correct bar timing
   - Ensure smooth crossfades between techniques

4. **Test with actual transitions:**
   - Verify audio quality (no artifacts)
   - Confirm timing accuracy
   - Listen for professional DJ feel

---

## Implementation Workflow

### Phase 0: Diagnosis ✅ (IN PROGRESS)
- [x] Read segment_eq_strategies.py
- [x] Read phase1_early_transitions.py
- [x] Read phase5_micro_techniques.py
- [x] Read render.py (first 200 lines)
- [x] Identify integration points
- [ ] **WAIT for RESEARCH_FINDINGS.md** from research manager with:
  - Exact line causing numpy error
  - Test case reproducing the error
  - Audio file characteristics (mono/stereo/channels)

### Phase 1: Numpy Fix 🔧 (BLOCKED ON RESEARCH)
**Prerequisites:** Exact error location and test case from research

1. Locate broadcasting error in code
2. Add channel-aware audio processing
3. Validate shape compatibility
4. Test with mono and stereo files
5. Verify no regression in working pathways

### Phase 2: Phase 1 Integration 🎵
**Prerequisites:** Numpy fix complete

1. Modify render.py to check `phase1_enabled` flag
2. Call `EarlyTransitionCalculator` for each transition
3. Pass transition timing to v2 script generator
4. Generate Liquidsoap `begin()` timing for incoming track
5. Test 16-bar early transitions

### Phase 3: Phase 5 Integration 🎛️
**Prerequisites:** Phase 1 complete

1. Create Phase5Renderer class in render.py
2. Implement all 10 micro-technique generators
3. Parse phase5_micro_techniques from metadata
4. Apply each technique at correct bar position
5. Test all 10 techniques individually
6. Test combination of techniques

### Phase 4: Integration Testing 🧪
**Prerequisites:** All fixes complete

1. Run render_with_all_phases.py
2. Verify all phases render without errors
3. Listen to output for quality
4. Check Liquidsoap script for syntax
5. Validate timing accuracy

### Phase 5: Documentation & Deployment 📝
1. Update MEMORY.md with implementation details
2. Document each fix with rationale
3. Create test cases for regression prevention
4. Update project README with new capabilities

---

## Key Files to Modify

### Primary Files
| File | Lines | Change Type | Priority |
|------|-------|-------------|----------|
| `src/autodj/render/render.py` | ~800, ~1200-1400 | Add phase1/phase5 logic | HIGH |
| `src/autodj/render/eq_applier.py` | ~350-400 | Fix numpy broadcasting | HIGH |
| `src/autodj/render/phase1_early_transitions.py` | Integration point | Call from render.py | HIGH |
| `src/autodj/render/phase5_micro_techniques.py` | Codegen templates | Instantiate in render.py | HIGH |
| `render_with_all_phases.py` | ~50-70 | Verify config passes flags | MEDIUM |

### Supporting Files (Read-only)
- `src/autodj/render/segment_eq_strategies.py` (reference for EQ patterns)
- `src/autodj/render/segmenter.py` (understand segment timing)
- `src/autodj/analyze/confidence_validator.py` (Phase 0 patterns)

---

## Testing Strategy

### Unit Tests
```python
# Test Phase 1
test_early_transition_calculation()
test_16_bar_timing()
test_32_bar_timing()

# Test Phase 5
test_stutter_roll_generation()
test_bass_cut_roll_generation()
test_filter_sweep_generation()
test_all_10_techniques()

# Test Numpy Fix
test_mono_audio_processing()
test_stereo_audio_processing()
test_shape_compatibility()
```

### Integration Tests
```python
# Test all phases together
test_render_with_all_phases_enabled()
test_liquidsoap_script_syntax()
test_audio_output_quality()
test_transition_timing_accuracy()
```

### Manual Testing
1. Render test mix with Phase 1 + Phase 5 enabled
2. Listen for smooth transitions
3. Verify early blend timing (should hear track 2 before track 1 ends)
4. Verify micro-techniques (bass cuts, rolls, sweeps)
5. Check for audio artifacts or glitches

---

## Success Criteria

| Criterion | Status | Measurement |
|-----------|--------|-------------|
| Numpy error fixed | ❌ TODO | No broadcasting errors in render |
| Phase 1 renders | ❌ TODO | Liquidsoap script includes `begin()` timing |
| Phase 5 renders | ❌ TODO | Script includes `stutter()`, `hpf()`, `lpf()` effects |
| All phases work together | ❌ TODO | render_with_all_phases.py completes successfully |
| Audio quality maintained | ❌ TODO | Manual listening test passes |
| No regressions | ❌ TODO | Existing render tests still pass |

---

## Blocking Issues & Questions

### For Research Manager
1. **Numpy Error:**
   - What is the exact error location (file + line)?
   - What audio file triggers the error (mono/stereo/sample rate)?
   - Can you provide a minimal test case?

2. **Phase 1 / Phase 5 Data:**
   - What does the `phase5_micro_techniques` metadata look like?
   - What values are in `early_transition_enabled` field?
   - Are there example transition JSONs with both fields populated?

3. **Liquidsoap API:**
   - What version of Liquidsoap is deployed?
   - Are there working examples of `stutter()`, `hpf()`, `lpf()` with Liquidsoap 2.1.3?
   - Any known limitations with multi-effect chains?

### For Main Agent (Maxime)
- Should I wait for research findings before starting Phase 1/5 implementation?
- Can you provide a test audio file that triggers the numpy error?
- What is the priority order: Fix numpy error → Phase 1 → Phase 5?

---

## Time Estimates

| Task | Duration | Status |
|------|----------|--------|
| Diagnosis (this document) | 1-2 hours | ✅ DONE |
| Numpy fix (with test case) | 2-4 hours | ⏳ BLOCKED |
| Phase 1 integration | 3-4 hours | ⏳ WAITING |
| Phase 5 implementation | 5-8 hours | ⏳ WAITING |
| Integration testing | 2-3 hours | ⏳ WAITING |
| Documentation | 1-2 hours | ⏳ WAITING |
| **TOTAL** | **14-24 hours** | 1-2 days with focus |

---

## Notes for Future Work

### Quick Wins (If No Blockers)
1. Review render.py integration points (already done)
2. Create Phase5Renderer skeleton class
3. Implement 1-2 micro-techniques as proof-of-concept
4. Set up test infrastructure

### Nice-to-Have Improvements
- Cache Liquidsoap script compilation for faster iterations
- Add progress bar to render_with_all_phases.py
- Create listening guide for each micro-technique
- Implement technique selector based on mood/genre

---

## Reference Materials

- [BASS_EQ_BUG_FIX_SESSION_SUMMARY.md](./BASS_EQ_BUG_FIX_SESSION_SUMMARY.md) - Previous EQ bug fix session
- [phase1_early_transitions.py](./src/autodj/render/phase1_early_transitions.py) - Phase 1 module
- [phase5_micro_techniques.py](./src/autodj/render/phase5_micro_techniques.py) - Phase 5 module
- [render.py](./src/autodj/render/render.py) - v2 script generator (main integration point)

---

**Prepared by:** Implementation Subagent  
**Next Step:** Await RESEARCH_FINDINGS.md or proceed with available information  
**Last Updated:** 2026-02-25
