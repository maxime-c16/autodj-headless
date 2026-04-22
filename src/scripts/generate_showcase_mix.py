#!/usr/bin/env python3
"""
SHOWCASE MIX: Loop Layering & Advanced Techniques
=================================================

Demonstrates new features using "Enough Blood - EP" album:
1. Drop Loop Layering (multi-track mashup)
2. Loop Progression (energy building)
3. Loop Swapping (quick transitions)
4. Breakdown Bridging (smooth transitions)
5. Loop Filtering (creative effects)

Target: Showcase all new loop features + detect audio artifacts

Author: AutoDJ Showcase Generator
Date: 2026-02-12
"""

import sys
import json
from pathlib import Path
from datetime import datetime
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.db import Database
from autodj.config import Config

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def create_showcase_mix():
    """Create a showcase mix using the Enough Blood EP album."""
    
    logger.info("🎛️ Creating Showcase Mix: New Loop Features")
    logger.info("=" * 80)
    
    # Connect to database
    config = Config.load()
    db = Database(config["system"]["database_path"])
    db.connect()
    
    # Load all tracks from analysis
    all_tracks = db.list_tracks()
    logger.info(f"📊 Loaded {len(all_tracks)} tracks from database")
    
    if not all_tracks:
        logger.error("❌ No tracks analyzed! Run 'make analyze' first.")
        return False
    
    # Parse tracks with loops
    tracks_with_loops = []
    for track in all_tracks:
        if track.loops_json:
            try:
                loops = json.loads(track.loops_json)
                tracks_with_loops.append({
                    'track': track,
                    'loops': loops,
                    'bpm': track.bpm,
                    'title': track.title,
                    'artist': track.artist,
                })
            except:
                pass
    
    logger.info(f"📍 Found {len(tracks_with_loops)} tracks with loops detected")
    
    if not tracks_with_loops:
        logger.error("❌ No tracks with loops! Analysis may have failed.")
        return False
    
    # Create showcase mix structure
    mix = {
        'title': 'SHOWCASE: Loop Features Demo',
        'date': datetime.now().isoformat(),
        'duration_minutes': 0,
        'features_showcased': [],
        'sections': []
    }
    
    logger.info("\n🎯 MIX STRUCTURE:")
    logger.info("=" * 80)
    
    # FEATURE 1: Drop Loop Layering (Mashup)
    logger.info("\n1️⃣ DROP LOOP LAYERING - Multi-track mashup")
    logger.info("-" * 80)
    
    # Select tracks with high-stability drop loops
    drop_loop_tracks = []
    for t in tracks_with_loops:
        for loop in t['loops']:
            if loop['label'] == 'drop_loop' and loop['stability'] >= 0.8:
                drop_loop_tracks.append({
                    'track': t['track'],
                    'loop': loop,
                    'bpm': t['bpm'],
                    'title': t['title']
                })
    
    drop_loop_tracks.sort(key=lambda x: x['loop']['stability'], reverse=True)
    
    if len(drop_loop_tracks) >= 2:
        section1 = {
            'name': 'Drop Loop Layer Mashup',
            'technique': 'Drop Loop Layering',
            'duration_bars': 32,
            'tracks': []
        }
        
        # Layer top 2 drop loops
        for i, tl in enumerate(drop_loop_tracks[:2]):
            logger.info(f"   Track {i+1}: {tl['title']}")
            logger.info(f"      Loop: {tl['loop']['label']} @ {tl['loop']['start_sec']:.2f}s")
            logger.info(f"      Stability: {tl['loop']['stability']:.2f} ✅")
            logger.info(f"      Length: {tl['loop']['length_bars']} bars")
            
            section1['tracks'].append({
                'track_id': tl['track'].track_id,
                'title': tl['title'],
                'loop_start': tl['loop']['start_sec'],
                'loop_end': tl['loop']['end_sec'],
                'length_bars': tl['loop']['length_bars'],
                'stability': tl['loop']['stability']
            })
        
        mix['sections'].append(section1)
        mix['features_showcased'].append('Drop Loop Layering')
        mix['duration_minutes'] += 2.0  # 32 bars at ~157 BPM = ~2 min
    
    # FEATURE 2: Loop Progression (Energy Building)
    logger.info("\n2️⃣ LOOP PROGRESSION - Energy building with different loops")
    logger.info("-" * 80)
    
    # Find tracks with varied loop types
    section2 = {
        'name': 'Progressive Loop Build',
        'technique': 'Loop Progression',
        'duration_bars': 40,
        'progression': []
    }
    
    for t in tracks_with_loops[:1]:  # Use first track
        breakdown = [l for l in t['loops'] if l['label'] == 'breakdown_loop']
        drop = [l for l in t['loops'] if l['label'] == 'drop_loop']
        
        if breakdown and drop:
            logger.info(f"   Track: {t['title']}")
            
            # Step 1: Breakdown (low energy)
            if breakdown:
                logger.info(f"   Step 1: Breakdown Loop (energy build start)")
                logger.info(f"      @ {breakdown[0]['start_sec']:.2f}s, {breakdown[0]['length_bars']} bars")
                section2['progression'].append({
                    'step': 1,
                    'loop_type': 'breakdown_loop',
                    'duration_bars': breakdown[0]['length_bars'],
                    'energy_level': 'low-to-mid'
                })
            
            # Step 2: Drop (high energy)
            if drop:
                logger.info(f"   Step 2: Drop Loop (energy peak)")
                logger.info(f"      @ {drop[0]['start_sec']:.2f}s, {drop[0]['length_bars']} bars")
                section2['progression'].append({
                    'step': 2,
                    'loop_type': 'drop_loop',
                    'duration_bars': drop[0]['length_bars'],
                    'energy_level': 'high'
                })
    
    mix['sections'].append(section2)
    mix['features_showcased'].append('Loop Progression')
    mix['duration_minutes'] += 2.5
    
    # FEATURE 3: Loop Swapping (Quick Transitions)
    logger.info("\n3️⃣ LOOP SWAPPING - Quick transitions between sections")
    logger.info("-" * 80)
    
    section3 = {
        'name': 'Rapid Loop Swaps',
        'technique': 'Loop Swapping',
        'duration_bars': 48,
        'swaps': []
    }
    
    swap_count = 0
    for t in tracks_with_loops[:2]:
        for loop in t['loops'][:3]:  # First 3 loops
            section3['swaps'].append({
                'track': t['title'],
                'loop_type': loop['label'],
                'duration_bars': loop['length_bars'],
                'entry_point': f"Bar {round(loop['start_sec'] / (4*60/t['bpm']))}"
            })
            swap_count += 1
            
            if swap_count <= 4:
                logger.info(f"   Swap {swap_count}: {loop['label']} ({loop['length_bars']} bars)")
    
    mix['sections'].append(section3)
    mix['features_showcased'].append('Loop Swapping')
    mix['duration_minutes'] += 3.0
    
    # FEATURE 4: Breakdown Bridging
    logger.info("\n4️⃣ BREAKDOWN BRIDGING - Smooth transitions")
    logger.info("-" * 80)
    
    breakdown_loops = []
    for t in tracks_with_loops:
        for loop in t['loops']:
            if loop['label'] == 'breakdown_loop':
                breakdown_loops.append({
                    'track': t['title'],
                    'loop': loop,
                    'stability': loop['stability']
                })
    
    if breakdown_loops:
        section4 = {
            'name': 'Breakdown Bridge Transitions',
            'technique': 'Breakdown Bridging',
            'duration_bars': 32,
            'bridges': []
        }
        
        for i, bl in enumerate(breakdown_loops[:3]):
            logger.info(f"   Bridge {i+1}: {bl['track']} @ {bl['loop']['start_sec']:.2f}s")
            logger.info(f"      Stability: {bl['stability']:.2f}")
            
            section4['bridges'].append({
                'track': bl['track'],
                'duration_bars': bl['loop']['length_bars'],
                'stability': bl['stability']
            })
        
        mix['sections'].append(section4)
        mix['features_showcased'].append('Breakdown Bridging')
        mix['duration_minutes'] += 2.0
    
    # FEATURE 5: Loop Filtering (Creative Effects)
    logger.info("\n5️⃣ LOOP FILTERING - Creative effects & transitions")
    logger.info("-" * 80)
    
    section5 = {
        'name': 'Filtered Loop Effects',
        'technique': 'Loop Filtering',
        'duration_bars': 32,
        'effects': []
    }
    
    # HPF sweep: Filter in from highs
    section5['effects'].append({
        'name': 'HPF Sweep Filter-In',
        'description': 'High-pass filter sweep from 0-5kHz',
        'duration_bars': 8,
        'starting_frequency': '0 Hz',
        'ending_frequency': '5000 Hz'
    })
    logger.info(f"   Effect 1: HPF Sweep Filter-In (8 bars)")
    
    # Loop hold: Layer two loops
    section5['effects'].append({
        'name': 'Loop Hold',
        'description': 'Hold outgoing loop, bring in incoming',
        'duration_bars': 8
    })
    logger.info(f"   Effect 2: Loop Hold (8 bars)")
    
    # LPF sweep: Filter out to lows
    section5['effects'].append({
        'name': 'LPF Sweep Filter-Out',
        'description': 'Low-pass filter sweep from 20kHz to 200Hz',
        'duration_bars': 8,
        'starting_frequency': '20000 Hz',
        'ending_frequency': '200 Hz'
    })
    logger.info(f"   Effect 3: LPF Sweep Filter-Out (8 bars)")
    
    mix['sections'].append(section5)
    mix['features_showcased'].append('Loop Filtering')
    mix['duration_minutes'] += 2.0
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("🎯 MIX SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total Duration: {mix['duration_minutes']:.1f} minutes")
    logger.info(f"Total Sections: {len(mix['sections'])}")
    logger.info(f"Features Showcased: {', '.join(mix['features_showcased'])}")
    
    # Save mix plan
    output_path = Path('/app/showcase_mix.json')
    with open(output_path, 'w') as f:
        json.dump(mix, f, indent=2)
    
    logger.info(f"\n✅ Showcase mix plan saved: {output_path}")
    
    logger.info("\n" + "=" * 80)
    logger.info("🎧 NEXT STEPS:")
    logger.info("=" * 80)
    logger.info("1. Export showcase mix to audio file")
    logger.info("2. Listen for audio artifacts/glitches")
    logger.info("3. Check filter smoothness (HPF/LPF sweeps)")
    logger.info("4. Verify loop alignment and timing")
    logger.info("5. Validate new feature output quality")
    
    db.disconnect()
    return True


if __name__ == "__main__":
    success = create_showcase_mix()
    sys.exit(0 if success else 1)
