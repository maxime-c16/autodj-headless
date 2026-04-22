# 2026-02-17 VALIDATION PLAN - Integration Test

## Test Scenario

**What:** Quick-mix with integrated DJEQSystem
**Tracks:** 2x "Never Enough" (test seed)
**EQ:** ON (using new integration module)
**Expected Duration:** ~5 minutes

## Validation Checkpoints

### 1. Module Loads Successfully ✓
```
from dj_eq_integration import IntegratedDJEQSystem
```

### 2. Drop Detection Works
- [ ] Should find 3-5 drops per track
- [ ] Confidence scores should be 0.5-0.99
- [ ] Should use 4-strategy approach
- [ ] Should log which strategy detected each drop

### 3. EQ Filter Application
- [ ] RBJ biquad filters designed correctly
- [ ] Envelope automation smooth (no clicks)
- [ ] Preset applied (default = 'moderate')
- [ ] Frequency response correct (-6dB @ 80Hz)

### 4. Audio Quality
- [ ] No clipping or distortion
- [ ] Smooth transitions at drop points
- [ ] No artifacts during envelope attack/release
- [ ] Final mix normalizes properly

### 5. Pipeline Integration
- [ ] transitions.json parsed correctly
- [ ] Drop times extracted from audio
- [ ] Drops matched to bar positions
- [ ] Output file saved correctly

### 6. Performance
- [ ] Processing completes in <5 minutes
- [ ] Liquidsoap mixing works with processed tracks
- [ ] No memory leaks or crashes

## What NOT to Expect (Yet)

These are separate and won't be in this test:
- ❌ Integration into aggressive_eq_annotator (next step)
- ❌ Integration into nightly render pipeline (after validation)
- ❌ UI feedback or logging of EQ effects (enhancement)

## Test Result Files

Expected output:
```
/home/mcauchy/autodj-headless/data/mixes/quick-mix-20260217-*.mp3
/tmp/autodj_eq_processed/track_*.wav (processed audio)
logs/dj-eq-*.log
```

## Success Criteria

✅ **PASS** if:
1. Mix renders without errors
2. Output file is created (>20MB)
3. No Python exceptions
4. Logs show drop detection running
5. Logs show EQ filters being applied
6. Audio plays without artifacts

❌ **FAIL** if:
1. Import errors
2. Drop detection crashes
3. Filter application fails
4. Output is corrupted or silent
5. Liquidsoap integration breaks

## Monitoring the Test

Check Docker logs:
```bash
docker logs autodj-dev | tail -50
```

Check for processed tracks:
```bash
ls -lh /tmp/autodj_eq_processed/
```

Check final mix:
```bash
ls -lh /home/mcauchy/autodj-headless/data/mixes/quick-mix-*.mp3
```

## If Test Fails

1. Check Docker logs for ImportError
2. Verify scipy.signal is available in container
3. Check if librosa is properly installed
4. Verify /tmp/autodj_eq_processed/ has write permissions
5. Check transitions.json is being generated

## Documentation After Success

If test passes:
1. ✅ Update MEMORY.md with test results
2. ✅ Document integration approach
3. ✅ Create integration guide for next developer
4. ✅ Mark old test scripts as "Integrated in dj_eq_integration.py"
5. ✅ Add to roadmap when full pipeline integration is next

## Next Steps After Validation

1. **Immediate:** Verify audio quality (listen to mix)
2. **Short-term:** Integrate into aggressive_eq_annotator
3. **Medium-term:** Add to nightly render pipeline
4. **Long-term:** Create presets configuration system

## Safeguards Added

1. ✅ CODE_REVIEW_CHECKLIST.md - Before coding checklist
2. ✅ check_abandoned_code.sh - Automated code discovery
3. ✅ This validation plan - Testing protocol
4. ✅ LESSON documentation - What happened & why

## Timeline

- 23:27 - Test started
- ~23:32 - Container ready, Liquidsoap starting
- ~23:33-23:35 - Processing tracks
- ~23:35-23:40 - Mixing
- ~23:40 - Results available
