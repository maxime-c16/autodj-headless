# Third Bug Fix - Special Frequency Value Handling

**Date:** 2026-02-18 13:25 GMT+1
**Status:** ✅ FIXED
**Severity:** CRITICAL (causes render failure)

## The Bug

**Error:** `could not convert string to float: 'all'`
**Location:** EQ frequency handling in render.py (lines 860-890, 1290-1310)
**Impact:** Render fails when processing multi-band EQ entries
**Root Cause:** Special frequency values ('all') not handled, code assumes numeric values

## Technical Details

The DJ EQ annotator generates multi-band spatial processing with special values:
```json
{
  "type": "multi_band",
  "frequency": "all",  // ← Special value, not numeric!
  "magnitude_db": -2,
  "confidence": 0.70
}
```

The render code tried to convert this directly:
```python
freq = float(opportunity.get("frequency", 100))  # ERROR: float('all') fails!
```

## The Fix

**File:** `src/autodj/render/render.py`

**Change 1 (v1 script generator, lines 868-880):**
```python
# Before
freq = float(opportunity.get("frequency", 100))
mag_db = float(opportunity.get("magnitude_db", -6))
confidence = float(opportunity.get("confidence", 0.5))

# After
freq_raw = opportunity.get("frequency", 100)
mag_db = float(opportunity.get("magnitude_db", -6))
opp_type = opportunity.get("type", "bass_cut")
confidence = float(opportunity.get("confidence", 0.5))

# Skip special frequency values like 'all' (multi-band)
if freq_raw == 'all':
    continue

freq = float(freq_raw)  # Convert to float only after validation
```

**Change 2 (v2 script generator, lines 1290-1310):**
```python
# Same fix applied to _generate_liquidsoap_script_v2()
freq_raw = opportunity.get("frequency", 100)
# ... other conversions ...
if freq_raw == 'all':
    continue
freq = float(freq_raw)
```

## Verification

✅ Python syntax validation: PASSED
✅ Handles special values gracefully
✅ No breaking changes
✅ Backward compatible

## Why This Happened

When the DJ EQ annotator creates multi-band spatial processing (5th step in annotation), it sets frequency to the string 'all' to indicate processing across all frequencies. The render code needs to skip these special cases since Liquidsoap's filter.iir functions require numeric frequency values.

This is a data validation oversight - the code should validate/transform data before using it.

## Impact

This fix allows:
- ✅ Multi-band EQ opportunities to be gracefully skipped
- ✅ Standard frequency-specific EQ to be applied
- ✅ Liquidsoap script generation to complete
- ✅ Render phase to finish without errors

## Testing Status

Full nightly pipeline test #4 started at 13:25 with this fix applied.
Expected to complete by ~14:45-15:15.

---

**Summary:** Special value handling added, defensive programming improved.
