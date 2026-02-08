"""
Loop Segment Pre-processor for Pro DJ Mixing Engine.

Pre-extracts loop segments from source audio files using ffmpeg
BEFORE Liquidsoap rendering. Supports:
- Simple segment extraction (for loop_hold transitions)
- Progressive halving rolls (for loop_roll transitions)
- Temp file management with cleanup

All operations use ffmpeg subprocess calls (already in Docker container).
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


def extract_segment(
    file_path: str,
    start_sec: float,
    duration_sec: float,
    output_path: str,
) -> bool:
    """
    Extract audio segment via ffmpeg.

    Args:
        file_path: Source audio file path
        start_sec: Start time in seconds
        duration_sec: Duration in seconds
        output_path: Output WAV file path

    Returns:
        True if successful
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{duration_sec:.3f}",
        "-i", file_path,
        "-ar", "44100",
        "-ac", "2",
        "-acodec", "pcm_s16le",
        output_path,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg extract failed: {result.stderr[:200]}")
            return False
        if not Path(output_path).exists() or Path(output_path).stat().st_size < 100:
            logger.error(f"ffmpeg produced empty or missing output: {output_path}")
            return False
        logger.debug(f"Extracted segment: {start_sec:.1f}s +{duration_sec:.1f}s -> {output_path}")
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg extract timed out (60s)")
        return False
    except Exception as e:
        logger.error(f"ffmpeg extract error: {e}")
        return False


def create_loop_hold(
    file_path: str,
    loop_start: float,
    loop_end: float,
    repeats: int,
    output_path: str,
) -> bool:
    """
    Create a looped audio segment by extracting and repeating via ffmpeg.

    Extracts a single loop period and repeats it N times using
    ffmpeg's -stream_loop option.

    Args:
        file_path: Source audio file path
        loop_start: Loop region start in seconds
        loop_end: Loop region end in seconds
        repeats: Number of times to repeat the loop (total plays = repeats)
        output_path: Output WAV file path

    Returns:
        True if successful
    """
    loop_duration = loop_end - loop_start
    if loop_duration <= 0:
        logger.error(f"Invalid loop region: {loop_start:.1f}-{loop_end:.1f}")
        return False

    # Step 1: Extract single loop period to temp file
    temp_loop = output_path + ".single.wav"
    try:
        if not extract_segment(file_path, loop_start, loop_duration, temp_loop):
            return False

        # Step 2: Repeat via -stream_loop (loop count = repeats - 1 since
        # ffmpeg plays the file once, then loops N additional times)
        stream_loop_count = repeats - 1
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(stream_loop_count),
            "-i", temp_loop,
            "-ar", "44100",
            "-ac", "2",
            "-acodec", "pcm_s16le",
            output_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg loop repeat failed: {result.stderr[:200]}")
            return False

        logger.debug(
            f"Created loop hold: {loop_start:.1f}-{loop_end:.1f}s x{repeats} -> {output_path}"
        )
        return True

    except Exception as e:
        logger.error(f"Loop hold creation error: {e}")
        return False
    finally:
        # Clean up temp single loop
        try:
            Path(temp_loop).unlink(missing_ok=True)
        except Exception:
            pass


def create_loop_roll(
    file_path: str,
    loop_start: float,
    bpm: float,
    stages: List[Tuple[int, int]],
    output_path: str,
) -> bool:
    """
    Create progressive halving roll from loop region.

    Generates a roll where each stage has a shorter loop segment
    repeated more times, creating a "tightening" effect:
    e.g., [(8, 1), (4, 1), (2, 1), (1, 2)] means:
      - 8-bar segment played 1x
      - 4-bar segment played 1x
      - 2-bar segment played 1x
      - 1-bar segment played 2x

    Args:
        file_path: Source audio file path
        loop_start: Start of the loop region in seconds
        bpm: Track BPM for bar duration calculation
        stages: List of (bars, repeats) tuples
        output_path: Output WAV file path

    Returns:
        True if successful
    """
    if bpm <= 0:
        logger.error(f"Invalid BPM for loop roll: {bpm}")
        return False

    bar_duration = 4 * 60.0 / bpm  # seconds per bar
    temp_dir = Path(output_path).parent
    stage_files = []

    try:
        # Generate each stage as a separate WAV
        for stage_idx, (bars, reps) in enumerate(stages):
            stage_duration = bars * bar_duration
            stage_path = str(temp_dir / f"roll_stage_{stage_idx}.wav")
            stage_files.append(stage_path)

            if reps == 1:
                # Simple extraction
                if not extract_segment(file_path, loop_start, stage_duration, stage_path):
                    return False
            else:
                # Extract + repeat
                if not create_loop_hold(
                    file_path, loop_start, loop_start + stage_duration,
                    reps, stage_path,
                ):
                    return False

        # Concatenate all stages using ffmpeg concat demuxer
        concat_file = str(temp_dir / "roll_concat.txt")
        with open(concat_file, "w") as f:
            for sf in stage_files:
                escaped = sf.replace("'", "\\'")
                f.write(f"file '{escaped}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-ar", "44100",
            "-ac", "2",
            "-acodec", "pcm_s16le",
            output_path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg roll concat failed: {result.stderr[:200]}")
            return False

        logger.debug(f"Created loop roll: {len(stages)} stages -> {output_path}")
        return True

    except Exception as e:
        logger.error(f"Loop roll creation error: {e}")
        return False
    finally:
        # Clean up stage files and concat file
        for sf in stage_files:
            try:
                Path(sf).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            Path(concat_file).unlink(missing_ok=True)
        except Exception:
            pass


def create_temp_loop_dir() -> str:
    """
    Create a temporary directory for loop files.

    Returns:
        Path to temp directory
    """
    temp_dir = tempfile.mkdtemp(prefix="autodj_loops_")
    logger.debug(f"Created temp loop directory: {temp_dir}")
    return temp_dir


def cleanup_temp_loops(temp_dir: str) -> None:
    """
    Remove temporary loop files after rendering.

    Args:
        temp_dir: Path to temporary directory to remove
    """
    import shutil
    try:
        if temp_dir and Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.debug(f"Cleaned up temp loop directory: {temp_dir}")
    except Exception as e:
        logger.warning(f"Failed to clean up temp loops: {e}")
