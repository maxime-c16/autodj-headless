# 🔧 OPUS 4.6 REVIEW & FIXES - CRITICAL ISSUES

**Date:** 2026-02-07 08:40 UTC  
**Status:** ⚠️ Issues identified, fixes required  
**Opus Review Score:** 5/10 (scaffolding good, but critical integration gaps)

---

## 🎯 CRITICAL ISSUES IDENTIFIED BY OPUS

### Issue 1: ❌ Audio Buffer NOT Shared (MAJOR)
**Problem:**
- Each analysis module (loudness, spectral, adaptive_eq) reloads audio file independently
- For 4-track set: Audio loaded 12+ times (wasteful, slow)
- Memory bloat: 500MB+ when could be 100MB with shared buffer

**Example Current Flow:**
```
pipeline.py loads track.mp3
  → loudness.py loads track.mp3 again (reread from disk)
  → spectral.py loads track.mp3 again (reread from disk)
  → adaptive_eq.py loads track.mp3 again (reread from disk)
```

**Impact:** 
- 4-track set: 12 disk reads instead of 4
- Performance: 30+ seconds instead of 15 seconds
- Memory: 500MB instead of 100MB

---

### Issue 2: ❌ Config NOT Wired to Modules (MAJOR)
**Problem:**
- Pipeline has configuration (sample_rate, fft_size, block_size) but doesn't pass to:
  - spectral.py (uses hardcoded 2048 FFT)
  - adaptive_eq.py (uses hardcoded parameters)
  - loudness.py (uses hardcoded 48kHz)

**Example:**
```python
# pipeline.py has this config
fft_size = 2048  # Could be 4096 for better resolution
block_overlap = 0.75  # Not used in spectral.py!

# But spectral.py doesn't accept parameters:
def analyze_energy_profile(filepath):  # No config param!
    fft_size = 2048  # Hardcoded
```

**Impact:**
- Cannot tune DSP parameters globally
- Modules cannot adapt to different sample rates
- Configuration inheritance missing

---

### Issue 3: ❌ 5A→6A Scores as "POOR" (MEDIUM)
**Problem:**
- In some scenarios, 5A→6A (should be EXCELLENT) scores as POOR
- Root cause: Matrix calculation or compatibility determination bug
- Only affects certain input conditions

**Expected:** 5A→6A = EXCELLENT (adjacent on Camelot wheel)  
**Actual:** Sometimes POOR (4+ positions away)

**Root Cause:** Likely in `determine_compatibility()` cross-mode logic or matrix generation

---

### Issue 4: ⚠️ Pipeline Data Flow (MEDIUM)
**Problems:**
- No shared FFT/energy cache between modules
- loudness.py and adaptive_eq.py both run spectral analysis separately
- spectral characteristics computed 3x for same track

**Impact:**
- Redundant computation
- Slow integration
- Cannot share intermediate results

---

### Issue 5: ⚠️ No Memory Management for Large Sets (LOW)
**Problem:**
- Pipeline loads all tracks simultaneously
- For 100-track DJ set: 5GB+ RAM needed
- No streaming mode or batch processing

---

## ✅ FIX PRIORITY

### CRITICAL (Do First)
1. **Implement shared audio buffer** - Load once, reuse in all modules
2. **Fix 5A→6A compatibility** - Validate core algorithm
3. **Wire config to modules** - Pass parameters through function signatures

### HIGH (Do Second)
4. **Add FFT caching** - Compute once, share results
5. **Refactor pipeline** - Central audio loading, pass to modules

### MEDIUM (Optional)
6. **Add streaming mode** - For large DJ sets
7. **Memory pooling** - Pre-allocate numpy arrays

---

## 🔧 IMPLEMENTATION PLAN

### Fix 1: Shared Audio Buffer (3 hours)

**Create new utility module:**
```python
# src/autodj/analyze/audio_loader.py

class AudioCache:
    """Shared audio loading and caching."""
    
    def __init__(self, sample_rate: int = 48000):
        self.sample_rate = sample_rate
        self.audio_cache: Dict[str, np.ndarray] = {}
    
    def load_audio(self, filepath: str) -> Tuple[np.ndarray, int]:
        """Load audio once, cache for reuse."""
        if filepath not in self.audio_cache:
            audio, sr = librosa.load(filepath, sr=self.sample_rate)
            self.audio_cache[filepath] = audio
        return self.audio_cache[filepath], self.sample_rate
    
    def clear(self):
        self.audio_cache.clear()

# Update all modules to accept audio_cache parameter
def analyze_loudness(
    filepath: str,
    audio_cache: AudioCache  # NEW!
) -> LoudnessProfile:
    """Uses cached audio instead of reloading."""
    audio, sr = audio_cache.load_audio(filepath)
    # ... rest of analysis
```

**Changes Required:**
- loudness.py: Accept `audio_cache` parameter
- spectral.py: Accept `audio_cache` parameter
- adaptive_eq.py: Accept `audio_cache` parameter
- pipeline.py: Create `AudioCache` once, pass to all modules

**Impact:** 4-track set goes from 12 loads to 4 loads (3x faster)

---

### Fix 2: Validate 5A→6A Compatibility (2 hours)

**Test current behavior:**
```python
cd /home/mcauchy/autodj-headless

# Comprehensive test
python3 << 'EOF'
from src.autodj.analyze.harmonic import HarmonicMixer

mixer = HarmonicMixer()
mixer.add_track(0, "Track1", "5A")
mixer.add_track(1, "Track2", "6A")

matrix = mixer.calculate_compatibility_matrix()
print(f"5A→6A: {matrix[0,1]}")  # Should be 4.0 (EXCELLENT)

# Test with other adjacent pairs
tests = [
    ("1A", "2A"), ("12A", "1A"),  # Wrap-around
    ("1B", "2B"), ("5B", "6B"),    # Minor keys
    ("5A", "5B"),                  # Cross-mode same pos
]

for key1, key2 in tests:
    mixer2 = HarmonicMixer()
    mixer2.add_track(0, "T1", key1)
    mixer2.add_track(1, "T2", key2)
    mat = mixer2.calculate_compatibility_matrix()
    print(f"{key1}→{key2}: {mat[0,1]}")
EOF
```

**If failing:**
- Check `calculate_semitone_distance()` for mode switching logic
- Verify wheel_dist calculation doesn't miscalculate wrap-around
- Add edge case tests for positions 12→1, 1→12

---

### Fix 3: Wire Config to Modules (2 hours)

**Create config dataclass:**
```python
# src/autodj/analyze/config.py

from dataclasses import dataclass

@dataclass
class DSPConfig:
    """Global DSP configuration for all analysis modules."""
    sample_rate: int = 48000
    fft_size: int = 2048
    fft_overlap: float = 0.75
    block_size_ms: int = 400
    
    # Module-specific
    loudness_gate_lufs: float = -70.0
    eq_num_bands: int = 3
    eq_max_gain_db: float = 6.0
    
    @property
    def hop_size(self) -> int:
        """Hop size in samples."""
        return int(self.fft_size * (1 - self.fft_overlap))

# Update all module signatures:
def analyze_loudness(
    filepath: str,
    config: DSPConfig = None  # NEW!
) -> LoudnessProfile:
    if config is None:
        config = DSPConfig()  # Default
    
    sample_rate = config.sample_rate  # Use config value!
    # ... rest

# Pipeline creates once, passes to all:
config = DSPConfig(
    sample_rate=48000,
    fft_size=2048,
    block_size_ms=400,
)

loudness_result = analyze_loudness(track_path, config, audio_cache)
spectral_result = identify_smart_cues(track_path, config, audio_cache)
eq_result = design_adaptive_eq(spectral_result, config)
```

**Changes Required:**
- Create config.py with DSPConfig dataclass
- Update all 5 analysis modules to accept `config` parameter
- Pipeline passes config to all modules
- Allow runtime override of parameters

---

### Fix 4: Refactor Pipeline Data Flow (3 hours)

**Current flow (bad):**
```
track_path → loudness_py (load audio)
         → spectral_py (load audio)
         → adaptive_eq (no audio load, but needs spectral)
         → pipeline (orchestrates)
```

**New flow (good):**
```
track_path → pipeline
         ├→ AudioCache (load audio once)
         ├→ loudness.py (use cached audio)
         ├→ spectral.py (use cached audio)
         └→ adaptive_eq.py (use spectral result from cache)
```

**Implementation:**
```python
class DJAnalysisPipeline:
    def __init__(self, config: DSPConfig = None):
        self.config = config or DSPConfig()
        self.audio_cache = AudioCache(self.config.sample_rate)
    
    def analyze_track(self, filepath: str) -> TrackAnalysis:
        """Analyze track with shared resources."""
        # All modules use same audio, config, caching
        
        loudness = analyze_loudness(
            filepath,
            config=self.config,
            audio_cache=self.audio_cache  # NEW!
        )
        
        spectral = identify_smart_cues(
            filepath,
            config=self.config,
            audio_cache=self.audio_cache  # NEW!
        )
        
        eq = design_adaptive_eq(
            spectral,  # Reuse spectral result
            config=self.config
        )
        
        return TrackAnalysis(
            filepath=filepath,
            loudness=loudness,
            spectral=spectral,
            adaptive_eq=eq,
        )
    
    def analyze_track_set(self, filepaths: List[str]) -> List[TrackAnalysis]:
        """Analyze multiple tracks with efficient resource use."""
        results = []
        for filepath in filepaths:
            result = self.analyze_track(filepath)
            results.append(result)
            self.audio_cache.clear()  # Clear after each track
        
        return results
```

**Impact:**
- Audio loaded once per track (not 3x)
- Config globally consistent
- FFT results can be cached
- Memory usage drops 3-5x

---

## 📋 TESTING PLAN

### Unit Tests (Fix Validation)

```bash
# Test 1: Shared audio buffer works
pytest tests/test_audio_buffer.py -v

# Test 2: 5A→6A compatibility correct
pytest tests/test_phase2.py::test_camelot_wheel_5A_to_6A -v

# Test 3: Config propagates to modules
pytest tests/test_config_wiring.py -v

# Test 4: FFT caching works
pytest tests/test_spectral_cache.py -v
```

### Integration Tests

```bash
# Test 5: Full pipeline with 4 tracks
pytest tests/test_pipeline.py::test_4track_set_analysis -v

# Test 6: Memory usage < 200MB (not 500MB)
pytest tests/test_pipeline.py::test_memory_efficiency -v

# Test 7: Performance < 15 seconds (not 30+)
pytest tests/test_pipeline.py::test_performance_targets -v
```

### Real-World Validation

```bash
# Test 8: Analyze real 4-track DJ set
python3 << 'EOF'
from src.autodj.analyze.pipeline import DJAnalysisPipeline
from src.autodj.analyze.config import DSPConfig

config = DSPConfig(sample_rate=48000, fft_size=2048)
pipeline = DJAnalysisPipeline(config)

results = pipeline.analyze_track_set([
    "track1.m4a",
    "track2.m4a", 
    "track3.m4a",
    "track4.m4a",
])

for r in results:
    print(f"{r.filename}: {r.loudness.integrated_lufs:.1f} LUFS, "
          f"{r.spectral.bass_energy:.2f} bass")
EOF
```

---

## 📊 EXPECTED IMPROVEMENTS

**Before Fixes:**
- Audio loads: 12 (3x per track)
- Config hardcoded: ✗
- 5A→6A compatibility: Sometimes POOR ✗
- Performance: 30+ seconds for 4 tracks
- Memory: 500MB+

**After Fixes:**
- Audio loads: 4 (once per track)
- Config parameterized: ✓
- 5A→6A compatibility: EXCELLENT ✓
- Performance: <15 seconds for 4 tracks
- Memory: <150MB

**Improvement Factor:** 
- 3x faster ✓
- 3x less memory ✓
- 100% config control ✓
- No compatibility bugs ✓

---

## 📅 TIMELINE

**Day 1 (Today):**
- [ ] Validate 5A→6A bug (30 min)
- [ ] Create audio_loader.py (1 hour)
- [ ] Create config.py (30 min)

**Day 2:**
- [ ] Update loudness.py to use shared buffer + config (1 hour)
- [ ] Update spectral.py to use shared buffer + config (1 hour)
- [ ] Update adaptive_eq.py to use config (30 min)
- [ ] Refactor pipeline.py (2 hours)

**Day 3:**
- [ ] Write tests (3 hours)
- [ ] Validate with 4-track set (1 hour)
- [ ] Performance benchmarks (1 hour)

**Total:** 12-14 hours

---

## 🎯 SUCCESS CRITERIA

✅ All adjacent Camelot transitions score as EXCELLENT  
✅ Audio buffer shared (single load per track)  
✅ Config propagates to all modules  
✅ Performance: <15 sec for 4-track set  
✅ Memory: <200MB for 4 tracks  
✅ All tests pass with ≥80% coverage  
✅ No duplicate computation  

---

**Status:** Ready for implementation  
**Next:** Begin with validation & unit tests

Generated: 2026-02-07 08:45 UTC
