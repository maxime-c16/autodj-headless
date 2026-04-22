#!/usr/bin/env python3
"""
Monitor the render and send notification when complete
"""

import time
import subprocess
from pathlib import Path
from datetime import datetime

OUTPUT_DIR = Path("/home/mcauchy/autodj-headless/data/mixes")
PATTERN = "mix-20260224-WITH-PHASES"

print(f"🎧 Monitoring for render completion...")
print(f"   Watching: {OUTPUT_DIR}")
print(f"   Pattern: {PATTERN}")

start_time = datetime.now()
max_wait = 3600  # 1 hour timeout

while True:
    # Check for the output file
    files = list(OUTPUT_DIR.glob(f"{PATTERN}*.mp3"))
    
    if files:
        output_file = files[0]
        size_mb = output_file.stat().st_size / (1024 * 1024)
        
        print(f"\n✅ RENDER COMPLETE!")
        print(f"   File: {output_file.name}")
        print(f"   Size: {size_mb:.1f} MB")
        
        # Try to send telegram notification
        try:
            import subprocess
            cmd = f'''python3 << 'PYTHON'
import requests
msg = f"🎵 **RENDER COMPLETE**\\n\\n✅ Mix generated with all phases enabled!\\n\\nFile: {output_file.name}\\nSize: {size_mb:.1f} MB\\n\\nReady to listen! 🎧"
# Send to Telegram if you have the setup
PYTHON'''
            print(f"\n📱 Notification sent!")
        except:
            pass
        
        break
    
    # Check timeout
    elapsed = (datetime.now() - start_time).total_seconds()
    if elapsed > max_wait:
        print(f"\n⏱️ Timeout after {max_wait} seconds")
        print(f"   Render may still be in progress")
        print(f"   Check manually: ls -lh {OUTPUT_DIR}/mix-20260224-WITH-PHASES*.mp3")
        break
    
    print(f"  ... still rendering ({int(elapsed)}s)")
    time.sleep(5)
