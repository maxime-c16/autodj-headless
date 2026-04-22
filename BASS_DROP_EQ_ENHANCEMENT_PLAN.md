# AutoDJ Bass Drop Detection & EQ Automation Enhancement

**Goal:** Detect bass drops in tracks and apply professional DJ EQ technique (cut bass on drop, release modulo 4 bars)

**Status:** Research + Planning Phase ✅

---

## 🎯 The Pro DJ Technique: Extended Bass Cut Surprise

**The Goal:** Build tension by KEEPING bass cut THROUGH the drop, then release for maximum impact.

```
Timeline:
Bar 0-7:    Full groove (audience comfortable)
Bar 8:      ⚠️ DROP DETECTED - CUT BASS immediately
Bar 8-11:   Bass cut (2 bars pre-drop tension)
Bar 12:     🔔 DROP HITS - Audience expects bass back
Bar 12-15:  🎯 EXTENDED CUT - Bass STILL OFF (surprise!)
Bar 16:     🔊 BOOM! - Bass suddenly restored (massive impact)
```

**Why This Works:**
1. Audience expects bass + energy at drop
2. They get silence/reduced bass instead (tension!)
3. Release at bar 16 hits way harder (psychological impact)
4. Pro technique = memorable moment

**No audio glitches:** Need smooth envelope curves with no clicks/pops

---

## 🎯 Current Implementation Analysis

### What We Already Have

#### 1. **Cue Detection** ✅
- **Location:** `src/autodj/analyze/cues.py`
- **Techniques:**
  - Aubio onset detection (professional-grade, ~91-94% accuracy)
  - Hybrid fallback (energy + spectral flux)
  - Beat grid snapping (DJ-precise)
- **Detects:** Cue-in (energetic downbeat), Cue-out (energy drop before mix-out)
- **Output:** Frame positions snapped to beat grid

#### 2. **Audio Features Extraction** ✅
- **Location:** `src/autodj/analyze/audio_features.py`
- **Metrics Captured:**
  - RMS energy envelope
  - Spectral centroid (frequency content)
  - Percussiveness detection
  - Breakdown/Drop confidence scores
  - Loudness (EBU R128 standard)

#### 3. **EQ Automation Engine** ✅
- **Location:** `src/autodj/render/eq_automation.py`
- **Current Techniques:**
  - BASS_CUT: Quick bass reduction (1-4 bars) — **RELEVANT**
  - HIGH_SWAP: High-frequency control (4-8 bars)
  - FILTER_SWEEP: Low-pass sweep (8-16 bars) — **RELEVANT**
  - THREE_BAND_BLEND: All bands gradual (16-32 bars)
  - BASS_SWAP: Bass transition (4-8 bars) — **RELEVANT**

#### 4. **Bar Grid System** ✅
- **Location:** Multiple files
- **Features:**
  - Convert timestamps to bar positions
  - Snap to beat boundaries
  - 4-bar modulo alignment (4, 8, 16, 32 bar phrases)
  - Sample-accurate timing

---

## 🔍 Professional DJ Bass Drop Technique (Research)

### What Pro DJs Do

**Reference:** SkillzDJ Academy, Reddit r/DJs, r/Beatmatch, Electronic Music Production Forums

#### The Classic Technique: "Bass Duck Before Drop"

```
Timeline (4-bar phrases):

Bar 0-7:  Normal groove, full bass
    |
Bar 8:    ⚠️ ENERGY DROPS (drop point detected)
    |
Bar 8-11: CUT BASS completely (high-pass filter ~150Hz)
          Keep mids/highs for tension building
    |
Bar 12:   🔊 DROP HITS (bass returns to neutral/boosted)
    |
Bar 12+:  Full bass + energy back
```

**Pro Details:**
1. **Detection:** Listen for sudden drop in RMS energy/kick drum
2. **Pre-drop:** Cut low frequencies (60-150Hz band)
   - Sometimes use high-pass filter sweep (2kHz → minimal)
   - Creates tension/build-up
3. **Release:** Snap to next 4-bar boundary
   - Always restore at musical phrase (4, 8, 16 bar intervals)
   - Never leave bass cut (sounds broken)
4. **Timing:** Usually 1-2 bars of bass cut before drop
   - Then instant release on beat

#### Variations by Music Genre

**House/Tech House:**
- Bass cut: 1 bar (quick)
- Release: Immediate on drop
- Frequency: 80-100Hz

**Drum & Bass:**
- Bass cut: 2-4 bars (longer tension)
- Filter sweep for more drama
- Frequency: 150-200Hz (less aggressive)

**Dubstep:**
- Bass cut: Full spectrum (2-12kHz filter sweep)
- Release: Explosive on drop (boosts bass +3dB often)
- Frequency: Progressive roll-off

**Trap:**
- Bass cut: Selective (keep 808 thump, cut sub)
- Release: Gradual re-entry
- Frequency: Split at 60Hz

---

## 💻 Implementation Strategy

### Phase 1: Drop Detection Enhancement (2-3 hours)

**Goal:** Identify bass drops in audio features + cue detection

#### Approach A: Energy-Based (Fastest)
```python
# In audio_features.py, add:

def detect_drops(
    rms_energy: np.ndarray,
    spectral_centroid: np.ndarray,
    onset_frames: np.ndarray,
    bpm: float,
    sample_rate: int,
    confidence_threshold: float = 0.75
) -> List[Dict]:
    """
    Detect bass drops by:
    1. Energy drop (10-20% RMS decrease)
    2. Spectral change (centroid shift)
    3. Snap to beat grid
    4. Return modulo 4 bars
    """
    drops = []
    
    # 1. Calculate energy derivatives
    energy_derivative = np.diff(rms_energy)
    
    # 2. Find sudden drops (negative peaks in derivative)
    threshold = np.median(energy_derivative) - 0.5 * np.std(energy_derivative)
    drop_indices = np.where(energy_derivative < threshold)[0]
    
    # 3. Cluster nearby drops (within 0.5s)
    min_distance = int(0.5 * sample_rate)
    drops_clustered = []
    for idx in drop_indices:
        if not drops_clustered or (idx - drops_clustered[-1]) > min_distance:
            drops_clustered.append(idx)
    
    # 4. For each drop, calculate confidence + snap to beat
    samples_per_bar = (60 / bpm) * 4 * sample_rate
    
    for idx in drops_clustered:
        # Energy drop magnitude
        energy_change = energy_derivative[idx]
        confidence = min(1.0, abs(energy_change) / np.std(rms_energy))
        
        if confidence >= confidence_threshold:
            # Snap to nearest 4-bar boundary
            bar_pos = idx / samples_per_bar
            bar_snapped = round(bar_pos / 4) * 4  # Modulo 4
            frame_snapped = int(bar_snapped * samples_per_bar)
            
            drops.append({
                'frame': frame_snapped,
                'bar': int(bar_snapped),
                'confidence': confidence,
                'magnitude': energy_change,
                'type': 'energy_drop'
            })
    
    return drops
```

#### Approach B: Onset + Energy (More Accurate)
```python
# Combine aubio onset with energy analysis:

def detect_drops_advanced(
    audio_path: str,
    bpm: float,
    sample_rate: int = 44100
) -> List[Dict]:
    """
    1. Get onsets from aubio
    2. Filter for "breaks" (no new onsets for 0.25+ bars)
    3. Look for energy dip right after
    4. Return drop locations snapped to 4-bar grid
    """
    # Load audio
    y, sr = librosa.load(audio_path, sr=sample_rate)
    
    # Get onsets
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_env=onset_env, sr=sr)
    
    # Get energy
    rms = librosa.feature.rms(y=y)[0]
    
    # Look for gaps in onsets (breaks/drops)
    samples_per_bar = (60 / bpm) * 4 * sample_rate
    min_break_bars = 0.5  # At least half bar of no onsets
    min_break_frames = int(min_break_bars * samples_per_bar / hop_length)
    
    drops = []
    onset_intervals = np.diff(onsets)
    for i, interval in enumerate(onset_intervals):
        if interval > min_break_frames:
            # Potential drop/break
            drop_frame = onsets[i]
            
            # Check energy dip around this point
            energy_window = rms[max(0, drop_frame-10):drop_frame+10]
            if np.mean(energy_window) < np.median(rms) * 0.85:
                # Confirmed: low energy + no onsets = drop
                bar_pos = drop_frame / samples_per_bar
                bar_snapped = round(bar_pos / 4) * 4
                
                drops.append({
                    'frame': drop_frame,
                    'bar': int(bar_snapped),
                    'confidence': 0.9,  # High confidence for onset gaps
                    'type': 'onset_gap_drop'
                })
    
    return drops
```

### Phase 2: Bass Drop EQ Automation (1-2 hours)

**Goal:** Apply bass cut + release technique when drops detected

#### Enhancement to eq_automation.py

```python
class EQCutType(Enum):
    # ... existing ...
    BASS_DROP_CUT = "bass_drop_cut"  # NEW: Cut bass on drop, release 4 bars later

class EQAutomationEngine:
    def __init__(self, ...):
        # ... existing ...
        self.DROP_PATTERNS = {
            'bass_drop_cut': {
                'frequency_band': FrequencyBand.LOW,
                'magnitude_db': -12,  # Aggressive cut
                'envelope': EQEnvelope(
                    attack_ms=0,      # Instant (on the drop)
                    hold_bars=2,      # Hold 2 bars (tension building)
                    release_ms=0      # Snap back to neutral
                ),
                'phrase_length_bars': 4  # Always 4-bar aligned
            }
        }
    
    def detect_eq_opportunities(self, audio_features, ...) -> List[EQOpportunity]:
        # ... existing code ...
        
        # NEW: Add drop-based bass cuts
        if 'drops' in audio_features:
            for drop in audio_features['drops']:
                if drop['confidence'] >= self.MIN_CONFIDENCE:
                    bar = drop['bar']
                    
                    # Snap to next 4-bar boundary if not already
                    bar_aligned = (bar // 4) * 4
                    
                    opp = EQOpportunity(
                        cut_type=EQCutType.BASS_DROP_CUT,
                        bar=bar_aligned,
                        confidence=drop['confidence'],
                        frequency_band=FrequencyBand.LOW,
                        magnitude_db=self.DROP_PATTERNS['bass_drop_cut']['magnitude_db'],
                        envelope=self.DROP_PATTERNS['bass_drop_cut']['envelope'],
                        phrase_length_bars=4,
                        reason=f"Bass drop: cut bass at bar {bar_aligned}, release at bar {bar_aligned + 4}"
                    )
                    opportunities.append(opp)
        
        return opportunities
```

### Phase 3: Integration Testing (1 hour)

**Goal:** Test drop detection + EQ automation on real tracks

#### Test Cases

1. **Track with Clear Drop** (e.g., "Levels" by Avicii)
   - Drop at bar 32, cut bars 32-36, release at bar 36
   
2. **Track with Multiple Drops** (Buildup pattern)
   - Drop 1: bar 16 → cut 16-20 → release 20
   - Drop 2: bar 48 → cut 48-52 → release 52

3. **Track with Gradual Energy Shift** (No sharp drop)
   - Should have low confidence, may skip

---

## 🔧 Files to Create/Modify

### New Files
1. **`src/autodj/analyze/drop_detection.py`** (80-100 lines)
   - `detect_drops()` function
   - Energy-based detection
   - Onset-based detection (advanced)
   - Return drop metadata + confidence

### Modified Files
1. **`src/autodj/analyze/audio_features.py`**
   - Call `detect_drops()` at end of analysis
   - Store drops in audio_features dict
   
2. **`src/autodj/render/eq_automation.py`**
   - Add `BASS_DROP_CUT` technique
   - Update `detect_eq_opportunities()` to use drops
   - Add drop-specific envelope definitions

3. **`src/autodj/render/eq_applier.py`** (if filtering exists)
   - May need to handle instant attack + release timing

---

## 📊 Expected Results

### Before
```
Track: "Never Enough"
EQ Opportunities: 
  - Intro filter sweep (bar 0-16)
  - High swap (bar 8)
Result: Smooth, gradually opens into main groove
```

### After
```
Track: "Never Enough"
EQ Opportunities:
  - Intro filter sweep (bar 0-16)
  - High swap (bar 8)
  + Bass drop cut (bar 32-36)   ← NEW
  + Bass drop cut (bar 64-68)   ← NEW
Result: Tension building before drops, pro-sounding EQ automation
```

---

## 🎵 Reference Materials

### Research Sources
1. **SkillzDJ Academy** - "Understanding Blending with EQ"
   - Cut bass on incoming before swap
   - Release timing is critical
   - Always return to neutral (12 o'clock)

2. **Reddit r/DJs** - "Forget to bring bass back before drop"
   - Use filter sweep for deeper effect
   - 8-bar release is acceptable (more gradual)
   - Recovery is easier than missing drop

3. **Gearspace forums** - "Filter sweep + mix management"
   - Resonance adds drama (Q ~2.0-2.5)
   - Volume increases as filter opens
   - Sometimes intentional "break the rules" effects

4. **Electronic Music Production Communities**
   - Drop detection = sudden energy shift + kick drum change
   - Modulo 4-bar alignment is musical standard
   - Release timing matters more than cut timing

---

## 🚀 Implementation Timeline

| Phase | Task | Time | Status |
|-------|------|------|--------|
| 1 | Add drop detection (energy-based) | 1.5h | ⏳ Ready |
| 1 | Add drop detection (onset-based fallback) | 1.5h | ⏳ Ready |
| 2 | Add BASS_DROP_CUT to EQ engine | 1h | ⏳ Ready |
| 2 | Integrate drops into EQ detection | 1h | ⏳ Ready |
| 3 | Write tests + A/B comparison | 1h | ⏳ Ready |

**Total: ~6 hours**

---

## ✅ Next Steps

1. **Start Phase 1:** Create `drop_detection.py` with energy-based approach
2. **Test on sample track:** Verify drops are detected correctly
3. **Integrate into audio features:** Pass drops to EQ engine
4. **Implement Phase 2:** Add bass cut automation
5. **A/B test:** Compare with/without bass drop EQ
6. **Refine:** Adjust confidence thresholds + timings based on listening tests

**Ready to proceed?** Let's start with Phase 1 tomorrow (1.5-2 hours)

