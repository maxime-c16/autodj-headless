# 📚 Brother Beatus — The Librarian of Truth (MIR Analyzer)

**Role:** Analysis & metadata extraction (BPM, key, cues)

**Personality:**
- Silent, exacting, measurement-first
- Works offline; never guesses during live generation

**Real function:** Runs analysis on tracks and populates the DB and tags.

Inputs
- Audio files (music library)
- Analysis config (e.g., aubio hop sizes, confidence thresholds)

Outputs
- `tracks` DB rows with `bpm`, `key`, `cue_in_frames`, `cue_out_frames`
- Optionally writes tags to files (ID3/MP4/FLAC)

Mapping to code
- `src/autodj/analyze/bpm.py`
- `src/autodj/analyze/key.py`
- `src/autodj/analyze/cues.py`
- `src/scripts/analyze_library.py`

Tests to add
- `test_bpm_detection_is_within_tolerance()`
- `test_key_detection_fallbacks()`
- `test_cue_detection_min_duration()`

Notes
- Beatus is the reason the system scales — analysis happens once per track and is stored.
- Keep memory usage constrained (limits in `autodj.toml`).
