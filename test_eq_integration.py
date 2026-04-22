#!/usr/bin/env python3
"""
Test EQ integration: verify eq_annotation flows through the pipeline.
"""

import sys
sys.path.insert(0, '/home/mcauchy/autodj-headless')

import json
from pathlib import Path
from autodj.render.render import _generate_liquidsoap_script_v2

# Create a sample plan with eq_annotation
plan = {
    "playlist_id": "test-eq",
    "mix_duration_seconds": 300,
    "generated_at": "2026-02-18",
    "transitions": [
        {
            "track_index": 0,
            "track_id": "track-1",
            "file_path": "/tmp/dummy1.mp3",
            "title": "Test Track 1",
            "artist": "Artist A",
            "bpm": 127.0,
            "target_bpm": 127.0,
            "cue_in_frames": 0,
            "cue_out_frames": 5000000,
            "transition_type": "bass_swap",
            "overlap_bars": 8,
            "hpf_frequency": 200.0,
            "lpf_frequency": 2500.0,
            "next_track_id": "track-2",
            # 🎛️ KEY TEST: eq_annotation field
            "eq_annotation": {
                "track": "dummy1.mp3",
                "duration_seconds": 180,
                "detected_bpm": 127.0,
                "total_beats": 508,
                "drops": [],
                "eq_opportunities": [
                    {
                        "type": "bass_cut",
                        "bar": 4,
                        "frequency": 70.0,
                        "magnitude_db": -8.0,
                        "bars_duration": 1,
                        "confidence": 0.85,
                        "description": "bass cut at drop"
                    },
                    {
                        "type": "high_cut",
                        "bar": 8,
                        "frequency": 5000.0,
                        "magnitude_db": -6.0,
                        "bars_duration": 2,
                        "confidence": 0.75,
                        "description": "high cut for transition"
                    }
                ],
                "total_eq_skills": 2
            }
        },
        {
            "track_index": 1,
            "track_id": "track-2",
            "file_path": "/tmp/dummy2.mp3",
            "title": "Test Track 2",
            "artist": "Artist B",
            "bpm": 128.0,
            "target_bpm": 128.0,
            "cue_in_frames": 0,
            "cue_out_frames": 5000000,
            "transition_type": "bass_swap",
            "overlap_bars": 8,
            "hpf_frequency": 200.0,
            "lpf_frequency": 2500.0,
            "next_track_id": None,
            # No eq_annotation for track 2 (optional)
        }
    ]
}

config = {
    "render": {
        "output_format": "mp3",
        "mp3_bitrate": 320,
    }
}

print("=" * 80)
print("TEST: EQ Integration in Liquidsoap Script Generation")
print("=" * 80)
print()

# Generate the script
try:
    script = _generate_liquidsoap_script_v2(plan, "/tmp/test.wav", config, temp_loop_dir=None, eq_enabled=True)
    print("✅ Script generation successful!")
    print()
    
    # Check for EQ-related content
    script_lines = script.split('\n')
    
    # Look for DJ EQ comments and filter commands
    eq_lines = [i for i, line in enumerate(script_lines) if 'DJ EQ' in line or 'eqffmpeg' in line]
    
    print(f"Found {len(eq_lines)} lines with EQ references")
    print()
    
    if eq_lines:
        print("EQ-related script lines:")
        for idx in eq_lines[:20]:  # First 20 hits
            print(f"  Line {idx}: {script_lines[idx]}")
        print()
    
    # Check specifically for eq_annotation being read
    if "eq_annotation = trans.get" in script or "eq_annotation =" in script:
        print("❌ ERROR: Found raw code in generated script (should be comments only)")
    else:
        print("✅ Good: Script doesn't contain raw code (variable names are in comments)")
    
    # Count filter commands
    filter_count = sum(1 for line in script_lines if 'eqffmpeg' in line)
    print()
    print(f"Filter commands generated: {filter_count}")
    if filter_count == 0:
        print("⚠️  WARNING: No eqffmpeg filter commands found in script")
        print("    This might indicate eq_annotation wasn't processed")
    else:
        print(f"✅ Good: Found {filter_count} filter commands in script")
    
    # Check for the specific EQ commands we expect
    expected_commands = {
        'eqffmpeg.bass': False,
        'eqffmpeg.mid': False,
        'eqffmpeg.high': False,
    }
    
    for cmd in expected_commands:
        if cmd in script:
            expected_commands[cmd] = True
    
    print()
    print("Filter types used:")
    for cmd, found in expected_commands.items():
        status = "✅" if found else "❌"
        print(f"  {status} {cmd}")
    
    print()
    print("=" * 80)
    print("RESULT: EQ annotation integration is", "WORKING" if filter_count > 0 else "NOT WORKING")
    print("=" * 80)
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
