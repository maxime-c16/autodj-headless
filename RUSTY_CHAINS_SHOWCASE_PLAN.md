# Rusty Chains Showcase Generation Plan

**Album:** "Rusty Chains" by Ørgie  
**Goal:** Generate a professional DJ-quality mix showcasing all DJ Techniques phases  
**Status:** Ready to implement  

---

## What We're Creating

A full-album remix showcasing:
- ✅ **Phase 1:** Early transitions (16+ bars before outros)
- ✅ **Phase 2:** Professional bass control (HPF + unmask)
- ✅ **Phase 4:** Dynamic variation (natural mixing patterns)
- 📊 **Analysis:** Before/after comparisons

**Output:** `rusty_chains_dj_techniques_showcase.mp3` (~40-60 min)

---

## Implementation Steps

### Step 1: Catalog Rusty Chains Album
```
Goal: Identify all tracks and their audio characteristics
Time: ~15 minutes

Tasks:
1. Scan music library for "Rusty Chains" or "Ørgie" tracks
2. Analyze each track:
   - Duration
   - BPM
   - Key (harmonic compatibility)
   - Intro/outro boundaries
   - Bass energy levels
3. Create track manifest (JSON)
```

### Step 2: Run Full Analysis Pipeline
```
Goal: Generate spectral + harmonic data for all tracks
Time: ~5-10 minutes (depends on track count)

Uses: aubio (spectral), harmonic.py (keys), bpm detection
Output: Analysis metadata for each track
```

### Step 3: Generate DJ Mix Playlist
```
Goal: Create optimal track sequence using Merlin selector
Time: ~2 minutes

Uses: Merlin greedy selector
Constraints:
  - Harmonic compatibility (Camelot wheel)
  - BPM proximity (allow ±5 BPM)
  - Energy flow (build tension, release)
  - Track variety (avoid repetition)

Output: playlist.m3u + transitions.json
```

### Step 4: Apply DJ Techniques Phases
```
Goal: Enhance transitions with Phases 1-4
Time: ~1 minute

Pipeline:
  Phase 1: Calculate early transition timings
  Phase 2: Analyze bass, apply HPF specs
  Phase 4: Apply dynamic variation (randomize)

Output: transitions.json with all phase fields
```

### Step 5: Render DJ Mix
```
Goal: Generate final MP3 with all effects applied
Time: ~15-30 minutes (depends on total duration)

Uses: Liquidsoap render engine
Applies:
  - Phase 1 timing (early transitions)
  - Phase 2 bass control (HPF filters)
  - Phase 4 variation (timing/intensity)
  - EQ automation

Output: Final MP3 mix
```

### Step 6: Generate Comparison Analysis
```
Goal: Create before/after visualizations
Time: ~5-10 minutes

Generates:
  - Spectrogram comparison (frequency content)
  - Loudness analysis (LUFS)
  - Transition timing diagram
  - Bass energy timeline

Output: PNG charts + analysis PDF
```

### Step 7: Create Showcase Documentation
```
Goal: Document the showcase with technical details
Time: ~5 minutes

Includes:
  - Track listing
  - Transition analysis (timing, EQ moves)
  - Phase statistics (gradual vs instant, etc.)
  - Audio quality metrics

Output: README + analysis document
```

---

## Estimated Total Time

| Step | Time | Cumulative |
|------|------|-----------|
| 1. Catalog tracks | 15 min | 15 min |
| 2. Analysis | 10 min | 25 min |
| 3. Playlist generation | 2 min | 27 min |
| 4. Phase application | 1 min | 28 min |
| 5. Rendering | 30 min | 58 min |
| 6. Comparison analysis | 10 min | 68 min |
| 7. Documentation | 5 min | 73 min |
| **TOTAL** | **~73 min** | **1h 13m** |

---

## Output Deliverables

```
/home/mcauchy/showcase/
├── rusty_chains_dj_techniques_showcase.mp3  (Main output - 40-60 min)
├── playlist.m3u                              (Track sequence)
├── transitions.json                          (All phase data)
├── analysis/
│   ├── spectrogram_before.png               (Original playlist mixing)
│   ├── spectrogram_after.png                (With DJ techniques)
│   ├── transition_timeline.png              (Timing visualization)
│   ├── bass_energy_analysis.png             (HPF effectiveness)
│   └── statistics.json                      (Numerical metrics)
├── README_SHOWCASE.md                       (Full documentation)
├── track_manifest.json                      (Catalog of all tracks)
└── TECHNICAL_ANALYSIS.md                    (Deep dive)
```

---

## Expected Results

### Audio Quality Improvements
- **Transition Smoothness:** Professional DJ blend vs abrupt playlist cuts
- **Bass Clarity:** Controlled low-end (no mud from overlapping basslines)
- **Energy Flow:** Natural progression through intensity curves
- **Mixing Techniques:** Audible EQ moves, frequency layering

### Metrics to Measure
- ✅ Transition timing accuracy (should be 16± bars before outro)
- ✅ Bass cut effectiveness (HPF reducing <200Hz by target %)
- ✅ Variation patterns (60/40 gradual/instant ratio, ±2 bar jitter)
- ✅ Overall loudness consistency (LUFS within target)
- ✅ Frequency balance (no clipping, clean bass)

---

## How to Run

### Quick Start (If Rusty Chains Available)
```bash
cd /home/mcauchy/autodj-headless

# Full showcase generation
python3 -m src.autodj.showcase_generator \
  --album "Rusty Chains" \
  --artist "Ørgie" \
  --output "./showcase/" \
  --enable-all-phases \
  --generate-analysis

# Result: Everything in ./showcase/
```

### Step-by-Step Manual
```bash
# 1. Catalog tracks
python3 scripts/catalog_album.py --path "/path/to/rusty_chains"

# 2. Analyze
python3 -m src.autodj.analyze --manifest tracks.json

# 3. Generate playlist
python3 -m src.autodj.generate --manifest tracks.json

# 4. Apply DJ techniques
python3 scripts/apply_dj_phases.py --transitions transitions.json

# 5. Render
python3 -m src.autodj.render --playlist playlist.m3u --transitions transitions.json

# 6. Compare
python3 scripts/generate_comparison.py --original playlist.m3u --mixed output.mp3

# 7. Document
python3 scripts/generate_documentation.py --transitions transitions.json
```

---

## Why This Showcase is Powerful

### Demonstrates All Phases Working Together
- **Phase 1 + 2:** Early bass control (visible in spectrogram)
- **Phase 4:** Natural variation (audible in listening test)
- **Combined:** Professional mix, not automation

### Validates Research
- Real DJ technique research implemented and proven
- Before/after comparison shows the difference
- Metrics back up the subjective improvements

### Pushes System Limits
- Full album (30-60 min)
- 20-30+ transitions
- Diverse track characteristics
- Complex mixing scenarios

### Production-Ready Proof
- Showcases what the system can do
- Ready for user demonstrations
- Portfolio piece for the project

---

## Next Steps

1. **Find/Confirm Rusty Chains Album** - Do you have the tracks?
2. **Start with Existing Test Tracks** - Validate on what's available
3. **Generate Showcase** - Run the full pipeline
4. **Iterate** - Adjust parameters based on results
5. **Document** - Create final showcase with analysis

---

## Questions for Max

1. **Rusty Chains availability?** Do you have the album files available?
   - If YES: What's the path?
   - If NO: Should we use available test tracks or create synthetic showcase?

2. **Output preferences?**
   - Full album mix (~40-60 min)?
   - Shorter highlight reel (~10-15 min)?
   - Both?

3. **Analysis depth?**
   - Full spectral analysis + before/after?
   - Just the MP3 output?
   - Include listening notes?

---

**Status:** Ready to implement - awaiting confirmation on track availability and preferences. 🎧
