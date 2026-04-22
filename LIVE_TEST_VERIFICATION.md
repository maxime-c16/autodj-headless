# Live Test Verification - DJ EQ & Playlist Fixes

## Tests to Run After Nightly Completes

### Test 1: Playlist Randomization
```bash
# Check if random seed was selected (not hardcoded)
grep "Selected random seed\|Using explicit seed" data/logs/nightly-*.log | tail -1

# Expected output: "Selected random seed: XXXXXXX..."
# (If it says "Using explicit seed: ff5a6be4778892c8" = fix didn't work)
```

### Test 2: DJ EQ Annotations in Transitions
```bash
# Find the latest transitions file
LATEST=$(ls -1 data/playlists/transitions-*.json | tail -1)

# Check if eq_annotation field exists
jq ".$transitions[0] | has(\"eq_annotation\")" "$LATEST"

# Expected: true

# Check eq_opportunities count
jq '.transitions[0].eq_annotation.eq_opportunities | length' "$LATEST"

# Expected: > 0 (should have many opportunities)

# Check confidence levels
jq '.transitions[0].eq_annotation.eq_opportunities[] | .confidence' "$LATEST" | head -5

# Expected: Values between 0.5-0.9
```

### Test 3: Liquidsoap Script Contains Filters
```bash
# Check if eqffmpeg filters were added to script
grep -c "eqffmpeg" /tmp/last_render.liq

# Expected: > 100 (many filters across multiple tracks)

# Show example filter lines
grep "eqffmpeg" /tmp/last_render.liq | head -5

# Expected: Lines like:
# track_body_0 = eqffmpeg.bass(freq=70.0, gain=-8.0, track_body_0)
```

### Test 4: Verify No Errors
```bash
# Check logs for EQ-related errors
grep -i "error\|failed" data/logs/nightly-*.log | grep -i "eq\|annotation" | wc -l

# Expected: 0 or very few (< 5)

# Check overall error count
grep -i "ERROR" data/logs/nightly-*.log | wc -l

# Expected: Should be reasonable number (< 50)
```

### Test 5: Audio File Generated
```bash
# Check output MP3 exists and has reasonable size
ls -lh data/mixes/autodj-mix-*.mp3 | tail -1

# Expected: File size 50-300 MB, created today

# Check duration
ffprobe -hide_banner -show_format data/mixes/autodj-mix-*.mp3 2>/dev/null | grep duration | head -1

# Expected: ~2700 seconds (45 minutes)
```

### Test 6: Listen to Output
```bash
# Play the mix and listen for:
play data/mixes/autodj-mix-$(date +%Y-%m-%d).mp3

# ✅ Different mix from yesterday (if you run multiple days)
# ✅ Bass cuts at drop points (clear reduction, then rebuild)
# ✅ Smooth transitions between tracks
# ✅ NO clicks/pops (or significantly reduced)
# ✅ Professional DJ mixing sound
```

## Success Criteria

✅ All tests pass = All three fixes working
⚠️ Partial pass = Investigate specific areas
❌ Test fails = Fix didn't work, troubleshoot

## Expected Results Timeline

- Analyze phase: ~60-120s (per track analysis)
- Generate phase: ~30s (playlist generation)
- Render phase: ~300s (Liquidsoap rendering at 3x speed or slower)
- **Total: 8-15 minutes**

Monitor `/tmp/nightly-test.log` or `data/logs/nightly-*.log` for progress.
