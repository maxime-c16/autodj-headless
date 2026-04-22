#!/usr/bin/env python3
"""
Simplified EQ Solutions Tester - uses actual render pipeline

Tests all 4 solutions using the existing render() function
"""

import sys
import json
from pathlib import Path

# Add project to path
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

from autodj.render.render import render

def test_all_solutions():
    """Test all 4 EQ solutions"""
    
    # Test data
    transitions_json = "/app/data/playlists/transitions-20260222-013150.json"
    config = {
        "render": {
            "output_format": "mp3",
            "mp3_bitrate": 320
        }
    }
    
    strategies = ["ladspa", "ffmpeg", "calf", "hybrid"]
    results = {}
    
    for strategy in strategies:
        output_path = f"/tmp/eq_solution_{strategy}_test.mp3"
        
        print(f"\n{'='*70}")
        print(f"🧪 Testing: {strategy.upper()}")
        print(f"{'='*70}")
        print(f"   Output: {output_path}")
        
        try:
            # Call render with specific strategy
            success = render(
                transitions_json_path=transitions_json,
                output_path=output_path,
                config=config,
                eq_enabled=True,
                eq_strategy=strategy
            )
            
            if success and Path(output_path).exists():
                size_mb = Path(output_path).stat().st_size / (1024 * 1024)
                print(f"   ✅ PASS - Output size: {size_mb:.1f} MB")
                results[strategy] = {"status": "PASS", "size_mb": size_mb}
            else:
                print(f"   ❌ FAIL - Render returned False or no output")
                results[strategy] = {"status": "FAIL"}
                
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            results[strategy] = {"status": "ERROR", "error": str(e)}
    
    # Summary
    print(f"\n\n{'='*70}")
    print(f"📊 SUMMARY")
    print(f"{'='*70}\n")
    
    for strategy, result in results.items():
        status_icon = "✅" if result["status"] == "PASS" else "❌"
        print(f"{status_icon} {strategy.upper():20} {result['status']}")
        if "size_mb" in result:
            print(f"   └─ {result['size_mb']:.1f} MB")
    
    passed = sum(1 for r in results.values() if r["status"] == "PASS")
    total = len(results)
    
    print(f"\n✅ Passed: {passed}/{total}")
    print(f"📁 Test files in: /tmp/")
    
    return 0 if passed > 0 else 1

if __name__ == "__main__":
    sys.exit(test_all_solutions())
