# Database Integration Analysis - Beat-Synced DJ EQ

## ✅ NO NEW DB COLUMNS NEEDED!

The existing `track_analysis` table already has everything we need:

```sql
CREATE TABLE track_analysis (
    track_id TEXT PRIMARY KEY,
    sections_json TEXT,          ← Can store EQ annotations here!
    cue_points_json TEXT,
    loop_regions_json TEXT,
    energy_profile_json TEXT,
    spectral_json TEXT,
    loudness_json TEXT,
    kick_pattern TEXT,
    downbeat_seconds REAL,
    total_bars INTEGER,
    has_vocal INTEGER,
    analyzed_at TEXT NOT NULL
);
```

## 🎯 STORAGE STRATEGY

### Option 1: Add to existing `sections_json` (EASIEST) ✅ RECOMMENDED

Store EQ annotations with section data:
```json
{
  "sections": [...],
  "eq_annotations": {
    "detected_bpm": 110.0,
    "drops": [...],
    "eq_opportunities": [...]
  }
}
```

**Pros:**
- No schema migration needed
- Already parsed by existing code
- Follows current pattern

**Cons:**
- Mixes section & EQ data (minor)

### Option 2: Add new `eq_json` column (CLEANER)

```sql
ALTER TABLE track_analysis ADD COLUMN eq_json TEXT;
```

**Pros:**
- Separates concerns
- Cleaner queries

**Cons:**
- Requires schema migration (v3)
- Backward compatibility issue

### Option 3: Add to `spectral_json` (ALSO WORKS)

Since spectral analysis is beat-dependent.

**Pros:**
- Related to beat detection
- No new column

**Cons:**
- Mixes domains

## 🔄 RECOMMENDED INTEGRATION PATH

### For NOW (no DB changes):

1. **Store annotations in JSON files** (what we're doing)
   ```
   /tracks/{artist}/{track}/eq_annotation.json
   ```

2. **Reference in analysis** - add to sections_json:
   ```python
   analysis['sections_json'] = {
       'sections': [...],
       'eq_metadata': {
           'bpm': 110.0,
           'eq_opportunities': 19,
           'annotation_file': 'eq_annotation.json'
       }
   }
   ```

3. **No DB changes** - works immediately!

### For LATER (better organization):

When consolidating, add migration:
```sql
-- Migration v3: Add dedicated EQ analysis column
ALTER TABLE track_analysis ADD COLUMN eq_annotations_json TEXT;

-- Then migrate from sections_json references
UPDATE track_analysis
SET eq_annotations_json = json_extract(sections_json, '$.eq_metadata')
WHERE json_extract(sections_json, '$.eq_metadata') IS NOT NULL;
```

## 📊 FURTHER ANALYSIS NEEDED?

### What's ALREADY analyzed:

✅ BPM detection (librosa + aubio)
✅ Section detection (structure analysis)
✅ Energy profiles (spectral analysis)
✅ Kick patterns (percussive analysis)
✅ Vocal detection (spectral/harmonic)
✅ Loudness (LUFS measurement)

### What the NEW system ADDS:

✅ Beat grid (librosa.beat_track)
✅ Drop snapping (beat-aligned timing)
✅ DJ skill opportunities (greedy selector)
✅ Confidence scores (per opportunity)
✅ Multi-band EQ parameters (peaking filters)

### What we DON'T need to add:

❌ New spectral analysis (covered by existing)
❌ New loudness measurement (covered by existing)
❌ New section detection (covered by existing)
❌ New BPM detection (covered by existing)

**The new system REUSES existing analysis** - it just adds strategic interpretation!

## 🚀 IMMEDIATE NEXT STEPS

### 1. NO Schema Change (simplest)
```python
# In aggressive_eq_annotator.py

def store_annotation(self, track_id, annotation):
    # Option A: Store as file (current)
    with open(f'eq_annotation_{track_id}.json', 'w') as f:
        json.dump(annotation, f)
    
    # Option B: Store in DB sections_json
    db.update_track_analysis(
        track_id,
        sections_json=json.dumps({
            **existing_sections,
            'eq_metadata': annotation
        })
    )
```

### 2. Reference in Render Pipeline
```python
# In render.py

# Fetch annotation from DB or file
annotation = db.get_track_analysis(track_id).get('eq_metadata')

# Apply EQ skills
for opportunity in annotation['eq_opportunities']:
    if opportunity['confidence'] >= 0.65:
        apply_dj_skill(audio, opportunity)
```

### 3. Ready for Nightly Tomorrow
```bash
./scripts/autodj-nightly.sh

# Pipeline flow:
# 1. Analyze tracks (existing)
# 2. Add EQ annotations (NEW - aggressive_eq_annotator.py)
# 3. Generate playlists (existing)
# 4. Render mix with EQ (NEW - integrated)
```

## ✅ DECISION

**Don't add DB columns yet.** 

- Existing JSON fields handle everything
- Can store annotations in `sections_json` or as files
- No schema migration needed
- Ready to go TODAY
- Can optimize later (migration v3)

The system can analyze and apply DJ skills WITHOUT any database changes!
