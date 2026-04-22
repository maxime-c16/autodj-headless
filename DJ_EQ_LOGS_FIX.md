# DJ EQ Logging Issue & Fix

## Problem
Both nightly runs (manual Feb 16 + cron Feb 17) generated **complete mixes** successfully, but DJ EQ debug logs were NOT created.

### Error Encountered
```
[WARNING] ⚠️ EQ annotation failed: [Errno 13] Permission denied: '/home/mcauchy'
```

### Root Cause
The Docker container (`autodj-dev`) runs as user `autodj`, not `mcauchy`. When the render process tries to write DJ EQ logs to `/home/mcauchy/autodj-headless/data/logs/`, it fails because the container user doesn't have write permission to the host's home directory.

## What Still Works
- ✅ Mix rendering completes
- ✅ Liquidsoap logs are created in `/app/data/logs/` (container path)
- ✅ Audio output (MP3) is generated successfully

## What Needs Fixing
- ❌ DJ EQ debug logs (`dj-eq-*.log`) not created
- ❌ Detailed skill analysis not logged
- ❌ Beat detection data not captured

## Solutions

### Option 1: Volume Mount Fix (RECOMMENDED)
Update `docker-compose.dev.yml`:
```yaml
services:
  autodj-dev:
    volumes:
      # ... existing volumes ...
      - ./data/logs:/app/data/logs  # Ensure this is writable
      - ./data/mixes:/app/data/mixes
```

Change render.py to use container paths:
```python
# Instead of:
log_path = Path('/home/mcauchy/autodj-headless/data/logs')

# Use:
log_path = Path('/app/data/logs')
```

Then copy logs back to host after render:
```bash
docker cp autodj-dev:/app/data/logs/dj-eq-*.log ./data/logs/
```

### Option 2: Container User Fix
Run container with host user:
```yaml
services:
  autodj-dev:
    user: "1000:1000"  # Change to match host user
```

### Option 3: Environment Override
Add to `render_set.py`:
```python
import os
log_dir = os.environ.get('LOG_DIR', '/app/data/logs')
# DJ EQ will write to $LOG_DIR
```

## Testing After Fix
```bash
# After render completes:
ls -lh /home/mcauchy/autodj-headless/data/logs/dj-eq-*.log

# Should show debug logs like:
# dj-eq-debug-20260217-013116.log
# dj-eq-skills-20260217-013116.log
# dj-eq-filters-20260217-013116.log
```

## Files Affected
- `src/autodj/render/render.py` - Sets `log_dir` for DJ EQ debug logger
- `src/scripts/render_set.py` - Calls render.py
- `docker/compose.dev.yml` - Volume mounts

## Current Status (Feb 17, 2026)
- Both manual + cron runs: **Mixes generated ✅**
- DJ EQ logs: **Pending permission fix ❌**
- Liquidsoap render logs: **Available at `/app/data/logs/liquidsoap-*.log` ✅**
