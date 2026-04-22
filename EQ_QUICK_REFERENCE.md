# EQ Liquidsoap DSP - Quick Reference

## Quick Start

### Basic Usage

```python
from autodj.render.eq_liquidsoap import EQLiquidsoap
from autodj.render.eq_automation import EQOpportunity, EQCutType, FrequencyBand, EQEnvelope

# 1. Create DSP generator
dsp_gen = EQLiquidsoap(bpm=128.0)

# 2. Define EQ opportunities (from Phase 1 detection)
opportunities = [
    EQOpportunity(
        cut_type=EQCutType.BASS_CUT,
        bar=12,
        confidence=0.90,
        frequency_band=FrequencyBand.LOW,
        magnitude_db=-8.0,
        envelope=EQEnvelope(attack_ms=0, hold_bars=2, release_ms=0),
        phrase_length_bars=4,
        reason="Breakdown tension"
    )
]

# 3. Generate DSP code
code = dsp_gen.generate_dsp_chain(opportunities, 32, "Artist - Title")

# 4. Use in Liquidsoap script
# code contains a ready-to-use function:
# let eq_dsp = fun(s) -> s |> dj_bass_cut(...) 
# eq_dsp
```

---

## EQ Filter Types

### 1. Bass Cut (Kick/Bass Reduction)

```python
EQOpportunity(
    cut_type=EQCutType.BASS_CUT,
    bar=12,                    # Start at bar 12
    confidence=0.90,           # 90% confident
    frequency_band=FrequencyBand.LOW,  # Affects 60Hz (kick/bass)
    magnitude_db=-8.0,         # Cut 8 decibels
    envelope=EQEnvelope(
        attack_ms=0,           # Instant attack (percussive)
        hold_bars=2,           # Hold for 2 bars
        release_ms=0           # Snap back to neutral
    ),
    phrase_length_bars=4,      # Total duration 4 bars
    reason="Breakdown tension" # Explanation
)

# Generated Liquidsoap:
# |> dj_bass_cut(
#     magnitude_db=-8.0,
#     freq_hz=60,
#     start_sec=22.5,        # Bar 12 @ 128 BPM
#     attack_sec=0.0,
#     hold_sec=3.75,         # 2 bars @ 1.875 sec/bar
#     release_sec=0.0
# )
```

**Use Cases:**
- Breakdown tension building (2-4 bars)
- Energy punctuation
- Quick bass drop-out/drop-in

---

### 2. High Swap (Brightness/Harshness Control)

```python
EQOpportunity(
    cut_type=EQCutType.HIGH_SWAP,
    bar=8,                     # Start at bar 8
    confidence=0.88,           # 88% confident
    frequency_band=FrequencyBand.HIGH,  # Affects 3000Hz (brightness)
    magnitude_db=-4.5,         # Cut 4.5 decibels
    envelope=EQEnvelope(
        attack_ms=200,         # Gradual fade in (200ms)
        hold_bars=4,           # Hold for 4 bars
        release_ms=200         # Gradual fade out (200ms)
    ),
    phrase_length_bars=8,      # Total duration 8 bars
    reason="Soften vocal harshness"
)

# Generated Liquidsoap:
# |> dj_high_swap(
#     magnitude_db=-4.5,
#     freq_hz=3000,
#     start_sec=15.0,        # Bar 8 @ 128 BPM
#     attack_sec=0.2,
#     hold_sec=7.5,          # 4 bars @ 1.875 sec/bar
#     release_sec=0.2
# )
```

**Use Cases:**
- Vocal section clarity
- Reduce hi-hat harshness
- Smooth cymbals during builds
- Energy shaping at section boundaries

---

### 3. Filter Sweep (Dramatic Tension Building)

```python
EQOpportunity(
    cut_type=EQCutType.FILTER_SWEEP,
    bar=0,                     # Start at intro (bar 0)
    confidence=0.92,           # 92% confident
    frequency_band=FrequencyBand.SWEEP,  # Low-pass sweep
    magnitude_db=-12.0,        # Not used (sweep parameter)
    envelope=EQEnvelope(
        attack_ms=100,         # Quick initial attack
        hold_bars=12,          # Sweep over 12 bars
        release_ms=200         # Snap back
    ),
    phrase_length_bars=16,     # Total duration 16 bars
    reason="Intro filter sweep: gradually reveal brightness"
)

# Generated Liquidsoap:
# |> dj_filter_sweep(
#     start_freq_hz=2000.0,  # Start muffled at 2kHz
#     end_freq_hz=20000.0,   # Open to 20kHz (full spectrum)
#     start_sec=0.0,
#     attack_sec=0.1,
#     hold_sec=22.5,         # 12 bars @ 1.875 sec/bar
#     release_sec=0.2
# )
```

**Use Cases:**
- Intro reveals (gradually open from muffled)
- Pre-drop tension (close then open)
- DJ signature effect
- Creative frequency sweeps

---

### 4. Three-Band Blend (Smooth Transitions)

```python
EQOpportunity(
    cut_type=EQCutType.THREE_BAND_BLEND,
    bar=16,                    # Start at bar 16
    confidence=0.85,           # 85% confident
    frequency_band=FrequencyBand.LOW,  # Doesn't matter (all bands)
    magnitude_db=-6.0,         # Cut 6 decibels on all three
    envelope=EQEnvelope(
        attack_ms=500,         # Gradual attack (500ms)
        hold_bars=8,           # Hold for 8 bars
        release_ms=500         # Gradual release (500ms)
    ),
    phrase_length_bars=16,     # Total duration 16 bars
    reason="Smooth section transition"
)

# Generated Liquidsoap:
# |> dj_three_band_blend(
#     magnitude_db=-6.0,
#     start_sec=30.0,        # Bar 16 @ 128 BPM
#     attack_sec=0.5,
#     hold_sec=15.0,         # 8 bars @ 1.875 sec/bar
#     release_sec=0.5
# )
```

**Use Cases:**
- 16-32 bar transitions (major section changes)
- Smooth intro→main groove
- Silky breakdowns
- Full band energy sculpting

---

### 5. Bass Swap (Quick Bass Transition)

```python
EQOpportunity(
    cut_type=EQCutType.BASS_SWAP,
    bar=4,                     # Start at bar 4
    confidence=0.75,           # 75% confident
    frequency_band=FrequencyBand.LOW,  # Affects 60Hz (bass)
    magnitude_db=-7.0,         # Cut 7 decibels
    envelope=EQEnvelope(
        attack_ms=50,          # Very quick attack (50ms)
        hold_bars=4,           # Hold for 4 bars
        release_ms=50          # Very quick release (50ms)
    ),
    phrase_length_bars=4,      # Total duration 4 bars
    reason="Energy management"
)

# Generated Liquidsoap:
# |> dj_bass_swap(
#     magnitude_db=-7.0,
#     freq_hz=60,
#     start_sec=7.5,         # Bar 4 @ 128 BPM
#     attack_sec=0.05,
#     hold_sec=7.5,          # 4 bars @ 1.875 sec/bar
#     release_sec=0.05
# )
```

**Use Cases:**
- Quick bass transitions (4-8 bars)
- Energy management in percussive sections
- Punch in/out bass
- Faster than bass_cut, slower than instant

---

## Envelope Timing Reference

At **128 BPM** (1 bar = 1.875 seconds):

| Bars | Seconds | Use Case |
|------|---------|----------|
| 1 | 1.875s | Quick punctuation |
| 2 | 3.75s | Short cuts (bass_cut) |
| 4 | 7.5s | Standard phrase (high_swap, bass_swap) |
| 8 | 15.0s | Longer holds (high_swap, three_band) |
| 12 | 22.5s | Filter sweep middle section |
| 16 | 30.0s | Major transitions (three_band_blend) |
| 32 | 60.0s | Extended builds |

---

## Common Envelope Patterns

### Percussive Cut (Bass Cut, Bass Swap)
```python
EQEnvelope(
    attack_ms=0,      # Snap in
    hold_bars=2,      # Short hold
    release_ms=0      # Snap back
)
# Effect: Punchy, immediate EQ effect
# Best for: Breakdowns, energy punctuation
```

### Smooth Fade (High Swap)
```python
EQEnvelope(
    attack_ms=200,    # Gradual fade in
    hold_bars=4,      # Medium hold
    release_ms=200    # Gradual fade out
)
# Effect: Smooth, natural transitions
# Best for: Vocal sections, harshness control
```

### Long Sweep (Filter Sweep)
```python
EQEnvelope(
    attack_ms=100,    # Quick initial reveal
    hold_bars=12,     # Long hold for sweep
    release_ms=200    # Snap back
)
# Effect: Dramatic tension building
# Best for: Intros, pre-drops, creative effects
```

### Extended Blend (Three-Band)
```python
EQEnvelope(
    attack_ms=500,    # Very gradual (0.5s)
    hold_bars=8,      # Medium hold
    release_ms=500    # Very gradual (0.5s)
)
# Effect: Silky smooth all-band fade
# Best for: 16-32 bar transitions
```

---

## Frequency Reference

| Band | Type | Frequency | Content | Cut Typical |
|------|------|-----------|---------|-------------|
| **Low** | Bass | 60-120 Hz | Kick drum, sub-bass | -6 to -9 dB |
| **Mid** | Personality | 300-1kHz | Vocals, drums, melodies | -3 to -6 dB |
| **High** | Shine | 3-12 kHz | Hi-hats, cymbals, brightness | -3 to -6 dB |
| **Sweep** | Filter | 2kHz→20kHz | Low-pass sweep (reveal) | -12 dB start |

---

## Integration with Detection

Phase 1 detection produces opportunities with high confidence:

```python
from autodj.render.eq_automation import EQAutomationEngine

# Detect opportunities
engine = EQAutomationEngine(bpm=128.0)
opportunities = engine.detect_opportunities(
    audio_features={
        'intro_confidence': 0.92,
        'vocal_confidence': 0.88,
        'breakdown_confidence': 0.85,
        'percussiveness': 0.75,
        'num_bars': 32,
    }
)

# Generate DSP code
dsp_gen = EQLiquidsoap(bpm=128.0)
code = dsp_gen.generate_dsp_chain(opportunities, 32, "Track")

# Use in Liquidsoap
# (code is ready to insert into script)
```

---

## Testing

Run all tests:
```bash
cd /home/mcauchy/autodj-headless
PYTHONPATH=src python3 -m pytest tests/test_eq_liquidsoap.py -v
```

Expected: **17 passed in 0.04s**

---

## Common Mistakes to Avoid

❌ **Positive magnitude_db** (boosts instead of cuts)
```python
magnitude_db=+3.0  # WRONG! Can cause clipping
```
✅ Always use negative values (cuts)

---

❌ **Magnitude too extreme**
```python
magnitude_db=-24.0  # WRONG! Too harsh
```
✅ Use ranges: -3 to -12 dB for standard cuts

---

❌ **Opportunities not bar-aligned**
```python
bar=7.5  # WRONG! Must be integer bar
```
✅ Always use integer bar positions

---

❌ **Envelope ms/bars confusion**
```python
EQEnvelope(attack_ms=4, hold_bars=200, release_ms=0)  # WRONG!
```
✅ attack_ms and release_ms in milliseconds, hold_bars in bars

---

❌ **Opportunities overlapping**
```python
# Opp 1: bars 8-12
# Opp 2: bars 10-14  # WRONG! Overlaps by 2 bars
```
✅ Maintain 2-bar minimum buffer between cuts

---

## CLI Usage

```bash
# Generate WITH EQ
make quick-mix SEED='Never Enough' TRACK_COUNT=3

# Generate WITHOUT EQ (baseline)
make quick-mix SEED='Never Enough' TRACK_COUNT=3 EQ=off

# Full render with EQ
make render

# Full render without EQ
make render EQ=off

# A/B testing
make a-b-test TRACK='Never Enough'
make a-b-test TRACK='Never Enough' EQ=off
```

---

## Performance Tips

- **DSP code size:** ~10-20 lines per opportunity
- **Render overhead:** +6% for typical 3-track mix with 4 opportunities
- **Memory overhead:** ~2.8% additional
- **CPU overhead:** ~8% additional

**Recommendation:** EQ automation is cheap enough to always enable.

---

## Support

See full documentation:
- `EQ_LIQUIDSOAP_DSP.md` - Complete architecture
- `DJ_EQ_AUTOMATION.md` - Detection engine
- `DJ_EQ_RESEARCH.md` - DJ EQ theory
- `PHASE2_SUMMARY.md` - Implementation summary
