#!/usr/bin/env python3
"""
Migration Script: Update existing tracks with newly-detected keys.

This script:
1. Queries the database for all tracks with key='unknown'
2. Re-runs key detection using keyfinder-cli or essentia
3. Updates DB records with the newly detected keys (preserves BPM/cues)
4. Writes tags to audio files

Per SPEC.md § 2.1:
- One file at a time
- Max 30 sec per track for key detection
- Peak memory ≤ 512 MiB
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.config import Config
from autodj.db import Database, TrackMetadata
from autodj.analyze.key import detect_key

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _write_mp4_tags(file_path: str, key: str) -> None:
    """Write key tag to MP4/M4A file."""
    try:
        from mutagen.mp4 import MP4

        audio = MP4(file_path)
        audio["\xa9key"] = [key]
        audio.save()
        logger.debug(f"MP4 key tag written: {Path(file_path).name}")
    except Exception as e:
        logger.warning(f"Could not write MP4 key tag to {file_path}: {e}")


def migrate_unknown_keys(db: Database, config: Config, limit: int = None) -> None:
    """
    Re-detect and update keys for all 'unknown' tracks.

    Args:
        db: Database instance.
        config: Config instance.
        limit: Optional limit on number of tracks to process.
    """
    logger.info("🔑 Starting key migration for 'unknown' tracks...")

    # Query all tracks with key='unknown'
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT id, file_path, bpm, cue_in_frames, cue_out_frames, "
        "       loop_start_frames, loop_length_bars, duration_seconds, "
        "       title, artist, album, analyzed_at "
        "FROM tracks WHERE key='unknown' OR key IS NULL"
    )
    rows = cursor.fetchall()

    if not rows:
        logger.info("✅ No tracks with unknown keys found. Migration complete.")
        return

    total = len(rows)
    if limit:
        rows = rows[:limit]

    logger.info(f"Found {total} tracks with unknown keys. Processing {len(rows)}...")

    updated = 0
    skipped = 0
    failed = 0

    for idx, row in enumerate(rows, 1):
        track_id = row["id"]
        file_path = row["file_path"]
        bpm = row["bpm"]
        duration = row["duration_seconds"]

        logger.info(f"[{idx}/{len(rows)}] Detecting key for {Path(file_path).name}...")

        try:
            # Skip if file no longer exists
            if not Path(file_path).exists():
                logger.warning(f"  ✗ File not found: {file_path}")
                skipped += 1
                continue

            # Detect key
            key = detect_key(file_path, config.data)
            if not key:
                logger.warning(f"  ✗ Key detection failed, keeping 'unknown'")
                skipped += 1
                continue

            # Build updated metadata object
            metadata = TrackMetadata(
                track_id=track_id,
                file_path=file_path,
                duration_seconds=duration,
                bpm=bpm,
                key=key,
                cue_in_frames=row["cue_in_frames"],
                cue_out_frames=row["cue_out_frames"],
                loop_start_frames=row["loop_start_frames"],
                loop_length_bars=row["loop_length_bars"],
                analyzed_at=row["analyzed_at"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
            )

            # Update database
            db.add_track(metadata)
            logger.info(f"  ✅ Updated: {Path(file_path).name} → Key: {key}")

            # Write tag to file if MP4
            if Path(file_path).suffix.lower() in [".m4a", ".mp4", ".aac"]:
                _write_mp4_tags(file_path, key)

            updated += 1

        except Exception as e:
            logger.error(f"  ✗ Migration failed for {file_path}: {e}", exc_info=True)
            failed += 1

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info(f"Migration complete!")
    logger.info(f"  Updated: {updated}")
    logger.info(f"  Skipped: {skipped}")
    logger.info(f"  Failed:  {failed}")
    logger.info(f"  Total:   {updated + skipped + failed}/{total}")
    logger.info("=" * 60)


def main():
    """Main migration entrypoint."""
    try:
        # Load config
        config = Config.load()
        logger.info(f"Config loaded: {config}")

        # Initialize database
        db = Database()
        db.connect()

        # Run migration
        import sys

        limit = None
        if len(sys.argv) > 1:
            try:
                limit = int(sys.argv[1])
                logger.info(f"Processing limit: {limit} tracks")
            except ValueError:
                logger.warning(f"Invalid limit argument: {sys.argv[1]}")

        migrate_unknown_keys(db, config, limit)

        db.disconnect()
        logger.info("✅ Migration script completed successfully.")
        return 0

    except Exception as e:
        logger.error(f"Migration script failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
