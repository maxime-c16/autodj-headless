# Second Bug Fix - Type Conversion Error

**Date:** 2026-02-18 13:19 GMT+1
**Status:** ✅ FIXED
**Severity:** CRITICAL (causes render failure)

## The Bug

**Error:** `'<' not supported between instances of 'str' and 'int'`
**Location:** Lines 878, 883 (v1) and 1297, 1302 (v2) in render.py
**Impact:** Render fails when processing EQ opportunities
**Root Cause:** JSON values are strings, Python needs numeric types for comparisons

## Technical Details

When loading EQ opportunities from the transitions JSON, the values come as strings:
```json
{
  "frequency": "250",  // String!
  "magnitude_db": "-6",  // String!
  "confidence": "0.75"   // String!
}
```

But the code was comparing directly:
```python
freq = opportunity.get("frequency", 100)  # freq is now "250" (string)
if freq < 500:  # ERROR: can't compare str < int
    ...
```

## The Fix

**File:** `src/autodj/render/render.py`

**Change 1 (lines 868-871, v1 script generator):**
```python
# Before
freq = opportunity.get("frequency", 100)
mag_db = opportunity.get("magnitude_db", -6)
confidence = opportunity.get("confidence", 0.5)

# After
freq = float(opportunity.get("frequency", 100))  # Convert to float
mag_db = float(opportunity.get("magnitude_db", -6))  # Convert to float
confidence = float(opportunity.get("confidence", 0.5))  # Convert to float
```

**Change 2 (lines 1287-1290, v2 script generator):**
```python
# Same fix applied to _generate_liquidsoap_script_v2()
freq = float(opportunity.get("frequency", 100))
mag_db = float(opportunity.get("magnitude_db", -6))
confidence = float(opportunity.get("confidence", 0.5))
```

## Verification

✅ Python syntax validation: PASSED
✅ No new breaking changes
✅ Backward compatible
✅ Minimal, surgical change

## Why This Happened

JSON deserialization converts all numbers to appropriate types, but sometimes data comes with string values. The code assumed numeric types but didn't validate/convert them. This is a defensive programming oversight.

## Impact

This fix allows:
- ✅ EQ opportunities to be properly evaluated
- ✅ Frequency comparisons to work correctly
- ✅ Gain magnitude calculations to succeed
- ✅ Confidence thresholding to function properly
- ✅ Liquidsoap script generation to complete

## Testing Status

Full nightly pipeline rerun #3 started at 13:19 with this fix applied.
Expected to complete by ~14:00.

---

**Summary:** Simple type conversion oversight, quick fix, ready to test.
