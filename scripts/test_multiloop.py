#!/usr/bin/env python3
"""
Test script for multi-loop detection (Phase 2026-02-11).

Demonstrates:
1. Loop region extraction from structure analysis
2. JSON storage in database
3. Loop querying API
4. Creative mixing use cases
"""

import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from autodj.db import Database


def demo_get_loops():
    """Demo: Get loops for a specific track."""
    db = Database()
    db.connect()

    # Get first track with loops
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT id, title, artist, loops_json FROM tracks WHERE loops_json IS NOT NULL LIMIT 1"
    )
    row = cursor.fetchone()

    if not row:
        print("❌ No tracks with loop data yet (run analysis first)")
        db.disconnect()
        return

    track_id, title, artist, loops_json = row
    print(f"\n📍 Track: {artist} — {title}")
    print(f"   ID: {track_id}\n")

    # Use new get_loops_for_track API
    loops = db.get_loops_for_track(track_id)

    if not loops:
        print("   ⚠️  No loops detected")
    else:
        print(f"   🎵 {len(loops)} loop regions detected:\n")
        for i, loop in enumerate(loops, 1):
            print(f"   {i}. {loop['label'].upper()}")
            print(
                f"      Position: {loop['start_sec']:.1f}s - {loop['end_sec']:.1f}s "
                f"({loop['length_bars']} bars)"
            )
            print(
                f"      Quality: Energy {loop['energy']:.1%} | "
                f"Stability {loop['stability']:.1%}"
            )
            print()

    db.disconnect()


def demo_creative_mixing():
    """Demo: Find loops suitable for creative layering."""
    db = Database()
    db.connect()

    print("\n🎹 CREATIVE MIXING - Multi-Loop Layering Demo\n")
    print("="*60)

    # Get all drop loops (best for layering)
    cursor = db.conn.cursor()
    cursor.execute(
        """
        SELECT id, title, artist, loops_json FROM tracks 
        WHERE loops_json LIKE '%drop_loop%'
        LIMIT 3
        """
    )
    rows = cursor.fetchall()

    if not rows:
        print("❌ No tracks with drop loops yet (run analysis first)")
        db.disconnect()
        return

    print(f"\n✅ Found {len(rows)} tracks with drop loops\n")

    for track_id, title, artist, loops_json in rows:
        loops = json.loads(loops_json)
        drop_loops = [l for l in loops if l["label"] == "drop_loop"]

        if drop_loops:
            print(f"🎵 {artist} — {title}")
            print(f"   Drop loops available for layering:")
            for loop in drop_loops:
                print(
                    f"   • {loop['length_bars']} bars @ {loop['start_sec']:.1f}s "
                    f"(stability: {loop['stability']:.0%})"
                )
            print()

    db.disconnect()


def demo_cross_track_matching():
    """Demo: Find loops with similar characteristics for mashups."""
    db = Database()
    db.connect()

    print("\n🔗 CROSS-TRACK LOOP MATCHING - Mashup Candidate Discovery\n")
    print("="*60)

    # Get all high-stability loops
    all_loops = db.get_all_loops(min_stability=0.85)

    if not all_loops:
        print("❌ No high-stability loops found (run analysis first)")
        db.disconnect()
        return

    print(f"\n✅ Found {len(all_loops)} tracks with high-stability loops (≥85%)\n")

    # Group by loop type
    loop_types = {}
    for track_id, loops in all_loops.items():
        for loop in loops:
            label = loop["label"]
            if label not in loop_types:
                loop_types[label] = []
            loop_types[label].append((track_id, loop))

    for loop_type, loop_list in sorted(loop_types.items()):
        print(f"🎯 {loop_type.upper()}: {len(loop_list)} available")
        for track_id, loop in loop_list[:2]:  # Show first 2
            cursor = db.conn.cursor()
            cursor.execute("SELECT title, artist FROM tracks WHERE id = ?", (track_id,))
            metadata = cursor.fetchone()
            if metadata:
                title, artist = metadata
                print(f"   • {artist} — {title} ({loop['length_bars']} bars)")
        if len(loop_list) > 2:
            print(f"   ... and {len(loop_list)-2} more")
        print()

    db.disconnect()


if __name__ == "__main__":
    print("\n🎵 AutoDJ Multi-Loop Detection Test Suite (Phase 2026-02-11)\n")

    demo_get_loops()
    demo_creative_mixing()
    demo_cross_track_matching()

    print("\n" + "="*60)
    print("✅ All tests complete!")
    print("\nNow run analysis to populate loops_json:")
    print("   python3 src/scripts/analyze_library.py")
