#!/usr/bin/env python3
"""
Analyze Music Library Script

Main entrypoint: make analyze

Per SPEC.md § 2.1:
- One file at a time
- Max 30 sec per track
- Peak memory ≤ 512 MiB
- Writes BPM/key to ID3 tags and SQLite
"""

import sys
import logging
from pathlib import Path
from datetime import datetime
import hashlib
import os

# Add src/ to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.config import Config
from autodj.db import Database, TrackMetadata
from autodj.analyze.bpm import detect_bpm
from autodj.analyze.key import detect_key
from autodj.analyze.cues import detect_cues

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Supported audio formats
AUDIO_FORMATS = {".mp3", ".m4a", ".flac", ".wav", ".aif", ".aiff", ".ogg"}


def _generate_track_id(file_path: str) -> str:
    """
    Generate unique track ID from file path and modification time.

    Args:
        file_path: Path to audio file.

    Returns:
        Hex-encoded track ID.
    """
    path_obj = Path(file_path)
    stat = path_obj.stat()
    key_string = f"{file_path}:{stat.st_mtime}:{stat.st_size}"
    return hashlib.sha256(key_string.encode()).hexdigest()[:16]


def _get_audio_duration(file_path: str) -> float:
    """
    Get audio file duration in seconds.

    Args:
        file_path: Path to audio file.

    Returns:
        Duration in seconds, or 0 if unable to determine.
    """
    try:
        import aubio

        source = aubio.source(file_path)
        frames = source.duration
        return frames / source.samplerate
    except Exception as e:
        logger.warning(f"Could not get duration for {file_path}: {e}")
        return 0.0


def _write_id3_tags(file_path: str, bpm: float = None, key: str = None) -> None:
    """
    Write BPM and key to ID3 tags.

    Args:
        file_path: Path to audio file.
        bpm: BPM value (optional).
        key: Key in Camelot notation (optional).
    """
    try:
        import mutagen
        from mutagen.easyid3 import EasyID3

        audio = EasyID3(file_path)

        if bpm:
            audio["bpm"] = str(int(bpm))
        if key:
            audio["key"] = key

        audio.save()
        logger.debug(f"ID3 tags written for {Path(file_path).name}")

    except Exception as e:
        logger.warning(f"Could not write ID3 tags to {file_path}: {e}")


def discover_audio_files(library_path: str = "data/music") -> list:
    """
    Discover all audio files in music library.

    Args:
        library_path: Path to music library directory.

    Returns:
        List of audio file paths.
    """
    lib_path = Path(library_path)

    if not lib_path.exists():
        logger.warning(f"Library path not found: {library_path}")
        return []

    audio_files = []
    for audio_format in AUDIO_FORMATS:
        audio_files.extend(lib_path.rglob(f"*{audio_format}"))
        audio_files.extend(lib_path.rglob(f"*{audio_format.upper()}"))

    logger.info(f"Found {len(audio_files)} audio files in {library_path}")
    return sorted(audio_files)


def analyze_track(
    file_path: str, db: Database, config: Config
) -> tuple:
    """
    Analyze a single track: BPM, key, cues.

    Args:
        file_path: Path to audio file.
        db: Database instance.
        config: Config instance.

    Returns:
        Tuple (success: bool, metadata: TrackMetadata or None)
    """
    logger.info(f"Analyzing: {Path(file_path).name}")

    try:
        # Generate track ID
        track_id = _generate_track_id(str(file_path))

        # Get duration
        duration = _get_audio_duration(str(file_path))
        if duration < config.get("constraints", {}).get("min_track_duration_seconds", 120):
            logger.warning(f"Track too short ({duration:.1f}s), skipping")
            return False, None

        # Detect BPM
        logger.debug("  → Detecting BPM...")
        bpm = detect_bpm(str(file_path), config.get("analysis", {}))
        if not bpm:
            logger.warning("  ✗ BPM detection failed")
            return False, None

        # Detect key
        logger.debug("  → Detecting key...")
        key = detect_key(str(file_path), config.data)
        if not key:
            logger.warning("  ✗ Key detection failed, marking as 'unknown'")
            key = "unknown"

        # Detect cues
        logger.debug("  → Detecting cue points...")
        cues = detect_cues(str(file_path), bpm, config.get("analysis", {}))
        if not cues:
            logger.warning("  ✗ Cue detection failed, using full track")
            cue_in = 0
            cue_out = int(duration * 44100)
            loop_start = None
            loop_length = None
        else:
            cue_in = cues.cue_in
            cue_out = cues.cue_out
            loop_start = cues.loop_start
            loop_length = cues.loop_length

        # Write ID3 tags
        _write_id3_tags(str(file_path), bpm, key)

        # Create metadata object
        metadata = TrackMetadata(
            track_id=track_id,
            file_path=str(file_path),
            duration_seconds=duration,
            bpm=bpm,
            key=key,
            cue_in_frames=cue_in,
            cue_out_frames=cue_out,
            loop_start_frames=loop_start,
            loop_length_bars=loop_length,
            analyzed_at=datetime.now().isoformat(),
            title=Path(file_path).stem,
            artist=None,
            album=None,
        )

        # Write to database
        db.add_track(metadata)

        logger.info(f"  ✅ {bpm:.0f} BPM, Key: {key}")
        return True, metadata

    except Exception as e:
        logger.error(f"Analysis failed for {file_path}: {e}", exc_info=True)
        return False, None


def main():
    """Main analysis entrypoint."""
    try:
        logger.info("🔍 Starting MIR analysis...")

        # Load config
        config = Config.load()
        logger.info(f"Config loaded: {config}")

        # Initialize database
        db = Database()
        db.connect()

        # Discover audio files
        library_path = os.getenv("MUSIC_LIBRARY_PATH", "data/music")
        audio_files = discover_audio_files(library_path)

        if not audio_files:
            logger.warning("No audio files found!")
            db.disconnect()
            return 0

        # Analyze each track
        processed = 0
        skipped = 0
        errors = 0

        for file_path in audio_files:
            # Check if already analyzed
            existing = db.get_track_by_path(str(file_path))
            if existing:
                logger.debug(f"Skipping (already analyzed): {Path(file_path).name}")
                skipped += 1
                continue

            # Analyze track
            success, metadata = analyze_track(str(file_path), db, config)
            if success:
                processed += 1
            else:
                errors += 1

        # Get stats and log summary
        stats = db.get_stats()

        logger.info("")
        logger.info("=" * 60)
        logger.info("📊 Analysis Summary")
        logger.info("=" * 60)
        logger.info(f"  Processed:  {processed}")
        logger.info(f"  Skipped:    {skipped}")
        logger.info(f"  Errors:     {errors}")
        logger.info(f"  Total DB:   {stats['total_tracks']}")
        logger.info(f"  Analyzed:   {stats['analyzed_tracks']}")
        logger.info(f"  With cues:  {stats['tracks_with_cues']}")

        if stats["bpm_stats"]["avg_bpm"]:
            logger.info(
                f"  BPM range:  {stats['bpm_stats']['min_bpm']:.0f} - "
                f"{stats['bpm_stats']['max_bpm']:.0f} (avg: {stats['bpm_stats']['avg_bpm']:.0f})"
            )

        logger.info("=" * 60)
        logger.info("✅ Analysis complete")

        db.disconnect()
        return 0

    except KeyboardInterrupt:
        logger.warning("Analysis interrupted by user")
        return 130
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
