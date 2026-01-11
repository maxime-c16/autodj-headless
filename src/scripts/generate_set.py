#!/usr/bin/env python3
"""
Generate DJ Playlist and Transition Plan Script

Main entrypoint: make generate

Per SPEC.md § 2.2:
- Max 30 sec total runtime
- Peak memory ≤ 512 MiB
- Outputs: playlist.m3u and transitions.json

USAGE MODES:

1. Default (random seed):
   make generate

2. Use specific seed track (by file path):
   SEED_TRACK_PATH=/music/path/to/track.mp3 make generate

3. Use specific seed track (by track ID):
   SEED_TRACK_ID=abc123def456 make generate

Example commands:
   # Generate with seed track by path
   docker-compose -f docker/compose.dev.yml exec -T autodj \\
     python -m src.scripts.generate_set -e SEED_TRACK_PATH="/music/House/Build.mp3"

   # Generate with seed track ID
   docker-compose -f docker/compose.dev.yml exec -T autodj \\
     python -m src.scripts.generate_set -e SEED_TRACK_ID="abc123"
"""

import sys
import os
import logging
import json
from pathlib import Path
from datetime import datetime

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.config import Config
from autodj.db import Database
from autodj.generate.playlist import generate

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Main generation entrypoint."""
    db = None
    try:
        logger.info("🎵 Starting playlist generation...")

        # Load config
        config = Config.load()
        logger.debug(f"Config loaded successfully")

        # Connect to database
        db_path = config["system"]["database_path"]
        db = Database(db_path)
        db.connect()
        logger.info(f"Connected to database: {db_path}")

        # Load all analyzed tracks
        all_tracks = db.list_tracks()
        logger.info(f"📚 Loaded {len(all_tracks)} analyzed tracks")

        if not all_tracks:
            logger.error("No analyzed tracks in database. Run 'make analyze' first.")
            return 1

        # Convert tracks to library format
        library = []
        for track in all_tracks:
            library.append(
                {
                    "id": track.track_id,
                    "file_path": track.file_path,
                    "duration_seconds": track.duration_seconds,
                    "bpm": track.bpm,
                    "key": track.key or "unknown",
                    "cue_in_frames": track.cue_in_frames,
                    "cue_out_frames": track.cue_out_frames,
                    "title": track.title,
                    "artist": track.artist,
                }
            )

        logger.debug(f"Library format: {len(library)} tracks prepared")

        # Prepare output directory
        output_dir = Path(config["system"]["playlists_path"])
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get generation parameters from config
        target_duration = config["mix"]["target_duration_minutes"]

        # Support for specifying tracks via environment variables or config
        seed_track_path = config["mix"].get("seed_track_path", "")
        seed_track_id = None

        # Check environment variables for quick override
        env_seed_path = os.environ.get("SEED_TRACK_PATH", "")
        env_seed_id = os.environ.get("SEED_TRACK_ID", "")
        env_explicit_ids = os.environ.get("EXPLICIT_TRACK_IDS", "")  # Comma-separated
        env_explicit_path = os.environ.get("EXPLICIT_PLAYLIST_PATH", "")

        # Priority: environment variables > config
        if env_seed_path:
            seed_track_path = env_seed_path
        if env_seed_id:
            seed_track_id = env_seed_id
            logger.info(f"Using seed track ID from env: {seed_track_id}")

        # Find seed track ID if path provided
        if seed_track_path and not seed_track_id:
            for track in library:
                if track["file_path"] == seed_track_path:
                    seed_track_id = track["id"]
                    logger.info(f"Using seed track: {seed_track_path}")
                    break
            if not seed_track_id:
                logger.warning(f"Seed track not found: {seed_track_path}, will use random")

        # Generate playlist
        logger.info(
            f"Generating {target_duration}-minute playlist with BPM tolerance "
            f"{config['constraints']['bpm_tolerance_percent']}%"
        )

        result = generate(
            library=library,
            config=config.data,  # Pass underlying dict, not Config object
            output_dir=str(output_dir),
            target_duration_minutes=target_duration,
            seed_track_id=seed_track_id,
            database=db,
        )

        if not result:
            logger.error("Playlist generation failed")
            return 1

        m3u_path, transitions_path = result

        # Load and log summary
        with open(transitions_path) as f:
            plan = json.load(f)

        num_tracks = len(plan["transitions"])
        playlist_id = plan.get("playlist_id", "unknown")
        mix_duration_sec = plan.get("mix_duration_seconds", 0)
        mix_duration_min = mix_duration_sec // 60

        # Calculate BPM distribution
        track_bpms = [t.get("target_bpm") for t in plan["transitions"] if t.get("target_bpm")]
        avg_bpm = sum(track_bpms) / len(track_bpms) if track_bpms else 0

        logger.info(f"✅ Playlist generated: {m3u_path}")
        logger.info(f"✅ Transitions generated: {transitions_path}")
        logger.info(f"📊 SUMMARY:")
        logger.info(f"   Tracks: {num_tracks}")
        logger.info(f"   Duration: {mix_duration_min}:{int(mix_duration_sec % 60):02d}")
        logger.info(f"   Avg BPM: {avg_bpm:.1f}")
        logger.info(f"   Playlist ID: {playlist_id}")

        return 0

    except KeyboardInterrupt:
        logger.warning("Generation interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Generation failed: {e}", exc_info=True)
        return 1
    finally:
        # Cleanup database connection
        if db:
            try:
                db.disconnect()
                logger.debug("Database disconnected")
            except Exception as e:
                logger.warning(f"Failed to disconnect database: {e}")


if __name__ == "__main__":
    sys.exit(main())
