# INTEGRATION CHECKLIST: Phase 1 & Phase 5

**Status:** Ready for Implementation  
**Complexity:** Medium (integration, not new code)  
**Risk Level:** Low (existing code, clear integration points)  

---

## PHASE 1: EARLY TRANSITIONS

### What Phase 1 Does
Starts mixing the incoming track **16 bars BEFORE the outgoing track's outro ends** (instead of when it finishes).

### Where to Integrate

**File 1: `/home/mcauchy/autodj-headless/src/autodj/render/render.py`**

#### Change 1: Add import (around line 30)
```python
# Add after existing imports:
from autodj.render.phase1_early_transitions import EarlyTransitionCalculator, EarlyTransitionParams
```

#### Change 2: Check phase1_enabled flag (around line 600-800)
Find where transitions are being processed. Look for loop like:
```python
for idx, transition in enumerate(transitions):
    # Process each transition
```

Add this check INSIDE the loop:
```python
if phase1_enabled and transition.get('early_transition_enabled'):
    # Calculate early transition timing
    calculator = EarlyTransitionCalculator()
    outro_start = transition.get('outro_start_seconds', 0)
    bpm = transition.get('target_bpm', 120)
    bars_before_outro = transition.get('bars_before_outro', 16)
    
    early_start_sec, early_end_sec = calculator.calculate_early_transition(
        outro_start=outro_start,
        bpm=bpm,
        bars=bars_before_outro
    )
    
    # Store for script generation
    transition['_phase1_early_start_seconds'] = early_start_sec
    transition['_phase1_early_end_seconds'] = early_end_sec
    transition['_phase1_enabled'] = True
```

#### Change 3: Pass to script generation (around line 1200-1400)
In the Liquidsoap script generation section, find where `incoming` track timing is set.

Look for code like:
```python
incoming_stream = f"single(\"{incoming_path}\")"
# ... later, mixer code uses incoming_stream
```

Modify to:
```python
# Check if Phase 1 early transition applies
if transition.get('_phase1_enabled'):
    early_start_sec = transition['_phase1_early_start_seconds']
    # Start incoming track early (convert seconds to offset)
    incoming_stream = f"single(\"{incoming_path}\")"
    incoming_stream = f"start({early_start_sec:.3f}, {incoming_stream})"
else:
    incoming_stream = f"single(\"{incoming_path}\")"
```

### Expected Liquidsoap Script Output

**BEFORE (current):**
```liquidsoap
# Standard crossfade at track end
outgoing = single("/path/to/track1.mp3")  # Starts at 0:00, ends at ~3:00
incoming = single("/path/to/track2.mp3")  # Starts at 3:00 (when track1 ends)
mixed = crossfade(fade_out=outgoing, fade_in=incoming)
output.file(mixed)
```

**AFTER (with Phase 1):**
```liquidsoap
# Early transition: track2 starts 16 bars before track1 ends
outgoing = single("/path/to/track1.mp3")  # Starts at 0:00, ends at ~3:00
incoming = single("/path/to/track2.mp3")  # Starts at 2:45 (16 bars early)
# Both play together for 16 bars, then crossfade
mixed = crossfade(fade_out=outgoing, fade_in=incoming)
output.file(mixed)
```

### Testing Phase 1

```bash
cd /home/mcauchy/autodj-headless

# Run unit tests
python -m pytest tests/test_phase1_early_transitions.py -v

# Run integration test
python render_with_all_phases.py

# Check Liquidsoap script
python -c "
from src.autodj.render.render import render
import json
with open('data/playlists/transitions-20260224-WITH-PHASES.json') as f:
    data = json.load(f)
transitions = data['transitions'][:2]  # Test with first 2
# Look for 'begin()' or offset timing in generated script
"

# Listen to output
ffplay /srv/nas/shared/automix/autodj-mix-*.mp3
```

---

## PHASE 5: MICRO-TECHNIQUES

### What Phase 5 Does
Applies 10 professional DJ techniques to transitions (bass cuts, rolls, sweeps, etc.) at precise bar positions.

### Where to Integrate

**File 1: `/home/mcauchy/autodj-headless/src/autodj/render/render.py`**

#### Change 1: Add imports (around line 30)
```python
# Add after existing imports:
from autodj.render.phase5_micro_techniques import (
    MicroTechniqueDatabase,
    GreedyMicroTechniqueSelector,
    MicroTechniqueType
)
from autodj.render.phase5_integration import Phase5Renderer
```

#### Change 2: Create Phase5Renderer instance (around line 500)
```python
# Early in the render() function:
phase5_renderer = None
if phase5_enabled:
    try:
        phase5_renderer = Phase5Renderer()
        logger.info(f"✅ Phase 5 renderer initialized (persona: {persona})")
    except Exception as e:
        logger.warning(f"⚠️ Phase 5 initialization failed: {e}")
        phase5_renderer = None
```

#### Change 3: Select and apply techniques (around line 1300)
In script generation loop, after setting up `incoming` stream:

```python
# Apply Phase 5 micro-techniques if enabled
if phase5_enabled and phase5_renderer:
    techniques = transition.get('phase5_micro_techniques', [])
    
    if techniques:
        logger.debug(f"Applying {len(techniques)} micro-techniques...")
        
        for technique in techniques:
            tech_type = technique.get('type', 'unknown')
            bar = technique.get('bar', 0)
            duration_bars = technique.get('duration_bars', 2)
            
            # Generate Liquidsoap code for technique
            try:
                effect_code = phase5_renderer.generate_technique(
                    technique_type=tech_type,
                    bar=bar,
                    duration_bars=duration_bars,
                    bpm=transition.get('target_bpm', 120),
                    parameters=technique.get('parameters', {})
                )
                
                if effect_code:
                    # Apply effect to incoming stream
                    script.append("# " + tech_type.replace('_', ' ').title())
                    script.extend(effect_code)
                    
            except Exception as e:
                logger.warning(f"  ⚠️ Failed to generate {tech_type}: {e}")
```

#### Change 4: Chain effects (around line 1350)
After all effects are generated, ensure they're chained to the incoming stream:

```python
# Chain all effects: incoming -> effect1 -> effect2 -> ... -> mixer
if phase5_renderer and transition.get('phase5_micro_techniques'):
    script.append("# Chain all Phase 5 effects to incoming stream")
    # The effects should be applied in order they appear in metadata
    script.append(f"{incoming_var} = apply_all_effects({incoming_var})")
```

### Expected Liquidsoap Script Output

**BEFORE (current):**
```liquidsoap
# Simple crossfade, no effects
incoming = single("/path/to/track2.mp3")
mixed = crossfade(fade_out=outgoing, fade_in=incoming)
```

**AFTER (with Phase 5):**
```liquidsoap
# Bar 8-10: Bass Cut + Roll (HPF @ 250Hz + stutter)
def bass_cut_roll(s) =
  hpf_stream = filter.iir.butterworth.high(cutoff=250.0)(s)
  stutter_stream = stutter(duration=2.0, loop_length=0.25)(hpf_stream)
  stutter_stream
end

# Bar 16-20: Filter Sweep (LPF sweep 2kHz → 20kHz)
def filter_sweep(s) =
  lpf_curve = envelope with sweep from 2000Hz to 20000Hz over 4 bars
  filter.iir.butterworth.low(cutoff=lpf_curve)(s)
end

# Apply effects in order
incoming = single("/path/to/track2.mp3")
incoming = bass_cut_roll(incoming)    # Bars 8-10
incoming = filter_sweep(incoming)     # Bars 16-20

# Mix with outgoing
mixed = crossfade(fade_out=outgoing, fade_in=incoming)
output.file(mixed)
```

### 10 Techniques to Implement

| # | Type | Implementation | Difficulty | Status |
|---|------|---|---|---|
| 1 | Stutter Roll | `stutter(duration, loop_length)` | ⭐⭐ | TODO |
| 2 | Bass Cut Roll | `hpf() + stutter()` | ⭐⭐ | TODO |
| 3 | Filter Sweep | `lpf()` with automation curve | ⭐⭐⭐ | TODO |
| 4 | Echo Out Return | `delay()` with fade automation | ⭐⭐⭐ | TODO |
| 5 | Quick Cut Reverb | `reverb()` with sharp cutoff | ⭐⭐ | TODO |
| 6 | Loop Stutter Accel | `stutter()` with acceleration | ⭐⭐⭐ | TODO |
| 7 | Mute Dim | Volume automation / silence | ⭐ | TODO |
| 8 | High Mid Boost | Peaking EQ @ 2-6kHz | ⭐⭐ | TODO |
| 9 | Ping Pong Pan | `panning()` with rapid automation | ⭐⭐⭐⭐ | TODO |
| 10 | Reverb Tail Cut | `reverb()` with fade-out | ⭐⭐⭐ | TODO |

### Testing Phase 5

```bash
cd /home/mcauchy/autodj-headless

# Run unit tests
python -m pytest tests/test_phase5_micro_techniques.py -v

# Run integration test
python render_with_all_phases.py

# Verify script includes effect code
python -c "
from src.autodj.render.render import render
# Check script for 'stutter(', 'hpf(', 'lpf(', etc.
"

# Listen for micro-techniques
ffplay /srv/nas/shared/automix/autodj-mix-*.mp3
# Should hear: bass cuts, rolls, filter sweeps at precise moments
```

---

## COMBINED INTEGRATION (BOTH PHASES)

### Test Entry Point
File: `render_with_all_phases.py`

```bash
# Currently this script exists but doesn't test anything
# After integration, run it to test Phase 1 + Phase 5 together:

python /home/mcauchy/autodj-headless/render_with_all_phases.py

# Expected output:
# 1. Loads transitions with Phase 1 & Phase 5 metadata
# 2. Renders with phase1_enabled=True, phase5_enabled=True
# 3. Generates Liquidsoap script with early transitions + effects
# 4. Creates MP3 output in /srv/nas/shared/automix/
# 5. No errors or numpy broadcasting issues
```

### Verification Checklist

- [ ] Phase 1 check: `early_transition_enabled=True` in metadata
- [ ] Phase 1 check: Early transition timing passes to Liquidsoap
- [ ] Phase 1 check: `begin()` offset or similar timing code in script
- [ ] Phase 1 test: Listen - hear track 2 starting before track 1 fully ends
- [ ] Phase 5 check: `phase5_micro_techniques` array in metadata
- [ ] Phase 5 check: Technique types match MicroTechniqueType enum
- [ ] Phase 5 check: Bar positions are within transition duration
- [ ] Phase 5 check: Liquidsoap script includes `stutter()`, `hpf()`, `lpf()` etc.
- [ ] Phase 5 test: Listen - hear effects at precise moments (bass cuts, rolls, sweeps)
- [ ] Combined test: All phases work together without errors
- [ ] Audio quality: No artifacts, glitches, or distortion
- [ ] Regression test: Old render tests still pass

---

## MINIMAL WORKING EXAMPLE

To test Phase 1 in isolation:

```python
from autodj.render.phase1_early_transitions import EarlyTransitionCalculator

calc = EarlyTransitionCalculator()
early_start, early_end = calc.calculate_early_transition(
    outro_start=280.0,      # Outro starts at 4:40 (280 seconds)
    bpm=128,                # Track is 128 BPM
    bars=16                 # Start 16 bars early
)

print(f"Transition starts at: {early_start:.1f}s")  # Should be ~272.5s
print(f"Transition ends at: {early_end:.1f}s")      # Should be ~280s
# Result: 16-bar overlap (272.5s to 280s is 7.5s ≈ 16 bars @ 128BPM)
```

To test Phase 5 in isolation:

```python
from autodj.render.phase5_micro_techniques import MicroTechniqueDatabase

db = MicroTechniqueDatabase()
spec = db.get_technique('stutter_roll')
print(f"Technique: {spec.name}")
print(f"Duration: {spec.min_duration_bars}-{spec.max_duration_bars} bars")
print(f"Liquidsoap template: {spec.liquidsoap_template}")
```

---

## EXPECTED TIMELINE

| Task | Duration | Status |
|------|----------|--------|
| Phase 1 integration (both changes) | 1-2 hours | READY |
| Phase 1 testing | 1 hour | READY |
| Phase 5 integration (tech generators) | 3-4 hours | READY |
| Phase 5 testing (all 10 techniques) | 2-3 hours | READY |
| Combined integration test | 1 hour | READY |
| Documentation & final validation | 1 hour | READY |
| **TOTAL** | **9-12 hours** | **1.5-2 days** |

---

## SUMMARY

✅ **Phase 1 Integration:**
- 2 files to modify (render.py in 2 places)
- Import EarlyTransitionCalculator
- Check flag, calculate timing, pass to script generation
- **Effort:** 1-2 hours

✅ **Phase 5 Integration:**
- 1 file to modify (render.py in 2 places)
- Import Phase5Renderer + MicroTechniqueDatabase
- Implement 10 technique code generators
- Apply to incoming stream in script
- **Effort:** 3-4 hours (mainly technique implementation)

✅ **Testing:**
- Unit tests already exist
- Integration test via render_with_all_phases.py
- Manual listening validation
- **Effort:** 3-4 hours

**Total Effort: 1.5-2 days of focused work**

---

**Ready to start when given the signal!**
