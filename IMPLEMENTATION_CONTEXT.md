# CONTEXT DOCUMENT FOR DSP IMPLEMENTATION AGENT
**Date:** 2026-02-06 20:31 GMT+1
**Task:** Full DSP Enhancement Implementation for AutoDJ-Headless

---

## PROJECT OVERVIEW

AutoDJ-Headless is an automated DJ mixing system that sequences music tracks with crossfades, harmonic mixing, and intelligent transitions. Current implementation is ~50% of professional quality. Task is to implement advanced DSP techniques to reach 85-90% professional quality.

**Current State:**
- ✅ BPM matching (beatmatching)
- ✅ Harmonic compatibility (Camelot wheel)
- ✅ Basic cue detection (energy-based)
- ❌ EQ automation during transitions
- ❌ Filter sweeps
- ❌ Smart loudness-aware crossfades
- ❌ Harmonic-aware transition logic
- ❌ Beat grid synchronization

---

## RESEARCH FINDINGS (From 2026-02-06 Research)

### The Three Most Impactful Techniques

1. **EQ Automation** (⭐ Most Important - 60% improvement in 3 hours)
   - Cut bass of outgoing track (prevents mud clash)
   - Boost mids of incoming track (clarity)
   - Automatically fade in/out over transition
   - Result: Dramatically smoother, more professional sound

2. **Smart Crossfade** (20% improvement in 30 min)
   - Use Liquidsoap's built-in `cross.smart()` function
   - Dynamically detects track volume
   - Chooses optimal fade strategy per situation
   - Prevents clipping automatically

3. **Filter Sweeps** (40% improvement in 4 hours)
   - High-pass sweep on incoming: track gradually comes into focus
   - Low-pass sweep on outgoing: track dissolves into bass
   - Masks ~90% of timing imperfections
   - Creates professional "opening" effect

### Additional Enhancements

4. **Harmonic-Aware Transitions** (25% improvement)
   - Compatible keys: shorter fades (3 sec)
   - Non-compatible: longer fades (5-6 sec) + filter sweep
   - Different EQ profiles per harmonic distance

5. **Enhanced Cue Detection** (30% improvement)
   - Use aubio onset detection (not just energy)
   - Snap to beat grid for precision
   - Classify cue types: intro, outro, breakdown, drop

6. **Tempo Ramping** (20% improvement)
   - Gradual BPM shift (±2% over 4 sec)
   - Smoother than instant time-stretch
   - More natural sounding

---

## IMPLEMENTATION PHASES

### PHASE 1: WEEK 1 CORE (6 hours)
**Target:** 70-75% professional quality

1. **Enable cross.smart()** (30 min)
   - File: `src/autodj/render/transitions.liq`
   - Replace stub `smart_crossfade()` with actual Liquidsoap code
   - Use built-in loudness detection

2. **Add EQ Automation** (3 hours) ⭐ PRIORITY
   - File: `src/autodj/render/render.py`
   - In `_generate_liquidsoap_script()`:
     - Create track instances with EQ filters
     - Low-pass on outgoing (100 Hz cutoff, Q=0.7)
     - High-pass on incoming (50 Hz cutoff, Q=0.7)
     - Crossfade with EQ applied
   - Test on sample mixes

3. **Enhance Cue Detection** (2 hours)
   - File: `src/autodj/analyze/cues.py`
   - Add aubio onset detection (already has aubio imported!)
   - Detect onset points more accurately
   - Classify cue types (intro, breakdown, drop)
   - Snap to beat grid

4. **Update Configuration** (30 min)
   - File: `configs/autodj.toml`
   - Add new parameters:
     - `enable_eq_automation = true`
     - `enable_filter_sweep = false` (for phase 2)
     - `eq_lowpass_frequency = 100`
     - `eq_highpass_frequency = 50`
     - `fade_type = "sin"`
     - `crossfade_duration = 4.0`

### PHASE 2: WEEK 2-3 PROFESSIONAL (11 hours)
**Target:** 85-90% professional quality

5. **Filter Sweeps** (4 hours)
   - File: `src/autodj/render/transitions.liq`
   - Implement `filter_sweep_entrance()` function
   - Hi-pass sweep (2kHz → 20kHz over 4 sec)
   - Create filter bank for band-switching approximation
   - Apply during transition

6. **Harmonic-Aware Transitions** (3 hours)
   - File: `src/autodj/render/render.py`
   - Check harmonic compatibility (you already track this!)
   - Calculate energy distance between tracks
   - Adjust transition parameters:
     - Compatible: 3 sec fade, minimal EQ
     - Non-compatible: 5 sec fade + filter sweep
   - Generate appropriate Liquidsoap code

7. **Tempo Ramping** (4 hours)
   - File: `src/autodj/render/render.py`
   - Detect BPM difference
   - Apply gradual time-stretch during transition
   - Fade in/out while tempo adjusts
   - Smoother than instant shift

### PHASE 3: ADVANCED FEATURES (Stretch goals)
**Timeline:** Month 2+

8. **Beat Grid Synchronization** (8 hours)
9. **Frequency Analysis Layer** (6 hours)
10. **Stem Separation** (12 hours, CPU intensive)

---

## CODE STRUCTURE

### Current File Locations

```
/home/mcauchy/autodj-headless/
├── src/autodj/
│   ├── render/
│   │   ├── render.py          ← Main script generation
│   │   ├── transitions.liq    ← Liquidsoap DSP functions (STUBS)
│   │   └── segmenter.py       ← Rendering pipeline
│   ├── analyze/
│   │   └── cues.py            ← Cue detection (needs aubio enhancement)
│   └── generate/
│       ├── playlist.py
│       └── selector.py
├── configs/
│   └── autodj.toml            ← Configuration (needs new params)
├── ADVANCED_DSP_IMPLEMENTATION.md  ← Reference guide
└── docs/
    └── SPEC.md                ← System specification
```

### Key Functions to Modify

**transitions.liq:**
```liquidsoap
def smart_crossfade(a, b, duration_seconds=4.0, eq_manipulation=false)
  # Currently: add(normalize=false, [a, b])
  # Needs: Implementation of cross.smart()

def filter_swap(a, b, duration_seconds=4.0)
  # Currently: add(normalize=false, [a, b])
  # Needs: Filter sweep logic

def time_stretch(audio, target_bpm_ratio=1.0, quality="high")
  # Currently: just returns audio unchanged
  # Needs: Actual time-stretching (phase 2)
```

**render.py `_generate_liquidsoap_script()`:**
```python
# Currently generates simple concatenation
# Needs:
#   1. Load each track with input.ffmpeg()
#   2. Create EQ-filtered versions (low-pass outgoing, high-pass incoming)
#   3. Apply smart_crossfade() with EQ
#   4. Add filter sweeps (phase 2)
#   5. Handle harmonic routing (phase 2)
#   6. Apply tempo ramping (phase 2)
```

**cues.py `detect_cues()`:**
```python
# Currently: Energy-based peak finding
# Needs:
#   1. Aubio onset detection (already imported!)
#   2. Beat grid alignment
#   3. Cue classification (intro/outro/breakdown/drop)
#   4. More accurate entry/exit points
```

---

## LIQUIDSOAP CODE EXAMPLES (Ready to Use)

### Example 1: Smart Crossfade
```liquidsoap
def smart_crossfade(a, b, duration=4.0)
  let fade.out = fade.out(type="sin", duration=duration)
  let fade.in = fade.in(type="sin", duration=duration)
  
  # Simple version: crossfade both tracks
  add(normalize=false, [
    fade.out(a),
    fade.in(b)
  ])
end
```

### Example 2: EQ Automation
```liquidsoap
# Generate in render.py template:
track_a = input.ffmpeg("path/to/track_a.mp3")
track_b = input.ffmpeg("path/to/track_b.mp3")

# Apply EQ filters
track_a_eq = eqffmpeg.low_pass(frequency=100., q=0.7, track_a)
track_b_eq = eqffmpeg.high_pass(frequency=50., q=0.7, track_b)

# Crossfade with EQ
result = add(normalize=false, [
  fade.out(type="sin", duration=4., track_a_eq),
  fade.in(type="sin", duration=4., track_b_eq)
])
```

### Example 3: Filter Sweep (Approximate)
```liquidsoap
def filter_sweep_entrance(source, duration=4.)
  hpf_2k = eqffmpeg.high_pass(frequency=2000., q=0.8, source)
  hpf_5k = eqffmpeg.high_pass(frequency=5000., q=0.8, source)
  hpf_10k = eqffmpeg.high_pass(frequency=10000., q=0.8, source)
  hpf_20k = eqffmpeg.high_pass(frequency=20000., q=0.8, source)
  
  sequence([
    fade.in(duration=1., hpf_2k),
    fade.in(duration=1., hpf_5k),
    fade.in(duration=1., hpf_10k),
    fade.in(duration=1., hpf_20k),
  ])
end
```

---

## TESTING PLAN

### Unit Tests
- Liquidsoap syntax validation (liq -c)
- EQ filter application (verify no errors)
- Cue detection on sample files

### Integration Tests
- Generate 5-track mix (15-20 min total)
- Verify no clipping (check peak levels)
- Verify transitions sound smooth
- Compare quality: before vs. after

### Quality Assessment
- Listening test protocol (professional DJ standard)
- Check for:
  - No clicks/pops at boundaries
  - Beat alignment (kick drums sync)
  - Frequency clarity (not muddy)
  - Energy continuity (no sudden drops)

---

## DEPENDENCIES

### Already Present
- ✅ aubio (installed, used in cues.py)
- ✅ Liquidsoap (render engine)
- ✅ FFmpeg (audio I/O)
- ✅ Python 3.9+

### May Need to Add
- ? librosa (for advanced onset detection, if needed)
- ? scipy.signal (for advanced filter design, if needed)

---

## GIT STRATEGY

- Backup commit: `backup: before DSP enhancement implementation (2026-02-06)` ✅ DONE
- Implementation commits:
  1. `feat: implement smart_crossfade in transitions.liq`
  2. `feat: add EQ automation to render pipeline`
  3. `feat: enhance cue detection with aubio onsets`
  4. `feat: add filter sweep effects (optional)`
  5. `feat: implement harmonic-aware transitions (optional)`
  6. `feat: add tempo ramping (optional)`

Each commit should be independently testable.

---

## SUCCESS CRITERIA

### Phase 1 (Week 1)
- ✅ cross.smart() working in Liquidsoap
- ✅ EQ automation applied to transitions
- ✅ Cue detection improved with aubio
- ✅ No syntax errors in generated scripts
- ✅ Test mix generates successfully
- ✅ Quality: 70-75% pro standard

### Phase 2 (Week 2-3)
- ✅ Filter sweeps implemented
- ✅ Harmonic-aware transitions routing tracks correctly
- ✅ Tempo ramping smooth and natural
- ✅ No artifacts or distortion
- ✅ Quality: 85-90% pro standard

### Overall
- Subjective listening test shows clear improvement
- Generated mixes sound professional
- Can run on 2-core server without CPU overload
- All changes tracked in git with clear history

---

## AGENT INSTRUCTIONS

### Your Task
Implement the Phase 1 enhancements (Week 1) with option to extend to Phase 2 if time allows:

1. **Read & understand** the current code:
   - transitions.liq (stubs)
   - render.py (_generate_liquidsoap_script function)
   - cues.py (detect_cues function)
   - autodj.toml (config)

2. **Implement Phase 1:**
   - [ ] Update transitions.liq with smart_crossfade using cross.smart()
   - [ ] Add EQ automation to render.py's Liquidsoap generation
   - [ ] Enhance cues.py with aubio onset detection
   - [ ] Update autodj.toml with new parameters
   - [ ] Test each change independently
   - [ ] Commit to git with clear messages

3. **Test Phase 1:**
   - [ ] Verify Liquidsoap scripts have no syntax errors
   - [ ] Generate test mix (5 tracks, ~20 min)
   - [ ] Inspect audio output (peak levels, no clipping)
   - [ ] Document results

4. **If time allows, implement Phase 2:**
   - [ ] Add filter_sweep_entrance() to transitions.liq
   - [ ] Implement harmonic-aware transition logic in render.py
   - [ ] Add tempo ramping support
   - [ ] Test combined effects
   - [ ] Commit changes

5. **Document:**
   - [ ] Update ADVANCED_DSP_IMPLEMENTATION.md with implementation notes
   - [ ] Create IMPLEMENTATION_NOTES.md with what was done & what remains
   - [ ] List any issues or edge cases encountered

### Important Notes
- **Don't break existing functionality** - preserve backward compatibility
- **Test after each major change** - use Liquidsoap -c for syntax check
- **Monitor memory usage** - keep peak under 2GB for 2-core server
- **Commit frequently** - small, clear commits make it easy to revert if needed
- **Log extensively** - add logger.info() calls for debugging

### Tools Available
- exec: Run shell commands, Python, etc.
- read: Read files
- write: Create/write files
- edit: Modify files precisely
- Remember: Use logger.info/debug/error for Python logging

---

## STARTER CHECKLIST

Before you begin:
1. [ ] Read this entire context document
2. [ ] Review ADVANCED_DSP_IMPLEMENTATION.md
3. [ ] Examine current transitions.liq (stub functions)
4. [ ] Examine render.py (_generate_liquidsoap_script)
5. [ ] Examine cues.py (current implementation)
6. [ ] Check autodj.toml (current config)
7. [ ] Verify Liquidsoap is installed & working
8. [ ] Test a simple Liquidsoap script
9. [ ] Begin implementation with Phase 1

---

## CONTACT & UPDATES

- **Monitor:** Main session (Pablo) will monitor progress
- **Questions:** If stuck, report status and ask for clarification
- **Time Budget:** Estimate 6 hours for Phase 1, 11 more for Phase 2
- **Update Frequency:** Status report after each major milestone

---

**Good luck! This is substantial work but very doable. The research is done, the code examples are ready, and you have clear phases to follow. Focus on Phase 1 first, test thoroughly, then extend to Phase 2 if time permits.** 🎧

