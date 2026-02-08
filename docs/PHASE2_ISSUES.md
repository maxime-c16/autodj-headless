# Phase 2 Complete → Phase 3 Blockers

## Overview
Phase 2 (Harmonic Mixing) implementation is complete and tested. This document outlines required work for Phase 3 (Spectral Analysis & Smart Cues).

---

## Phase 3 Required Issues

### #001 - Implement Spectral Analysis Module (Core)
**Priority:** CRITICAL  
**Type:** Feature  
**Estimate:** 8-10 hours  

**Description:**
Create `src/autodj/analyze/spectral.py` with FFT-based audio analysis functions.

**Requirements:**
- [ ] Implement `analyze_energy_profile(file_path)` - returns energy timeline + peaks
- [ ] Implement `detect_energy_peaks(spectrum, threshold=0.7)` - detects kicks/drops
- [ ] Implement `identify_smart_cues(audio_file)` - returns intro_end, first_kick, buildups[], outro_start, outro_end
- [ ] Implement `detect_intro_outro(spectrum)` - auto-detect intro/outro timestamps
- [ ] Implement `spectral_characteristics(file_path)` - bass/mid/treble energy, kick detection, bassline detection
- [ ] Full type hints and docstrings
- [ ] Logging at DEBUG/INFO levels

**Technical Notes:**
- Use scipy.signal.stft for short-time Fourier transform
- Use numpy for array operations
- Implement peak finding with signal.find_peaks()
- Energy threshold should be tunable (0.0-1.0)

**Acceptance Criteria:**
- All 5 functions implemented and working
- Handles various audio formats (m4a, mp3, wav)
- Performance: <2 seconds per track
- Graceful error handling for corrupted files

**Related:** #002, #003, #004

---

### #002 - Unit Tests for Spectral Analysis (80%+ coverage)
**Priority:** CRITICAL  
**Type:** Testing  
**Estimate:** 6-8 hours  

**Description:**
Comprehensive test suite for `test_phase3.py` with ≥80% code coverage.

**Test Categories:**
- [ ] `test_energy_profile_shape()` - verify output dimensions
- [ ] `test_peak_detection_count()` - realistic number of peaks
- [ ] `test_smart_cues_valid_range()` - cues within file duration
- [ ] `test_intro_outro_logic()` - sensible intro/outro timestamps
- [ ] `test_spectral_characteristics()` - frequency energy sums correctly
- [ ] `test_energy_threshold_impact()` - varying threshold changes peak count
- [ ] `test_real_track_cue_detection()` - integration test on 4 real tracks
- [ ] `test_performance_timing()` - processes <2 sec per track

**Acceptance Criteria:**
- ≥80% code coverage
- All tests passing
- Handles edge cases (very short files, silent sections)
- Performance benchmarks documented

**Related:** #001

---

### #003 - Smart Cue Point Detection on Real Tracks
**Priority:** CRITICAL  
**Type:** Integration Test  
**Estimate:** 4-6 hours  

**Description:**
Validate spectral analysis on 4 real DJ tracks and document detected cues.

**Test Tracks:**
1. NICE KEED - WE ARE YOUR FRIENDS (128 BPM, D minor)
2. LOOCEE Ø - COLD HEART (126 BPM, G minor)
3. DΛVЯ - In Favor Of Noise (130 BPM, A minor)
4. Niki Istrefi - Red Armor (125 BPM, E minor)

**Validation:**
- [ ] Detect intro endpoints (typically 8-32 seconds)
- [ ] Identify first major kick/drop
- [ ] Count buildups (should match audio subjectively)
- [ ] Find outro start (typically last 8-16 seconds)
- [ ] Verify cue accuracy within ±0.5 second tolerance

**Expected Results:**
- Intro detection accuracy: >90%
- Kick detection: All 4 tracks should have kick detected
- Buildup count: Reasonable for genre (electronic: 2-4 per track typical)
- Outro detection: Within last 20 seconds of file

**Related:** #001, #004

---

### #004 - Phase 3 Liquidsoap Integration
**Priority:** HIGH  
**Type:** Feature  
**Estimate:** 6-8 hours  

**Description:**
Create `demos/demo_phase3_liquidsoap.liq` combining Phase 1 + 2 + 3 features.

**Features to Implement:**
- [ ] Load 4 tracks with auto-detected smart cues
- [ ] Apply Phase 1 DSP (EQ automation, BPM matching)
- [ ] Apply Phase 2 harmonic awareness
- [ ] **NEW:** Apply Phase 3 smart cue-based mixing:
  - Use detected kick positions to sync EQ sweeps
  - Time crossfades to musical structure
  - Detect intro/outro for natural set boundaries
  - Synchronize BPM ramps to energy peaks

**Output:**
- MP3 file with all 3 phases active
- Real-time console logging showing detected cues
- Transition information at each boundary

**Performance Target:**
- Generate 10-minute demo in <2 minutes CPU time

**Related:** #001, #002, #003

---

### #005 - FFT Peak Detection Optimization
**Priority:** MEDIUM  
**Type:** Performance  
**Estimate:** 3-4 hours  

**Description:**
Optimize peak detection algorithm for real-time performance and accuracy.

**Current Issues:**
- Peak detection may be slow for long tracks
- Threshold tuning needs guidelines
- False positives in silence/room noise

**Optimization Tasks:**
- [ ] Implement adaptive threshold based on loudness
- [ ] Use librosa's peak picking when available
- [ ] Cache FFT results for repeated analysis
- [ ] Benchmark: target <2 sec per 3-minute track
- [ ] Document threshold tuning guidelines

**Success Metric:**
- Performance doubled from initial implementation
- <5% false positive rate on real tracks

**Related:** #001

---

### #006 - Spectral Characteristics Analysis Validation
**Priority:** HIGH  
**Type:** Validation  
**Estimate:** 4-5 hours  

**Description:**
Validate frequency decomposition and content detection (bass, mids, treble, rumble).

**Validation Tasks:**
- [ ] Test bass_energy (20-200 Hz) - known bass-heavy tracks
- [ ] Test mid_energy (200-2000 Hz) - should correlate with perceived brightness
- [ ] Test treble_energy (2000-20000 Hz) - high-frequency content
- [ ] Test rumble_presence (<20 Hz) - detect anomalies
- [ ] Test kick_detected - 100% accuracy on tracks with obvious kick
- [ ] Test bassline_present - correlation with bass-heavy tracks

**Reference Data:**
- Create reference audio with known frequency content
- Compare spectral analysis to professional tools (e.g., Sonic Visualizer)

**Related:** #001

---

### #007 - Documentation: Phase 3 Analysis Notes
**Priority:** MEDIUM  
**Type:** Documentation  
**Estimate:** 3-4 hours  

**Description:**
Create comprehensive technical documentation for Phase 3.

**Content:**
- [ ] FFT theory and STFT explanation
- [ ] Peak detection algorithm description
- [ ] Smart cue identification methodology
- [ ] Frequency band definitions and rationale
- [ ] Limitations and future improvements
- [ ] Performance benchmarks
- [ ] Usage examples and best practices

**Format:**
- `docs/phase3_analysis_notes.md` (3000+ words)
- Include diagrams (ASCII or embedded images)
- Code examples from real tests

**Related:** #001, #002, #003

---

### #008 - Phase 3 JSON Report Generation
**Priority:** MEDIUM  
**Type:** Feature  
**Estimate:** 2-3 hours  

**Description:**
Create JSON export for spectral analysis results on all 4 test tracks.

**Output Schema:**
```json
{
  "analysis_timestamp": "2026-02-07T...",
  "tracks": [
    {
      "index": 0,
      "name": "...",
      "file_path": "...",
      "duration_seconds": 240.5,
      "cues": {
        "intro_end": 12.3,
        "first_kick": 8.7,
        "buildups": [20.1, 45.3, 62.1],
        "outro_start": 230.2,
        "outro_end": 240.5
      },
      "spectral": {
        "bass_energy": 0.75,
        "mid_energy": 0.65,
        "treble_energy": 0.45,
        "rumble_presence": 0.15,
        "kick_detected": true,
        "bassline_present": true
      }
    }
  ]
}
```

**File:** `docs/phase3_analysis_report.json`

**Related:** #001, #003

---

### #009 - Real-Time Smart Cue Visualization (Optional)
**Priority:** LOW  
**Type:** Enhancement  
**Estimate:** 6-8 hours  

**Description:**
Create optional visualization of detected cues and energy profile.

**Features:**
- [ ] Plot energy timeline with peak markers
- [ ] Show detected intro/outro boundaries
- [ ] Overlay spectral content (bass/mid/treble)
- [ ] Interactive cue adjustment UI
- [ ] Export visualization as PNG/SVG

**Tools:**
- matplotlib for static plots
- plotly for interactive dashboards (optional)

**Use Case:**
- Manual verification of auto-detected cues
- Fine-tuning cue points before mixing
- Educational visualization of spectral concepts

**Related:** #001, #003, #007

---

### #010 - Robustness Testing: Edge Cases
**Priority:** HIGH  
**Type:** Testing  
**Estimate:** 4-5 hours  

**Description:**
Test spectral analysis on edge case audio files.

**Edge Cases to Cover:**
- [ ] Very short files (5 seconds)
- [ ] Very long files (30+ minutes)
- [ ] Silent/ambient sections
- [ ] Heavily compressed audio (low dynamic range)
- [ ] Extreme frequency content (subbass, ultra-treble)
- [ ] Corrupted/truncated files
- [ ] Various audio formats (m4a, mp3, wav, flac)
- [ ] Mono vs stereo files

**Acceptance Criteria:**
- Graceful handling of all edge cases
- Meaningful error messages for invalid input
- No crashes or memory leaks
- Documentation of limitations

**Related:** #001, #002

---

## Summary

**Total Estimated Effort:** 50-65 hours  
**Critical Path:** #001 → #002 → #003 → #004  
**Parallel Work Possible:** #005, #006, #007, #008, #009, #010  

**Completion Target:** ~40-48 hours with parallelization  
**Estimated Completion Date:** 2026-02-09 (2-3 days at 16 hours/day pace)

---

**Next Steps:**
1. Assign #001 (Spectral Analysis Module) - blocking all others
2. In parallel: Start #002 (Unit Tests template)
3. Once #001 complete: Unblock #003, #004
4. High-priority completion order: #001 → #002 → #003 → #004 → #006 → #007 → #008

**Dependencies:**
- librosa >= 0.10 (for audio analysis) - check available
- scipy >= 1.8 (for signal processing) - already available
- numpy >= 1.20 - already available

---

**Document Version:** 1.0  
**Generated:** 2026-02-07 01:30 UTC  
**Status:** Ready for Phase 3 Implementation
