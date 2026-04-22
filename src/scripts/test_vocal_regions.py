#!/usr/bin/env python3
"""
Test Phase 1: Vocal Region Detection

Loads test tracks and verifies vocal region detection works correctly.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.autodj.analyze.structure import detect_vocal_regions, detect_vocal, analyze_track_structure
from src.autodj.analyze.audio_loader import AudioCache
from src.autodj.db import Database

def test_vocal_regions():
    """Test vocal region detection on database tracks."""
    
    print("=" * 80)
    print("PHASE 1 TEST: Vocal Region Detection")
    print("=" * 80)
    
    # Connect to database
    db = Database()
    db.connect()
    
    # Get all tracks
    tracks = db.list_tracks()
    print(f"\n📊 Testing {len(tracks)} tracks from database\n")
    
    # Test each track
    for i, track in enumerate(tracks, 1):
        print(f"\n{i}. {track.title} by {track.artist}")
        print(f"   BPM: {track.bpm:.1f}, Key: {track.key}")
        print(f"   File: {track.file_path}")
        
        # Try to load audio
        try:
            audio_cache = AudioCache(sample_rate=44100)
            audio_data, sr = audio_cache.load(track.file_path, mono=True)
            print(f"   ✓ Audio loaded: {len(audio_data)/sr:.1f}s, {sr} Hz")
            
            # Test vocal detection (boolean)
            has_vocal = detect_vocal(audio_data, sr)
            print(f"   Has vocal: {has_vocal}")
            
            # Test vocal region detection
            if has_vocal:
                vocal_regions = detect_vocal_regions(audio_data, sr)
                print(f"   Vocal regions detected: {len(vocal_regions)}")
                
                for j, (start, end) in enumerate(vocal_regions, 1):
                    duration = end - start
                    print(f"      Region {j}: {start:.2f}s - {end:.2f}s ({duration:.2f}s)")
            else:
                print(f"   No vocal content detected (skipping region analysis)")
            
            audio_cache.clear()
            
        except FileNotFoundError:
            print(f"   ✗ File not found: {track.file_path}")
        except Exception as e:
            print(f"   ✗ Error: {e}")
    
    db.disconnect()
    
    print("\n" + "=" * 80)
    print("✅ PHASE 1 TEST COMPLETE")
    print("=" * 80)

if __name__ == "__main__":
    test_vocal_regions()
