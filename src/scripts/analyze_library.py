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
import gc

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
    Get audio file duration in seconds using ffprobe (metadata only, no decode).

    Uses ffprobe instead of aubio to avoid hangs on corrupted audio files.
    This is fast (~100ms) and works even on files with bad frames.

    Args:
        file_path: Path to audio file.

    Returns:
        Duration in seconds, or 0 if unable to determine.
    """
    try:
        import subprocess

        # Use ffprobe to read duration metadata (fast, no audio decode)
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path
            ],
            capture_output=True,
            text=True,
            timeout=5  # 5 second timeout (even slow NAS reads finish in <1s)
        )

        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        else:
            logger.warning(f"ffprobe could not get duration for {Path(file_path).name}")
            return 0.0

    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe timeout for {Path(file_path).name} (likely bad file)")
        return 0.0
    except (ValueError, OSError) as e:
        logger.warning(f"Could not get duration for {Path(file_path).name}: {e}")
        return 0.0
    except Exception as e:
        logger.warning(f"Unexpected error getting duration for {Path(file_path).name}: {e}")
        return 0.0


def _extract_id3_metadata(file_path: str) -> tuple:
    """
    Extract title, artist, album from ID3 tags.

    Args:
        file_path: Path to audio file.

    Returns:
        Tuple (title, artist, album) with fallbacks to None or filename.
    """
    try:
        import mutagen
        from pathlib import Path as PathlibPath

        file_ext = PathlibPath(file_path).suffix.lower()
        title = None
        artist = None
        album = None

        if file_ext in [".m4a", ".mp4", ".aac"]:
            # MP4/M4A tagging
            from mutagen.mp4 import MP4

            try:
                audio = MP4(file_path)
                # MP4 tags: \xa9nam = name, \xa9ART = artist, \xa9alb = album
                title = audio.get("\xa9nam", [None])[0] if "\xa9nam" in audio else None
                artist = audio.get("\xa9ART", [None])[0] if "\xa9ART" in audio else None
                album = audio.get("\xa9alb", [None])[0] if "\xa9alb" in audio else None
            except Exception as e:
                logger.debug(f"Could not read MP4 tags from {file_path}: {e}")

        elif file_ext in [".mp3"]:
            # ID3 tagging for MP3
            from mutagen.easyid3 import EasyID3

            try:
                audio = EasyID3(file_path)
                title = audio.get("title", [None])[0]
                artist = audio.get("artist", [None])[0]
                album = audio.get("album", [None])[0]
            except Exception as e:
                logger.debug(f"Could not read ID3 tags from {file_path}: {e}")

        elif file_ext in [".flac"]:
            # FLAC tagging
            from mutagen.flac import FLAC

            try:
                audio = FLAC(file_path)
                title = audio.get("title", [None])[0] if "title" in audio else None
                artist = audio.get("artist", [None])[0] if "artist" in audio else None
                album = audio.get("album", [None])[0] if "album" in audio else None
            except Exception as e:
                logger.debug(f"Could not read FLAC tags from {file_path}: {e}")

        # Fallback to filename if title not in tags
        if not title:
            title = PathlibPath(file_path).stem

        # Fallback to "Unknown" if artist not in tags
        if not artist:
            artist = "Unknown"

        return title, artist, album

    except Exception as e:
        logger.debug(f"ID3 extraction failed for {file_path}: {e}")
        return PathlibPath(file_path).stem, "Unknown", None


def _write_id3_tags(file_path: str, bpm: float = None, key: str = None) -> None:
    """
    Write BPM and key to tags (ID3 for MP3, MP4 for M4A/ALAC).

    Args:
        file_path: Path to audio file.
        bpm: BPM value (optional).
        key: Key in Camelot notation (optional).
    """
    try:
        import mutagen
        from pathlib import Path as PathlibPath

        file_ext = PathlibPath(file_path).suffix.lower()

        if file_ext in [".m4a", ".mp4", ".aac"]:
            # MP4/M4A tagging
            from mutagen.mp4 import MP4

            try:
                audio = MP4(file_path)
                if bpm:
                    audio["\xa9cmt"] = [f"BPM: {int(bpm)}"]  # MP4 comment field
                if key:
                    audio["\xa9key"] = [key]  # Custom MP4 tag for key
                audio.save()
                logger.debug(f"MP4 tags written for {PathlibPath(file_path).name}")
            except Exception as mp4_err:
                logger.warning(f"Could not write MP4 tags to {file_path}: {mp4_err}")

        elif file_ext in [".mp3"]:
            # ID3 tagging for MP3
            from mutagen.easyid3 import EasyID3

            try:
                audio = EasyID3(file_path)
                if bpm:
                    audio["bpm"] = str(int(bpm))
                if key:
                    audio["key"] = key
                audio.save()
                logger.debug(f"ID3 tags written for {PathlibPath(file_path).name}")
            except Exception as id3_err:
                logger.warning(f"Could not write ID3 tags to {file_path}: {id3_err}")

        elif file_ext in [".flac"]:
            # FLAC tagging
            from mutagen.flac import FLAC

            try:
                audio = FLAC(file_path)
                if bpm:
                    audio["bpm"] = str(int(bpm))
                if key:
                    audio["key"] = key
                audio.save()
                logger.debug(f"FLAC tags written for {PathlibPath(file_path).name}")
            except Exception as flac_err:
                logger.warning(f"Could not write FLAC tags to {file_path}: {flac_err}")

        else:
            logger.debug(f"Unsupported format for tagging: {file_ext}")

    except Exception as e:
        logger.warning(f"Tag writing failed for {file_path}: {e}")


EXCLUDE_DIRS = {"automix", "autodj-output", "mixes"}


def discover_audio_files(library_path: str = "data/music") -> list:
    """
    Discover all audio files in music library.

    Excludes directories matching EXCLUDE_DIRS (e.g. automix/) to avoid
    re-analyzing our own generated DJ mixes.

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
        for f in lib_path.rglob(f"*{audio_format}"):
            if not any(part in EXCLUDE_DIRS for part in f.parts):
                audio_files.append(f)
        for f in lib_path.rglob(f"*{audio_format.upper()}"):
            if not any(part in EXCLUDE_DIRS for part in f.parts):
                audio_files.append(f)

    logger.info(f"Found {len(audio_files)} audio files in {library_path}")
    return sorted(audio_files)


def analyze_track(
    file_path: str, db: Database, config: Config, pipeline=None
) -> tuple:
    """
    Analyze a single track: BPM, key, cues.

    Args:
        file_path: Path to audio file.
        db: Database instance.
        config: Config instance.
        pipeline: Optional shared DJAnalysisPipeline instance (for memory reuse).

    Returns:
        Tuple (success: bool, metadata: TrackMetadata or None)
    """
    logger.info(f"Analyzing: {Path(file_path).name}")

    try:
        # Generate track ID
        track_id = _generate_track_id(str(file_path))

        # Get duration
        duration = _get_audio_duration(str(file_path))
        min_duration = config["constraints"].get("min_track_duration_seconds", 120)
        max_duration = config["constraints"].get("max_track_duration_seconds", 1200)

        if duration < min_duration:
            logger.warning(f"Track too short ({duration:.1f}s), skipping")
            return False, None

        if duration > max_duration:
            logger.warning(f"Track too long ({duration:.1f}s > {max_duration}s), skipping")
            return False, None

        # Detect BPM
        logger.debug("  → Detecting BPM...")
        bpm = detect_bpm(str(file_path), config["analysis"])
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
        cues = detect_cues(str(file_path), bpm, config["analysis"])
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

        # Extract title, artist, album from ID3 tags
        title, artist, album = _extract_id3_metadata(str(file_path))

        # Write ID3 tags (non-fatal - skip if read-only filesystem)
        try:
            _write_id3_tags(str(file_path), bpm, key)
        except Exception as tag_err:
            logger.debug(f"  ID3 tag write skipped (read-only or error): {tag_err}")

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
            title=title,
            artist=artist,
            album=album,
        )

        # Write to database
        db.add_track(metadata)

        # Phase 5: Rich structure analysis (MANDATORY for Pro DJ v2)
        analysis_dict = None
        structure = None
        try:
            from autodj.analyze.structure import analyze_track_structure
            from autodj.analyze.audio_loader import AudioCache
            from dataclasses import asdict

            logger.debug("  → Analyzing structure (sections, loops, cues)...")
            audio_cache = AudioCache(sample_rate=44100)
            audio_data, sr = audio_cache.load(str(file_path), mono=True)
            structure = analyze_track_structure(audio_data, sr, bpm)

            analysis_dict = {
                "sections": [asdict(s) for s in structure.sections],
                "cue_points": [asdict(c) for c in structure.cue_points],
                "loop_regions": [asdict(l) for l in structure.loop_regions],
                "kick_pattern": structure.kick_pattern,
                "downbeat_seconds": structure.downbeat_position,
                "total_bars": structure.total_bars,
                "has_vocal": structure.has_vocal,
            }

            logger.debug(f"  ✓ Structure analysis complete: {len(structure.sections)} sections")

        except Exception as e:
            logger.error(f"  ✗ CRITICAL: Structure analysis failed (required for Pro DJ v2): {type(e).__name__}: {e}", exc_info=True)
            logger.warning(f"  Falling back to basic metadata only (will not have structure data)")

        # Phase 3/4: Spectral/loudness analysis (optional enhancement)
        if analysis_dict:
            try:
                logger.debug("  → Analyzing spectral/loudness (Phase 3/4)...")

                # Reuse pipeline instance to avoid memory overhead (passed from main())
                track_analysis = pipeline.analyze_track(
                    str(file_path), bpm=bpm, camelot_key=key,
                )

                if track_analysis.spectral:
                    analysis_dict["spectral"] = {
                        "bass_energy": track_analysis.spectral.bass_energy,
                        "mid_energy": track_analysis.spectral.mid_energy,
                        "treble_energy": track_analysis.spectral.treble_energy,
                        "kick_detected": track_analysis.spectral.kick_detected,
                        "bassline_present": track_analysis.spectral.bassline_present,
                    }
                if track_analysis.loudness:
                    analysis_dict["loudness"] = track_analysis.loudness.to_dict()

                logger.debug(f"  ✓ Spectral/loudness analysis complete")

                # CRITICAL: Clear audio cache after each track to prevent memory buildup
                pipeline.audio_cache.clear()

            except Exception as e:
                logger.debug(f"  Phase 3/4 pipeline skipped (optional): {type(e).__name__}: {e}")

        # Save analysis to database
        if analysis_dict:
            try:
                db.save_track_analysis(track_id, analysis_dict)

                # Update cue_in/cue_out to use semantic cues (if available)
                if structure:
                    mix_in = next((c for c in structure.cue_points if c.label == "mix_in"), None)
                    mix_out = next((c for c in structure.cue_points if c.label == "mix_out"), None)
                    if mix_in:
                        metadata.cue_in_frames = int(mix_in.position_seconds * 44100)
                    if mix_out:
                        metadata.cue_out_frames = int(mix_out.position_seconds * 44100)
                    if mix_in or mix_out:
                        db.add_track(metadata)

                logger.info(f"  ✅ Structure: {len(structure.sections)} sections, kick={structure.kick_pattern}")
            except Exception as e:
                logger.error(f"  Failed to save structure analysis: {e}", exc_info=True)
            finally:
                # CRITICAL: Always clear structure audio cache, even if save failed
                audio_cache.clear()
        else:
            logger.warning(f"  ⚠️  No structure data saved (structure analysis failed)")
            # Still clear cache even if structure analysis failed
            audio_cache.clear()

        logger.info(f"  ✅ {artist} — {title} | {bpm:.0f} BPM, Key: {key}")
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

        # Filter to only files not yet analyzed
        to_process = [f for f in audio_files if not db.get_track_by_path(str(f))]
        total_to_process = len(to_process)
        logger.info(f"Found {len(audio_files)} files, {total_to_process} pending analysis")

        # Initialize progress
        db.set_analysis_progress(total=total_to_process, processed=0)

        # ========== MEMORY MANAGEMENT ==========
        # Create pipeline ONCE and reuse across all tracks (critical for memory efficiency)
        try:
            from autodj.analyze.pipeline import DJAnalysisPipeline
            from autodj.analyze.dsp_config import DSPConfig
            pipeline = DJAnalysisPipeline(config=DSPConfig())
            logger.debug("✓ Initialized DJAnalysisPipeline (reused across all tracks)")
        except ImportError:
            pipeline = None
            logger.warning("⚠️  DJAnalysisPipeline not available, Phase 3/4 will be skipped")

        # Analyze each track
        processed = 0
        skipped = 0
        errors = 0

        for i, file_path in enumerate(to_process):
            # Re-check if analyzed (race-safe)
            existing = db.get_track_by_path(str(file_path))
            if existing:
                logger.debug(f"Skipping (already analyzed): {Path(file_path).name}")
                skipped += 1
                db.update_analysis_progress(1)
                continue

            # Analyze track (pass pipeline for memory reuse)
            success, metadata = analyze_track(str(file_path), db, config, pipeline=pipeline)
            if success:
                processed += 1
                db.update_analysis_progress(1)
            else:
                errors += 1
                db.update_analysis_progress(1)

            # Aggressive garbage collection every track to prevent memory buildup
            # aubio/essentia/librosa can hold onto memory even after processing completes
            gc.collect()

            # Extra aggressive cleanup every 10 tracks
            if (i + 1) % 10 == 0:
                logger.debug(f"Deep memory cleanup at track {i + 1}/{total_to_process}...")
                gc.collect()
                gc.collect()  # Run GC twice to catch circular references

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

        # Diagnostics: Check Pro DJ v2 readiness
        logger.info("")
        logger.info("=" * 60)
        logger.info("🔍 Pro DJ v2 Readiness Check")
        logger.info("=" * 60)

        try:
            # Query structure analysis coverage (from track_analysis table)
            conn = db.connection
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM track_analysis WHERE sections_json IS NOT NULL")
            with_structure = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM tracks WHERE artist IS NOT NULL AND artist != 'Unknown'")
            with_artist = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM tracks")
            total = c.fetchone()[0]

            structure_pct = (with_structure / total * 100) if total > 0 else 0
            artist_pct = (with_artist / total * 100) if total > 0 else 0

            logger.info(f"  Structure analysis:  {with_structure}/{total} ({structure_pct:.0f}%)")
            logger.info(f"  Artist metadata:     {with_artist}/{total} ({artist_pct:.0f}%)")

            if structure_pct >= 80:
                logger.info(f"  ✅ Ready for Pro DJ v2 (all transition types available)")
            elif structure_pct >= 50:
                logger.info(f"  ⚠️  Partial Pro DJ v2 support ({structure_pct:.0f}% of features available)")
            else:
                logger.warning(f"  ❌ Not ready for Pro DJ v2 (structure analysis <50%)")

        except Exception as diag_err:
            logger.debug(f"Diagnostic query failed: {diag_err}")

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
