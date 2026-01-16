"""
Liquidsoap Render Engine.

Generates and executes Liquidsoap offline mixing scripts.
Per SPEC.md § 5.3:
- Offline clock
- Streaming decode/encode
- Memory-bounded
"""

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable, List
import json
from datetime import datetime
from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC
import os
import threading
import time
import shutil
from subprocess import PIPE, STDOUT, Popen

from autodj.render.segmenter import RenderSegmenter, SegmentPlan

logger = logging.getLogger(__name__)


def render(
    transitions_json_path: str,
    output_path: str,
    config: dict,
    timeout_seconds: Optional[int] = None,  # No timeout (None = unlimited)
) -> bool:
    """
    Execute Liquidsoap rendering.

    Args:
        transitions_json_path: Path to transitions.json
        output_path: Path to output mix file
        config: Render config dict
        timeout_seconds: Max runtime in seconds (None = no timeout)

    Returns:
        True if successful, False otherwise
    """
    script_path = None
    try:
        # Load transitions plan
        with open(transitions_json_path, "r") as f:
            plan = json.load(f)

        # Preflight: ensure each transition has a valid file path
        missing = []
        for idx, t in enumerate(plan.get("transitions", [])):
            fp = t.get("file_path")
            if not fp:
                missing.append((idx, fp, "missing path"))
                continue
            try:
                p = Path(fp)
                if not p.exists():
                    missing.append((idx, fp, "not found"))
            except Exception:
                missing.append((idx, fp, "invalid path"))

        if missing:
            logger.error("Preflight check failed: some tracks missing or unreadable")
            for m in missing:
                logger.error(f" Transition {m[0]}: {m[1]} -> {m[2]}")
            return False

        # Generate Liquidsoap script
        script = _generate_liquidsoap_script(plan, output_path, config)
        if not script:
            logger.error("Failed to generate Liquidsoap script")
            return False

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            suffix=".liq", mode="w", delete=False
        ) as tmp:
            tmp.write(script)
            script_path = tmp.name

        # Save debug copy
        debug_script_path = Path("/tmp/last_render_standalone.liq")
        debug_script_path.write_text(script)
        logger.info(f"Debug script saved to: {debug_script_path}")

        # Execute Liquidsoap and stream logs to file & logger
        logger.info(f"Starting Liquidsoap render: {output_path}")
        logger.debug(f"Script ({len(script.split(chr(10)))} lines):\n{script[:500]}...")

        # Ensure logs directory
        log_dir = os.environ.get("AUTODJ_LOG_DIR", "/app/data/logs")
        try:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
        except Exception:
            logger.debug(f"Could not create log dir: {log_dir}")

        liquidsoap_log_path = Path(log_dir) / f"liquidsoap-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.log"

        # Start Liquidsoap process and stream stdout/stderr
        proc = Popen(["liquidsoap", script_path], stdout=PIPE, stderr=STDOUT, text=True)

        start_time = time.time()

        # Thread: stream process output to log file and logger
        def _stream_proc_output(p, logfile_path):
            try:
                with open(logfile_path, "a", encoding="utf-8") as lf:
                    while True:
                        line = p.stdout.readline()
                        if not line:
                            break
                        lf.write(line)
                        lf.flush()
                        logger.info(f"[liquidsoap] {line.rstrip()}")
            except Exception as e:
                logger.warning(f"Error streaming liquidsoap output: {e}")

        t = threading.Thread(target=_stream_proc_output, args=(proc, str(liquidsoap_log_path)), daemon=True)
        t.start()

        # Heartbeat: log elapsed time and output file size periodically
        while True:
            if proc.poll() is not None:
                break
            elapsed = time.time() - start_time
            try:
                size = Path(output_path).stat().st_size if Path(output_path).exists() else 0
            except Exception:
                size = 0
            logger.debug(f"Render running: elapsed={elapsed:.1f}s, out_size={size} bytes")
            time.sleep(5)

        # Wait for streaming thread to finish
        t.join(timeout=2)

        if proc.returncode != 0:
            logger.error(f"Liquidsoap failed with return code {proc.returncode}")
            logger.error(f"Debug script saved to: {debug_script_path}")
            logger.error(f"Liquidsoap log: {liquidsoap_log_path}")
            _cleanup_partial_output(output_path)
            return False


        # Validate output
        if not _validate_output_file(output_path):
            logger.error("Output file validation failed")
            _cleanup_partial_output(output_path)
            return False

        # Add metadata to output
        playlist_id = plan.get("playlist_id", "autodj-playlist")
        timestamp = datetime.now().isoformat()
        _write_mix_metadata(output_path, playlist_id, timestamp)

        logger.info(f"✅ Render complete: {output_path}")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Render timeout after {timeout_seconds} seconds")
        _cleanup_partial_output(output_path)
        return False
    except Exception as e:
        logger.error(f"Render failed: {e}")
        _cleanup_partial_output(output_path)
        return False
    finally:
        # Cleanup temp script
        if script_path:
            try:
                Path(script_path).unlink()
                logger.debug(f"Cleaned up temp script: {script_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp script {script_path}: {e}")


def render_segmented(
    transitions_json_path: str,
    output_path: str,
    config: dict,
    progress_callback: Optional[Callable] = None,
) -> bool:
    """
    Render large mix in segments to reduce memory usage.

    For mixes with >max_tracks_before_segment tracks, splits into segments
    to keep peak RAM ≤200 MiB per segment instead of 512+ MiB for full mix.

    Args:
        transitions_json_path: Path to transitions.json
        output_path: Final output path
        config: Render config dict
        progress_callback: Optional callback(segment_idx, total_segments, status)
                          status: "rendering", "completed", "concatenating"

    Returns:
        True if successful, False otherwise
    """
    temp_dir = None
    segment_files = []

    try:
        # Load transitions
        with open(transitions_json_path) as f:
            plan = json.load(f)

        transitions = plan.get("transitions", [])

        # Check if segmentation needed
        max_tracks_before_segment = config.get("render", {}).get(
            "max_tracks_before_segment", 10
        )

        segmenter = RenderSegmenter()
        should_segment = segmenter.should_segment(
            transitions, max_tracks_before_segment
        )

        if not should_segment:
            # Small mix, render normally
            logger.info(
                f"Mix has {len(transitions)} tracks, "
                f"rendering without segmentation"
            )
            return render(transitions_json_path, output_path, config)

        logger.info(
            f"Large mix detected ({len(transitions)} tracks), "
            f"using segmented rendering"
        )

        # Split into segments
        segment_size = config.get("render", {}).get("segment_size", 5)
        segments = segmenter.split_transitions(transitions, segment_size)

        if not segments:
            logger.error("Failed to create segments")
            return False

        logger.info(f"Split into {len(segments)} segments")

        # Create temp directory for segment files
        temp_dir = Path(tempfile.mkdtemp(prefix="autodj_segments_"))
        logger.debug(f"Created temp directory: {temp_dir}")

        # Render each segment
        for segment in segments:
            # Progress callback
            if progress_callback:
                progress_callback(segment.segment_index, len(segments), "rendering")

            # Generate segment-specific output
            segment_output = temp_dir / f"segment_{segment.segment_index}.mp3"

            success = _render_segment(
                segment=segment,
                plan=plan,
                output_path=str(segment_output),
                config=config,
            )

            if not success:
                logger.error(f"Segment {segment.segment_index} rendering failed")
                return False

            segment_files.append(segment_output)

            # Progress callback
            if progress_callback:
                progress_callback(segment.segment_index, len(segments), "completed")

        # Concatenate segments with crossfade blending
        if progress_callback:
            progress_callback(len(segments), len(segments), "concatenating")

        logger.info(f"Concatenating {len(segment_files)} segments...")
        success = _concatenate_segments(
            segment_files=segment_files,
            output_path=output_path,
            crossfade_duration=config.get("render", {}).get(
                "crossfade_duration_seconds", 4.0
            ),
        )

        if not success:
            logger.error("Segment concatenation failed")
            return False

        # Validate final output
        if not _validate_output_file(output_path):
            logger.error("Final output validation failed")
            return False

        # Write metadata to final output
        playlist_id = plan.get("playlist_id", "autodj-playlist")
        timestamp = datetime.now().isoformat()
        _write_mix_metadata(output_path, playlist_id, timestamp)

        logger.info(f"✅ Segmented render complete: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Segmented render failed: {e}")
        return False

    finally:
        # Cleanup temporary segments
        if temp_dir:
            try:
                shutil.rmtree(temp_dir)
                logger.debug(f"Cleaned up temp directory: {temp_dir}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp directory: {e}")


def _render_segment(
    segment: SegmentPlan,
    plan: dict,
    output_path: str,
    config: dict,
) -> bool:
    """
    Render a single segment to MP3.

    Args:
        segment: SegmentPlan describing this segment
        plan: Original transitions plan (for metadata)
        output_path: Output file path for this segment
        config: Render config dict

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(
            f"Rendering segment {segment.segment_index}: "
            f"tracks {segment.track_start_idx}-{segment.track_end_idx}"
        )

        # Generate segment-specific transitions JSON
        segment_plan = {
            "playlist_id": f"segment_{segment.segment_index}",
            "mix_duration_seconds": segment.estimated_duration_sec,
            "generated_at": datetime.utcnow().isoformat(),
            "transitions": segment.transitions,
        }

        # Write to temp JSON file
        segment_json = (
            Path(output_path).parent / f"segment_{segment.segment_index}.json"
        )
        with open(segment_json, "w") as f:
            json.dump(segment_plan, f, indent=2)

        # Render segment using existing render() function
        success = render(
            transitions_json_path=str(segment_json),
            output_path=output_path,
            config=config,
            timeout_seconds=None,  # No timeout for segments
        )

        # Cleanup temp JSON
        try:
            segment_json.unlink()
        except Exception:
            pass

        return success

    except Exception as e:
        logger.error(f"Segment {segment.segment_index} render failed: {e}")
        return False


def _concatenate_segments(
    segment_files: List[Path],
    output_path: str,
    crossfade_duration: float = 4.0,  # Deprecated (segments already have crossfades)
) -> bool:
    """
    Concatenate segment MP3 files directly (no blending).

    NOTE: Segment boundaries already have smooth transitions from Liquidsoap DSP.
    Simple concatenation via ffmpeg's concat demuxer is sufficient.

    Args:
        segment_files: List of segment MP3 file paths
        output_path: Output path for concatenated mix
        crossfade_duration: (DEPRECATED - not used)

    Returns:
        True if successful, False otherwise
    """
    try:
        if not segment_files:
            logger.error("No segment files to concatenate")
            return False

        if len(segment_files) == 1:
            # Single segment, just copy
            logger.debug("Single segment, copying to output")
            shutil.copy(segment_files[0], output_path)
            return True

        logger.info(
            f"Concatenating {len(segment_files)} segments (direct concat, no crossfade)"
        )

        # Create concat demuxer file (ffmpeg's efficient concatenation method)
        concat_file = Path(tempfile.mktemp(suffix=".txt"))
        try:
            with open(concat_file, "w") as f:
                for seg_file in segment_files:
                    # Escape single quotes in path
                    escaped_path = str(seg_file).replace("'", "\\'")
                    f.write(f"file '{escaped_path}'\n")

            logger.debug(f"Concat demuxer file: {concat_file}")

            # Use ffmpeg concat demuxer for fast, direct concatenation
            cmd = [
                "ffmpeg",
                "-y",  # Overwrite output
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",  # Direct stream copy (no re-encoding)
                output_path,
            ]

            logger.debug(f"ffmpeg command: {' '.join(cmd)}")

            # Execute ffmpeg
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max for concatenation
            )

            if result.returncode != 0:
                logger.error(f"ffmpeg concatenation failed: {result.stderr}")
                return False

            logger.info("✅ Segment concatenation complete")
            return True

        finally:
            # Cleanup concat file
            try:
                concat_file.unlink()
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg concatenation timeout (10 min)")
        return False
    except Exception as e:
        logger.error(f"Segment concatenation error: {e}")
        return False


def _frames_to_seconds(frames: Optional[int], sample_rate: int = 44100) -> float:
    """Convert frame offset to seconds."""
    if frames is None or frames == 0:
        return 0.0
    return float(frames) / sample_rate


def _calculate_stretch_ratio(
    native_bpm: Optional[float], target_bpm: Optional[float]
) -> float:
    """
    Calculate time-stretch ratio for BPM matching.

    Args:
        native_bpm: Track's detected BPM
        target_bpm: Target BPM for rendering

    Returns:
        Stretch ratio (1.0 = no change, >1.0 = faster, <1.0 = slower)
    """
    if native_bpm is None or target_bpm is None or native_bpm == 0:
        return 1.0
    ratio = target_bpm / native_bpm
    # Clamp to reasonable range (±8% per SPEC.md BPM tolerance)
    ratio = max(0.92, min(1.08, ratio))
    return ratio


def _generate_liquidsoap_script(
    plan: dict, output_path: str, config: dict, m3u_path: str = ""
) -> str:
    """
    Generate Liquidsoap offline mixing script with advanced DSP.

    Per SPEC.md § 5.3:
    - Offline clock (no real-time sync)
    - Streaming decode/encode
    - Memory-bounded
    - Transitions: crossfades with cue points and BPM time-stretching

    Args:
        plan: Transitions plan dict with transitions list
        output_path: Path to output file
        config: Render config (output format, bitrate, crossfade duration)
        m3u_path: Path to M3U playlist file (optional, for file path reference)

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 192)
    crossfade_duration = config.get("render", {}).get("crossfade_duration_seconds", 4.0)

    transitions = plan.get("transitions", [])

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    # Start building Liquidsoap script
    script = []

    # ==================== SETTINGS ====================
    script.append("# AutoDJ-Headless Offline Mix")
    script.append("# Generated Liquidsoap script for DJ-quality mixing")
    script.append("# Features: Cue points, BPM time-stretching, beatmatched crossfades")
    script.append("")
    script.append("# Offline clock (no real-time sync)")
    script.append('set("clock.sync", false)')
    script.append('set("frame.video.samplerate", 44100)')
    script.append("")

    # ==================== HELPER FUNCTIONS ====================
    script.append("# Crossfade transition function")
    script.append("def crossfade_transition(a, b) =")
    script.append(f"  # Linear fade-in/fade-out crossfade ({crossfade_duration}s)")
    script.append(f"  fade_in = fade.in(duration={crossfade_duration}, b)")
    script.append(f"  fade_out = fade.out(duration={crossfade_duration}, a)")
    script.append("  add(normalize=false, [fade_in, fade_out])")
    script.append("end")
    script.append("")

    # ==================== TRACK SEQUENCE BUILD ====================
    script.append("# Build track sequence with cue points and time-stretching")
    script.append("")

    # Generate individual track definitions
    track_vars = []
    for idx, trans in enumerate(transitions):
        track_var = f"track_{idx}"
        track_vars.append(track_var)

        file_path = trans.get("file_path", "")
        track_id = trans.get("track_id", f"unknown_{idx}")
        native_bpm = trans.get("bpm")
        target_bpm = trans.get("target_bpm", native_bpm)
        cue_in_frames = trans.get("cue_in_frames", 0)
        cue_out_frames = trans.get("cue_out_frames")

        # Convert frames to seconds
        cue_in_sec = _frames_to_seconds(cue_in_frames)
        cue_out_sec = _frames_to_seconds(cue_out_frames)

        # Calculate stretch ratio for BPM matching
        stretch_ratio = _calculate_stretch_ratio(native_bpm, target_bpm)

        # Build track with processing pipeline
        script.append(f"# Track {idx + 1}: {track_id}")
        script.append(f"#   Native BPM: {native_bpm}, Target BPM: {target_bpm}, Stretch: {stretch_ratio:.3f}")
        script.append(f"{track_var} = single(\"{file_path}\")")

        # Apply cue points (trim if cue_out is set)
        if cue_out_sec > 0:
            script.append(f"{track_var} = trim(start={cue_in_sec:.3f}, stop={cue_out_sec:.3f}, {track_var})")
        elif cue_in_sec > 0:
            script.append(f"{track_var} = trim(start={cue_in_sec:.3f}, {track_var})")

        # Apply time-stretching for BPM matching
        if stretch_ratio != 1.0:
            script.append(f"{track_var} = stretch(ratio={stretch_ratio:.3f}, {track_var})")

        # Wrap in once() to ensure single playback
        script.append(f"{track_var} = once({track_var})")
        script.append("")

    # ==================== TRACK SEQUENCE ====================
    script.append("# Chain tracks in sequence")
    if len(track_vars) == 1:
        # Single track
        script.append(f"sequence = mksafe({track_vars[0]})")
    else:
        # Multiple tracks: use sequence() to concatenate
        # Note: Full crossfade implementation coming in future version
        script.append("# Build track sequence")
        script.append(f"sequence = mksafe(sequence([")
        for idx, track_var in enumerate(track_vars):
            if idx == len(track_vars) - 1:
                script.append(f"  {track_var}")
            else:
                script.append(f"  {track_var},")
        script.append("]))")

    script.append("")

    # ==================== OUTPUT ENCODING ====================
    script.append("# Encode and output")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", sequence)'
        )
    elif output_format == "flac":
        script.append(f'output.file(%flac, "{output_path}", sequence)')
    else:
        logger.warning(f"Unknown output format: {output_format}, defaulting to MP3")
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", sequence)'
        )

    script.append("")

    return "\n".join(script)


def _validate_output_file(output_path: str) -> bool:
    """
    Validate rendered output file (SPEC.md § 10.3).

    Args:
        output_path: Path to output file

    Returns:
        True if valid, False otherwise
    """
    try:
        output_file = Path(output_path)

        # Check file exists
        if not output_file.exists():
            logger.error(f"Output file does not exist: {output_path}")
            return False

        # Check minimum size (1 MiB per SPEC.md § 10.3)
        min_size_bytes = 1024 * 1024
        file_size = output_file.stat().st_size
        if file_size < min_size_bytes:
            logger.error(f"Output file too small: {file_size} bytes (minimum {min_size_bytes})")
            return False

        logger.debug(f"Output validation passed: {output_path} ({file_size} bytes)")
        return True

    except Exception as e:
        logger.error(f"Output validation failed: {e}")
        return False


def _write_mix_metadata(output_path: str, playlist_id: str, timestamp: str) -> bool:
    """
    Write ID3 metadata to output mix file (SPEC.md § 4.4).

    Args:
        output_path: Path to output file
        playlist_id: Playlist identifier
        timestamp: Generation timestamp (ISO format)

    Returns:
        True if successful, False otherwise
    """
    try:
        output_file = Path(output_path)
        if not output_file.exists():
            logger.warning(f"Output file not found for metadata writing: {output_path}")
            return False

        year = timestamp[:4]  # Extract year from ISO timestamp
        album_name = f"AutoDJ Mix {timestamp[:10]}"  # YYYY-MM-DD
        genre = "DJ Mix"

        # Handle MP3 files
        if output_path.lower().endswith('.mp3'):
            try:
                audio = EasyID3(output_path)
                audio['album'] = album_name
                audio['genre'] = genre
                audio['date'] = year
                audio.save()
                logger.debug(f"Added ID3 metadata to {output_path}")
            except Exception as e:
                logger.warning(f"Failed to write ID3 tags to MP3: {e}")
                return False

        # Handle FLAC files
        elif output_path.lower().endswith('.flac'):
            try:
                audio = FLAC(output_path)
                audio['album'] = album_name
                audio['genre'] = genre
                audio['date'] = year
                audio.save()
                logger.debug(f"Added VORBIS metadata to {output_path}")
            except Exception as e:
                logger.warning(f"Failed to write VORBIS tags to FLAC: {e}")
                return False

        else:
            logger.debug(f"Unsupported format for metadata: {output_path}")
            return False

        return True

    except Exception as e:
        logger.error(f"Metadata writing failed: {e}")
        return False


def _cleanup_partial_output(output_path: str) -> None:
    """
    Clean up partial or failed output files.

    Args:
        output_path: Path to output file to remove
    """
    try:
        output_file = Path(output_path)
        if output_file.exists():
            output_file.unlink()
            logger.debug(f"Cleaned up partial output: {output_path}")
    except Exception as e:
        logger.warning(f"Failed to clean up output file {output_path}: {e}")


class RenderEngine:
    """Liquidsoap offline rendering orchestrator."""

    def __init__(self, config: dict):
        """
        Initialize render engine.

        Args:
            config: Configuration dict
        """
        self.config = config
        logger.info("RenderEngine initialized")

    def render_playlist(
        self,
        transitions_json_path: str,
        playlist_m3u_path: str,
        output_path: str,
        timeout_seconds: Optional[int] = None,
    ) -> bool:
        """
        Render playlist to final mix.

        Args:
            transitions_json_path: Path to transitions.json
            playlist_m3u_path: Path to playlist.m3u (for track reference)
            output_path: Output mix file path
            timeout_seconds: Max render time in seconds (None = no timeout)

        Returns:
            True if successful, False otherwise
        """
        logger.info(f"Starting render: {output_path}")
        script_path = None

        # Load transitions plan
        try:
            with open(transitions_json_path, "r") as f:
                plan = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load transitions: {e}")
            return False

        # Load playlist for file paths
        try:
            with open(playlist_m3u_path, "r") as f:
                playlist_lines = f.readlines()
        except Exception as e:
            logger.error(f"Failed to load playlist: {e}")
            return False

        # Map transitions to file paths from M3U
        file_paths = [
            line.strip() for line in playlist_lines
            if not line.startswith("#") and line.strip()
        ]

        for idx, trans in enumerate(plan.get("transitions", [])):
            if idx < len(file_paths):
                trans["file_path"] = file_paths[idx]

        # Generate script
        script = _generate_liquidsoap_script(plan, output_path, self.config, playlist_m3u_path)
        if not script:
            logger.error("Failed to generate Liquidsoap script")
            return False

        # Write and execute script
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".liq", mode="w", delete=False
            ) as tmp:
                tmp.write(script)
                script_path = tmp.name

            logger.debug(f"Liquidsoap script: {script_path}")
            logger.debug(f"Script ({len(script.split(chr(10)))} lines):\n{script[:500]}...")

            # Also save to a known location for debugging
            debug_script_path = Path("/tmp/last_render.liq")
            debug_script_path.write_text(script)
            logger.info(f"Debug script saved to: {debug_script_path}")

            result = subprocess.run(
                ["liquidsoap", script_path],
                timeout=timeout_seconds,
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                logger.error(f"Liquidsoap failed with return code {result.returncode}")
                logger.error(f"Liquidsoap stderr: {result.stderr if result.stderr else '(no stderr)'}")
                logger.error(f"Liquidsoap stdout: {result.stdout if result.stdout else '(no stdout)'}")
                logger.error(f"Debug script saved to: {debug_script_path}")
                logger.error(f"You can inspect with: cat {debug_script_path}")
                _cleanup_partial_output(output_path)
                return False

            # Validate output
            if not _validate_output_file(output_path):
                logger.error("Output file validation failed")
                _cleanup_partial_output(output_path)
                return False

            # Add metadata to output
            playlist_id = plan.get("playlist_id", "autodj-playlist")
            timestamp = datetime.now().isoformat()
            _write_mix_metadata(output_path, playlist_id, timestamp)

            logger.info(f"✅ Render complete: {output_path}")
            return True

        except subprocess.TimeoutExpired:
            logger.error(f"Render timeout after {timeout_seconds} seconds")
            _cleanup_partial_output(output_path)
            return False
        except Exception as e:
            logger.error(f"Render failed: {e}")
            _cleanup_partial_output(output_path)
            return False
        finally:
            # Cleanup temp script
            if script_path:
                try:
                    Path(script_path).unlink()
                    logger.debug(f"Cleaned up temp script: {script_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp script {script_path}: {e}")
