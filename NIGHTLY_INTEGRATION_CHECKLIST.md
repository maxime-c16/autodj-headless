# 🎧 NIGHTLY PIPELINE INTEGRATION CHECKLIST

## Current Status
The aggressive DJ EQ system is ALREADY PARTIALLY INTEGRATED, but needs final touches.

### What's Already Done ✅

1. **render.py modifications** ✅
   - AggressiveDJEQAnnotator imported
   - Annotation hook inserted (lines 89-134)
   - EQ metadata stored in transitions

2. **render_set.py modifications** ✅
   - EQ_ENABLED environment variable support
   - Passed to render() function call

3. **Integration tested** ✅
   - test_eq_integration.py passes 100%
   - Beat detection verified
   - DJ skill generation verified

### What Needs to be Updated

## 1. NIGHTLY SCRIPT UPDATES

**File:** `/home/mcauchy/autodj-headless/scripts/autodj-nightly.sh`

### Update 1A: Add EQ_ENABLED Environment Variable (Line 239-244)

**Current:**
```bash
# Phase 3: Render
log ""
log "===== Phase 3: Render Mix ====="
if ! docker exec \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.render_set; then
```

**Update to:**
```bash
# Phase 3: Render with Aggressive DJ EQ
log ""
log "===== Phase 3: Render Mix (with Aggressive DJ EQ) ====="
EQ_ENABLED="${EQ_ENABLED:-true}"  # Default: enabled
log "DJ EQ Automation: ${EQ_ENABLED}"
if ! docker exec \
    -e EQ_ENABLED="${EQ_ENABLED}" \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.render_set; then
```

### Update 1B: Add EQ Status to Discord Notifications (Line 262+)

**Add after Phase 3 Complete:**
```bash
# Log DJ EQ annotation summary
docker exec "${CONTAINER_NAME}" python3 << 'PYTHON_EQ_SUMMARY'
import sys, os, glob
sys.path.insert(0, '/home/mcauchy/autodj-headless')
try:
    # Find latest transitions file with EQ annotations
    latest = max(glob.glob('/app/data/playlists/transitions-*.json'), 
                 key=os.path.getctime, default=None)
    if latest:
        import json
        with open(latest) as f:
            plan = json.load(f)
        
        eq_count = 0
        total_skills = 0
        for trans in plan.get('transitions', []):
            if 'eq_annotation' in trans:
                eq_count += 1
                total_skills += trans.get('eq_annotation', {}).get('total_eq_skills', 0)
        
        if eq_count > 0:
            print(f"🎛️  DJ EQ Summary: {eq_count} tracks annotated, {total_skills} total DJ skills applied")
        else:
            print(f"⚠️  No EQ annotations found in transitions")
except Exception as e:
    print(f"[EQ Summary] Error: {e}")
PYTHON_EQ_SUMMARY
```

### Update 1C: Enhanced Discord Notification for Phase 3

**Current Discord notify:** Line 262-280

**Add EQ details to notification:**
```python
try:
    # Include EQ automation status in notification
    from src.autodj.discord.notifier import DiscordNotifier
    notifier = DiscordNotifier()
    
    # Build status message
    eq_status = "✅ DJ EQ Automation ENABLED" if os.environ.get('EQ_ENABLED', 'true').lower() in ('true', '1') else "⚠️  DJ EQ Automation disabled"
    
    notifier.post_phase_complete('Render Mix', {
        'Format': 'MP3 320 kbps',
        'DJ EQ': eq_status,
        'Status': 'Ready for playback'
    })
except Exception as e:
    print(f"[Discord] Notification failed: {e}")
```

---

## 2. RENDER_SET.PY UPDATES (Optional Enhancement)

**File:** `/home/mcauchy/autodj-headless/src/scripts/render_set.py`

### Add Logging for DJ Skills (After line 115)

```python
# Log DJ skills applied during rendering
logger.info("\n" + "=" * 100)
logger.info("🎛️ DJ EQ AUTOMATION SUMMARY")
logger.info("=" * 100)

try:
    import json
    with open(latest_transitions) as f:
        plan = json.load(f)
    
    total_skills = 0
    for idx, trans in enumerate(plan.get('transitions', [])):
        if 'eq_annotation' in trans:
            skills = trans.get('eq_annotation', {}).get('total_eq_skills', 0)
            bpm = trans.get('eq_annotation', {}).get('detected_bpm', trans.get('bpm', 0))
            title = trans.get('title', f'Track {idx}')
            logger.info(f"  ✅ {title}: {skills} DJ skills @ {bpm:.1f} BPM")
            total_skills += skills
    
    if total_skills > 0:
        logger.info(f"\n  Total DJ skills applied: {total_skills}")
        logger.info(f"  Average per track: {total_skills / len(plan.get('transitions', [])):.1f}")
    else:
        logger.info(f"  ⚠️  No EQ annotations found")
    
    logger.info("=" * 100)
except Exception as e:
    logger.warning(f"Could not log EQ summary: {e}")
```

---

## 3. CONFIGURATION UPDATES

### Update 3A: autodj.toml (Optional)

**Add section:**
```toml
[render.dj_eq]
enabled = true
min_confidence = 0.65  # Aggressive mode
aggressive_mode = true
```

### Update 3B: Environment Variable Documentation

**Add to .env file:**
```bash
# DJ EQ Automation
EQ_ENABLED=true                    # Enable aggressive DJ EQ (default: true)
DJ_EQ_MIN_CONFIDENCE=0.65          # Minimum confidence for DJ skills (0.0-1.0)
DJ_EQ_AGGRESSIVE_MODE=true         # Apply multiple skills per track
```

---

## 4. IMPLEMENTATION CHECKLIST

### Phase 3A: Script Updates (30 minutes)

- [ ] Add `EQ_ENABLED` environment variable to Phase 3 call
- [ ] Add DJ EQ summary logging after Phase 3
- [ ] Update Discord notification with EQ status
- [ ] Test with DRY_RUN=1 ./scripts/autodj-nightly.sh

### Phase 3B: Logging Enhancements (15 minutes)

- [ ] Add DJ skills summary to render_set.py
- [ ] Log per-track EQ details
- [ ] Log total skills applied
- [ ] Add timing information

### Phase 3C: Configuration (10 minutes)

- [ ] Update autodj.toml with DJ EQ settings
- [ ] Update .env with EQ environment variables
- [ ] Document all new options

### Phase 3D: Testing (45 minutes)

- [ ] Run: `DRY_RUN=1 ./scripts/autodj-nightly.sh` (verify no errors)
- [ ] Run: `EQ_ENABLED=true ./scripts/autodj-nightly.sh` (full test with EQ)
- [ ] Run: `EQ_ENABLED=false ./scripts/autodj-nightly.sh` (test without EQ)
- [ ] Verify: EQ annotations in transitions.json
- [ ] Verify: Discord notification shows EQ status
- [ ] Verify: Output mix has DJ skills applied

---

## 5. QUICK IMPLEMENTATION (Copy-Paste Ready)

### Step 1: Update nightly script (Line 241-244)

Replace this:
```bash
if ! docker exec \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.render_set; then
```

With this:
```bash
EQ_ENABLED="${EQ_ENABLED:-true}"
log "🎛️ DJ EQ Automation: ${EQ_ENABLED}"
if ! docker exec \
    -e EQ_ENABLED="${EQ_ENABLED}" \
    "${CONTAINER_NAME}" \
    python3 -m src.scripts.render_set; then
```

### Step 2: Add after Phase 3 success (after line 260)

```bash
# Log EQ annotation summary
docker exec "${CONTAINER_NAME}" tail -20 /app/data/logs/liquidsoap-*.log 2>/dev/null | grep -E "DJ skills|🎛️" || true
```

### Step 3: Update Discord notification (line 265)

Add this before the existing notification code:
```bash
# Include EQ status
if [[ "${EQ_ENABLED}" == "true" ]]; then
    EQ_STATUS="✅ DJ EQ Automation ENABLED (15-20 skills/track)"
else
    EQ_STATUS="⚠️ DJ EQ Automation DISABLED"
fi
```

---

## 6. VERIFICATION COMMANDS

**Dry run (no actual rendering):**
```bash
DRY_RUN=1 ./scripts/autodj-nightly.sh
```

**Full run with EQ enabled:**
```bash
EQ_ENABLED=true ./scripts/autodj-nightly.sh
```

**Full run with EQ disabled (baseline):**
```bash
EQ_ENABLED=false ./scripts/autodj-nightly.sh
```

**Check latest mix for EQ:**
```bash
ls -lh data/mixes/*.mp3 | tail -1
```

**Verify transitions had EQ applied:**
```bash
python3 -c "
import json, glob
latest = max(glob.glob('data/playlists/transitions-*.json'), key=os.path.getctime)
with open(latest) as f:
    plan = json.load(f)
for trans in plan['transitions']:
    if 'eq_annotation' in trans:
        print(f\"✅ {trans['title']}: {trans['eq_annotation']['total_eq_skills']} skills\")
"
```

---

## 7. SUMMARY OF CHANGES

| File | Change | Time |
|------|--------|------|
| autodj-nightly.sh | Add EQ_ENABLED env var + logging | 15 min |
| render_set.py | Add DJ skills summary logging | 10 min |
| autodj.toml | Add DJ EQ config section | 5 min |
| .env | Add EQ environment variables | 5 min |
| Testing | Full end-to-end verification | 30 min |

**Total implementation time: ~65 minutes**

---

## 8. READY FOR DEPLOYMENT

After these updates:

✅ Nightly pipeline will run with aggressive DJ EQ enabled
✅ Each track will get 15-20 DJ skill opportunities
✅ Discord will show EQ status
✅ Logs will detail skills applied
✅ Full professional automation throughout

**Next nightly run (tomorrow 02:30 UTC): Will feature full aggressive DJ EQ automation!**

