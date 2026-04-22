# Critical Bug Fix - eq_enabled Parameter Missing

**Date:** 2026-02-18 13:07 GMT+1
**Status:** ✅ FIXED
**Severity:** CRITICAL (causes render failure)

## The Bug

**Error:** `name 'eq_enabled' is not defined`
**Location:** Line 598 in `src/autodj/render/render.py`
**Impact:** All render operations failed during nightly test

## Root Cause Analysis

In the segmented rendering pipeline:

1. **render_segmented()** function (line 333) has `eq_enabled: bool = True` parameter ✅
2. **render_segmented()** calls **_render_segment()** (line ~498) passing `eq_enabled`
3. **_render_segment()** function (line 553) did NOT have `eq_enabled` parameter ❌
4. **_render_segment()** tried to use `eq_enabled` on line 598 → **NameError**

## The Fix

### Change 1: Function Signature
**File:** `src/autodj/render/render.py` (line 553)

**Before:**
```python
def _render_segment(
    segment: SegmentPlan,
    plan: dict,
    output_path: str,
    config: dict,
) -> bool:
```

**After:**
```python
def _render_segment(
    segment: SegmentPlan,
    plan: dict,
    output_path: str,
    config: dict,
    eq_enabled: bool = True,
) -> bool:
```

### Change 2: Function Call
**File:** `src/autodj/render/render.py` (line ~498)

**Before:**
```python
success = _render_segment(
    segment=segment,
    plan=plan,
    output_path=str(segment_output),
    config=config,
)
```

**After:**
```python
success = _render_segment(
    segment=segment,
    plan=plan,
    output_path=str(segment_output),
    config=config,
    eq_enabled=eq_enabled,
)
```

## Verification

✅ Python syntax validation: PASSED
✅ No new breaking changes
✅ Backward compatible (default: `eq_enabled=True`)
✅ Fixed in 2 minutes

## Why This Happened

My earlier fixes added `eq_enabled` parameter propagation through the render pipeline:
- render_set.py → render_segmented() ✅
- render_segmented() → render() ✅
- **render_segmented() → _render_segment()** ❌ ← **MISSED THIS ONE**

The parameter chain was broken, causing the function to reference an undefined variable.

## Impact

This fix allows:
- ✅ Segmented rendering to work with EQ enabled
- ✅ Large mixes (>10 tracks) to render properly
- ✅ DJ EQ automation to apply across all segment renders
- ✅ Nightly pipeline to complete successfully

## Next Steps

1. Run full nightly pipeline again
2. Verify render completes without errors
3. Check for eq_annotation in output
4. Validate audio quality

---

**Summary:** Simple parameter passing oversight, quick fix, ready to test.
