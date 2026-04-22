#!/usr/bin/env python3
"""
Rusty Chains Showcase Mix - Aggressive DJ EQ Features

Creates a professional DJ mix using only tracks from Ørgie's "Rusty Chains" album.
Demonstrates the aggressive beat-synced EQ system with multiple DJ techniques per track.

Usage:
    python3 scripts/rusty_chains_showcase.py

Output:
    data/mixes/rusty-chains-showcase-<timestamp>.mp3
"""

import json
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from autodj.config import Config
from autodj.db import Database
from autodj.render.render import render

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def find_rusty_chains_tracks():
    """Find all Rusty Chains tracks in the library."""
    album_dir = Path("/srv/nas/shared/ALAC/ØRGIE/Rusty Chains")
    
    if not album_dir.exists():
        logger.error(f"Album directory not found: {album_dir}")
        return []
    
    tracks = []
    for audio_file in sorted(album_dir.glob("*.m4a")):
        if audio_file.name in ["cover.jpg"]:
            continue
        tracks.append(audio_file)
    
    logger.info(f"Found {len(tracks)} tracks in Rusty Chains")
    for i, track in enumerate(tracks, 1):
        logger.info(f"  {i}. {track.name}")
    
    return tracks


def get_track_metadata(db, track_path):
    """Get metadata for a track from database."""
    try:
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT id, duration_seconds, bpm, key FROM tracks WHERE file_path = ?",
            (str(track_path),)
        )
        result = cursor.fetchone()
        
        if result:
            track_id, duration, bpm, key = result
            return {
                'track_id': track_id,
                'duration_seconds': duration,
                'bpm': bpm or 110.0,
                'key': key or 'unknown',
            }
    except Exception as e:
        logger.warning(f"Could not fetch metadata for {track_path.name}: {e}")
    
    return {
        'track_id': track_path.stem,
        'duration_seconds': 0,
        'bpm': 110.0,
        'key': 'unknown',
    }


def create_transitions_plan(tracks, db):
    """Create transitions plan for showcase mix."""
    logger.info("\n" + "=" * 100)
    logger.info("🎧 CREATING RUSTY CHAINS SHOWCASE MIX")
    logger.info("=" * 100)
    
    transitions = []
    
    for idx, track_path in enumerate(tracks):
        metadata = get_track_metadata(db, track_path)
        
        # Extract title from filename (remove numbering)
        title = track_path.stem
        if '. ' in title:
            title = title.split('. ', 1)[1]
        
        transition = {
            'track_id': metadata['track_id'],
            'file_path': str(track_path),
            'title': title,
            'artist': 'Ørgie',
            'album': 'Rusty Chains',
            'bpm': metadata['bpm'],
            'target_bpm': metadata['bpm'],
            'duration_seconds': metadata['duration_seconds'],
            'key': metadata['key'],
            'cue_in_frames': 0,
            'cue_out_frames': int(metadata['duration_seconds'] * 44100) if metadata['duration_seconds'] > 0 else 0,
            'transition_type': 'bass_swap' if idx < len(tracks) - 1 else 'outro',
            'overlap_bars': 8,
            'hpf_frequency': 200.0,
            'lpf_frequency': 2500.0,
        }
        
        transitions.append(transition)
        logger.info(f"  {idx+1}. {title}")
        logger.info(f"     BPM: {metadata['bpm']:.1f}, Key: {metadata['key']}")
    
    plan = {
        'seed_track_id': tracks[0].stem,
        'timestamp': datetime.utcnow().isoformat(),
        'total_tracks': len(transitions),
        'estimated_duration_minutes': sum(t['duration_seconds'] for t in transitions) / 60,
        'transitions': transitions,
    }
    
    logger.info(f"\nPlaylist Stats:")
    logger.info(f"  Total tracks: {len(transitions)}")
    logger.info(f"  Total duration: {plan['estimated_duration_minutes']:.1f} minutes")
    logger.info(f"  Mix type: Album Showcase (Rusty Chains)")
    
    return plan


def save_transitions_plan(plan):
    """Save transitions plan to file."""
    config = Config.load()
    playlists_dir = Path(config['system']['playlists_path'])
    playlists_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().isoformat().replace(':', '-').split('.')[0]
    plan_file = playlists_dir / f'transitions-rusty-chains-showcase-{timestamp}.json'
    
    with open(plan_file, 'w') as f:
        json.dump(plan, f, indent=2)
    
    logger.info(f"\n✅ Transitions plan saved: {plan_file}")
    return plan_file


def render_showcase_mix(transitions_file, eq_enabled=True):
    """Render the showcase mix with EQ."""
    config = Config.load()
    
    mixes_dir = Path(config['system']['mixes_path'])
    mixes_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().isoformat().replace(':', '-')
    output_format = config['render']['output_format']
    output_path = mixes_dir / f'rusty-chains-showcase-{timestamp}.{output_format}'
    
    logger.info("\n" + "=" * 100)
    logger.info("🎛️ RENDERING SHOWCASE MIX WITH AGGRESSIVE DJ EQ")
    logger.info("=" * 100)
    logger.info(f"Output: {output_path}")
    logger.info(f"EQ Automation: {'ENABLED (aggressive!)' if eq_enabled else 'DISABLED'}")
    logger.info("")
    
    success = render(
        transitions_json_path=str(transitions_file),
        output_path=str(output_path),
        config=config.data,
        eq_enabled=eq_enabled,
    )
    
    if success and output_path.exists():
        file_size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info("\n" + "=" * 100)
        logger.info(f"✅ SHOWCASE MIX COMPLETE!")
        logger.info("=" * 100)
        logger.info(f"File: {output_path.name}")
        logger.info(f"Size: {file_size_mb:.1f} MB")
        logger.info(f"\n🎧 Features demonstrated:")
        logger.info(f"  ✅ Multiple DJ techniques per track (15-20 opportunities)")
        logger.info(f"  ✅ Beat-synced automation (auto-detected BPM)")
        logger.info(f"  ✅ Professional peaking filters (RBJ cookbook)")
        logger.info(f"  ✅ Aggressive skill application (0.65+ confidence)")
        logger.info(f"  ✅ Instant release envelopes (no artifacts)")
        logger.info(f"\n🚀 Ready to showcase!")
        return True
    else:
        logger.error("❌ Rendering failed")
        return False


def main():
    """Main entry point."""
    try:
        # Find tracks
        tracks = find_rusty_chains_tracks()
        if not tracks:
            logger.error("No tracks found in Rusty Chains album")
            return 1
        
        # Initialize database
        config = Config.load()
        db = Database(config['system']['database_path'])
        db.connect()
        
        # Create transitions plan
        plan = create_transitions_plan(tracks, db)
        
        # Save plan
        transitions_file = save_transitions_plan(plan)
        
        # Render with aggressive EQ enabled
        success = render_showcase_mix(transitions_file, eq_enabled=True)
        
        db.disconnect()
        
        return 0 if success else 1
    
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
