# 🎯 PHASE 5: QUICK REFERENCE - MICRO-TECHNIQUES

## Bar Spacing Quick Facts

| Genre | Spacing | Techniques Per Section |
|-------|---------|----------------------|
| Tech House | 8-16 bars | 5-6 techniques |
| Techno | 8-16 bars | 4-5 techniques |
| House | 16-32 bars | 2-3 techniques |
| Afro House | 16-32 bars | 2-3 techniques |
| EDM | 8 bars | 4-6 techniques |

**Average across all genres: 8-16 bars between micro-techniques**

---

## Implementation Priority (Easiest → Hardest)

### 🟢 QUICK WINS (Easy, High Impact)

1. **MUTE + DIM** (Difficulty: ★☆☆)
   - Just drop volume 1-2 bars
   - Code: 10 lines
   - Test: 2 tests

2. **QUICK CUT + REVERB** (Difficulty: ★☆☆)
   - Crossfade cut + reverb
   - Code: 30 lines
   - Test: 3 tests

3. **BASS CUT + ROLL** (Difficulty: ★★☆)
   - Your original idea
   - HPF already exists in Phase 2
   - Code: 50 lines
   - Test: 5 tests

### 🟡 MEDIUM (Some complexity)

4. **STUTTER/LOOP ROLL** (Difficulty: ★★☆)
   - Loop length modulation
   - Liquidsoap loop() function
   - Code: 80 lines
   - Test: 8 tests

5. **FILTER SWEEP** (Difficulty: ★★★)
   - Smooth HPF/LPF over 4-8 bars
   - Curve selection (linear, log, exp)
   - Code: 120 lines
   - Test: 10 tests

### 🔴 COMPLEX (Worth it for polish)

6. **ECHO OUT + RETURN** (Difficulty: ★★★)
   - Echo + fade automation
   - Timing precision needed
   - Code: 100 lines
   - Test: 8 tests

7. **LOOP STUTTER ACCELERATION** (Difficulty: ★★★★)
   - Progressive shortening
   - Exponential timing
   - Code: 150 lines
   - Test: 12 tests

---

## Liquidsoap Commands Reference

```liquidsoap
# 1. Create a stutter effect
stutter(duration=2.0, loop_length=0.125) : track

# 2. Apply HPF (bass cut)
hpf(cutoff=250.0) : track

# 3. Add reverb
reverb(feedback=0.5, decay=2.0) : track

# 4. Mute (apply gain of 0)
amplify(0.0) : track

# 5. Filter sweep (HPF from 100 to 20000 Hz over 4 bars)
loop.
  f = 100.0 + (20000.0 - 100.0) * (time mod bar_duration) / bar_duration
  hpf(cutoff=f) : track

# 6. Echo effect
echo(duration=0.5, feedback=0.4, mix=0.6) : track

# 7. Ping-pong pan
pan(position=sin(2 * pi * time * pan_freq)) : track
```

---

## Phase 5 Architecture

```
┌─────────────────────────────────────────┐
│  Phase 5: Micro-Technique Engine        │
├─────────────────────────────────────────┤
│                                         │
│  Input: Track + Transition Data         │
│         Duration, BPM, Genre            │
│                                         │
│  Process:                               │
│  1. Identify micro-technique bars       │
│  2. Select technique (randomized)       │
│  3. Generate Liquidsoap FX code         │
│  4. Insert at correct timing            │
│                                         │
│  Output: Enhanced Liquidsoap script     │
│          with micro-techniques          │
│                                         │
└─────────────────────────────────────────┘
        ↓
    Phase 1-4 Processing
        ↓
    Audio Rendering
```

---

## Testing Strategy

### Unit Tests (Per-technique)
```python
test_stutter_roll_timing()
test_bass_cut_duration()
test_filter_sweep_frequency_curve()
test_echo_return_timing()
# ... etc for each technique
```

### Integration Tests
```python
test_phase5_with_phase1()
test_phase5_with_phase2()
test_phase5_with_phase4()
test_all_phases_together()
```

### Audio Quality Tests
```python
test_no_clicks_or_pops()
test_timing_accuracy_within_10ms()
test_audio_levels_normalized()
test_frequency_response_clean()
```

---

## Estimated Timeline

| Task | Duration | LOC | Tests |
|------|----------|-----|-------|
| Research & Design | ✅ Done | - | - |
| Implement 3 easy techniques | 45 min | 140 | 10 |
| Implement 2 medium techniques | 1.5 hrs | 200 | 18 |
| Implement 2 complex techniques | 2 hrs | 250 | 20 |
| Liquidsoap integration | 1 hr | 150 | 15 |
| Testing & debugging | 1.5 hrs | - | 40+ |
| Documentation | 45 min | - | - |
| **Total** | **~8 hours** | **~740 LOC** | **~60 tests** |

---

## Budget Conscious? Start Here

**Minimum Viable Phase 5** (3 hours, 240 LOC):

1. MUTE + DIM (easiest)
2. BASS CUT + ROLL (your idea, proven)
3. QUICK CUT + REVERB (professional touch)

These 3 alone would:
- ✅ Add engagement every 16-32 bars
- ✅ Use existing Phase 2 infrastructure
- ✅ Require minimal new Liquidsoap
- ✅ Sound professional

Then expand to full 10-technique system later.

---

## Questions to Answer Before Implementation

1. **Randomization?**
   - Random technique per bar? (Natural)
   - Structured sequence? (Predictable)
   - Genre-specific? (Professional)

2. **Intensity?**
   - How extreme should effects be?
   - More aggressive (Tech House style)?
   - More subtle (House style)?

3. **Bar Spacing?**
   - Exactly every 8/16/32 bars?
   - Random within 8-16 bar windows?
   - Adaptive to track energy?

4. **Integration with Phases 1-4?**
   - Conflict avoidance needed?
   - Can techniques overlap?
   - Priority ordering?

---

## Next Steps

1. **Decision:** Full 10-technique Phase 5, or MVP (3 techniques)?
2. **Priority:** Which 3-5 techniques first?
3. **Specification:** Answer the 4 questions above
4. **Implementation:** Code sprint
5. **Testing:** Showcase rendering
6. **Deployment:** Production pipeline

---

**Ready when you are!** 🎧
