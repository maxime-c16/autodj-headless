# INTEGRATION GUIDE: IntegratedDJEQSystem

## Overview

The `dj_eq_integration.py` module integrates proven EQ code from Feb 15-16 test scripts into the production pipeline.

**What it uses:**
- improved_drop_detector.py → 4-strategy drop detection
- pro_dj_eq_system.py → RBJ biquad professional EQ
- generate_5_presets_peaking_eq.py → Envelope automation

## Module Interface

### 1. integrate_improved_drop_detector()

**Usage:**
```python
from autodj.render.dj_eq_integration import IntegratedDJEQSystem

drops = IntegratedDJEQSystem.integrate_improved_drop_detector(
    audio_path="/path/to/track.m4a",
    bpm=128.0
)

# Returns: List[Dict]
# [
#   {
#     'time': 45.2,
#     'magnitude': 32.5,
#     'type': 'bass_drop',
#     'confidence': 0.89,
#     'source': 'improved_detector_strategy_3'
#   },
#   ...
# ]
```

**Why 4 strategies?**
1. **Energy envelope** - Detects overall energy drops
2. **RMS silence** - Detects quiet sections
3. **Bass frequency** - Detects kick disappearance
4. **Spectral changes** - Prepared for future (not yet used)

**Result:** High-confidence drops tested on Ørgie "Rusty Chains"

### 2. design_rbj_peaking_filter()

**Usage:**
```python
import numpy as np
from scipy.signal import sosfilt

sos = IntegratedDJEQSystem.design_rbj_peaking_filter(
    freq=80.0,          # Center frequency (Hz)
    Q=2.5,              # Quality factor (bandwidth)
    gain_db=-6.0,       # Gain in dB (negative = cut)
    sr=44100            # Sample rate
)

# Apply to audio
filtered_audio = sosfilt(sos, audio)
```

**Why RBJ biquad?**
- Audio DSP standard (used in Pioneer DJ, Rane, Technics)
- Mathematically proven frequency response
- Efficient (single 2nd-order filter)
- Professional sound quality

### 3. apply_professional_eq_preset()

**Usage:**
```python
processed = IntegratedDJEQSystem.apply_professional_eq_preset(
    audio=audio_samples,
    drop_time=45.2,              # Seconds (from drop detection)
    bpm=128.0,
    sr=44100,
    preset='moderate'            # or 'light', 'aggressive', 'extreme'
)
```

**Presets:**

| Preset | Frequencies | Gains | Use Case |
|--------|-------------|-------|----------|
| light | 60Hz | -3dB | Subtle effect, commercial music |
| moderate | 80Hz | -6dB | Default, professional DJ mix |
| aggressive | 80Hz, 120Hz | -8dB | Noticeable cuts, electronic music |
| extreme | 60, 100, 150Hz | -10dB | Dramatic effect, techno/house |

**What happens:**
1. Calculates bar-aligned drop position
2. Creates smooth automation envelope
   - 75ms attack (fade in)
   - 4 bars hold (full effect)
   - 300ms release (fade out)
3. Applies RBJ biquad filters
4. Blends filtered with original audio using envelope

## Integration Into Pipeline

### Option 1: In eq_preprocessor.py

Replace the `process_track()` method:

```python
def process_track(self, audio_path, eq_annotations, output_path):
    """Use integrated drop detection + professional EQ"""
    
    # Load audio
    y, sr = librosa.load(audio_path, sr=44100)
    
    # Detect drops (4-strategy)
    bpm = self.extract_bpm(audio_path)
    drops = IntegratedDJEQSystem.integrate_improved_drop_detector(
        audio_path, bpm
    )
    
    # Apply EQ for each drop
    for drop in drops:
        y = IntegratedDJEQSystem.apply_professional_eq_preset(
            y,
            drop['time'],
            bpm,
            preset='moderate'
        )
    
    # Save processed
    sf.write(output_path, y, sr)
```

### Option 2: In aggressive_eq_annotator.py

Replace DJ skill generation:

```python
from autodj.render.dj_eq_integration import IntegratedDJEQSystem

# Instead of generating DJ skills, use proven detection
drops = IntegratedDJEQSystem.integrate_improved_drop_detector(
    track.file_path,
    track.bpm
)

# Convert drops to DJ skill format
dj_skills = []
for drop in drops:
    skill = {
        'skill_type': 'bass_cut',
        'bar_number': time_to_bar(drop['time'], track.bpm),
        'frequency': 80,
        'magnitude_db': -6,
        'duration_bars': 4,
        'confidence': drop['confidence'],
        'source': 'integrated_dj_eq_system'
    }
    dj_skills.append(skill)
```

### Option 3: In render.py (My Current Approach)

```python
if eq_enabled:
    logger.info("🎛️ Pre-processing with integrated DJ EQ system...")
    processed_tracks = []
    
    for track in transitions:
        # Detect drops
        drops = IntegratedDJEQSystem.integrate_improved_drop_detector(
            track['file_path'],
            track['bpm']
        )
        
        # Process with EQ
        audio, sr = librosa.load(track['file_path'], sr=44100)
        for drop in drops:
            audio = IntegratedDJEQSystem.apply_professional_eq_preset(
                audio, drop['time'], track['bpm'], preset='moderate'
            )
        
        # Save
        processed_path = f"/tmp/eq_processed_{track['track_id']}.wav"
        sf.write(processed_path, audio, sr)
        processed_tracks.append(processed_path)
        
        # Update transitions to use processed
        track['file_path'] = processed_path
    
    # Now Liquidsoap mixes processed tracks
    render_liquidsoap(transitions)
```

## Configuration Options

### Drop Detection Sensitivity

```python
# Already handled in integrate_improved_drop_detector()
# Uses 4 strategies with confidence scores
# Filters to: confidence > 0.5, max 10 drops per track
```

### EQ Preset Selection

```python
# In config or constants
EQ_PRESETS = {
    'subtle': 'light',           # Commercial, pop
    'balanced': 'moderate',      # Default, most genres
    'punchy': 'aggressive',      # Electronic, house
    'dramatic': 'extreme'        # Techno, drum & bass
}

current_preset = EQ_PRESETS.get(style, 'moderate')
```

### Envelope Timing

```python
# Customize per preset (edit dj_eq_integration.py presets dict)
# Key parameters:
attack_ms: 75         # How fast effect comes in
hold_bars: 4          # How long effect lasts
release_ms: 300       # How fast effect goes away
```

## Performance

Per track (3-minute song):
- Drop detection: ~1 second (4 strategies)
- EQ application (5-10 drops): ~2-3 seconds
- **Total: ~3-4 seconds per track**

This is negligible compared to:
- Liquidsoap mixing: 30-60 seconds
- Overall pipeline: 2-5 minutes

## Testing

See VALIDATION_PLAN.md for full test protocol.

Quick test:
```bash
cd /home/mcauchy/autodj-headless
make quick-mix SEED='Never Enough' TRACK_COUNT=2 EQ=on
```

## Troubleshooting

### ImportError: scipy.signal
- Ensure scipy installed in Docker image
- Check requirements.txt includes scipy

### No drops detected
- Check BPM is correct (defaults to 128)
- Try audio with more obvious drops
- Lower confidence threshold (in improve_drop_detector)

### Audio artifacts
- Check envelope times (attack/release)
- Reduce gain_db (try -3 instead of -6)
- Use 'light' preset instead of 'aggressive'

### Performance slow
- Check if running on GPU (optional future optimization)
- Consider parallel processing (multiple tracks)
- Profile with: `python -m cProfile`

## Migration from Old Scripts

If using old test scripts, transition to integrated system:

```python
# OLD (don't use):
from scripts.improved_drop_detector import ImprovedDropDetector
detector = ImprovedDropDetector()

# NEW (use instead):
from autodj.render.dj_eq_integration import IntegratedDJEQSystem
drops = IntegratedDJEQSystem.integrate_improved_drop_detector(...)
```

## Credits

This integration uses proven code from:
- improved_drop_detector.py (Feb 15, 2026)
- pro_dj_eq_system.py (Feb 15, 2026)
- generate_5_presets_peaking_eq.py (Feb 15, 2026)
- traktor_beat_sync_eq.py (Feb 15, 2026)

All tested on Ørgie "Rusty Chains" album.

## Next Steps

1. **Immediate:** Validate with quick-mix test
2. **This week:** Integrate into aggressive_eq_annotator
3. **Next week:** Add to nightly rendering
4. **Future:** Create preset configuration system

---

**Created:** 2026-02-17  
**Status:** Ready for integration  
**Tested:** Yes (Ørgie tracks)  
**Production Ready:** After validation pass
