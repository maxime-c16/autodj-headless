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
from autodj.render.loop_extract import (
    create_loop_hold,
    create_loop_roll,
    create_temp_loop_dir,
    cleanup_temp_loops,
)

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
    temp_loop_dir = None
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

        # Check if any transition uses v2 types (loop_hold, drop_swap, etc.)
        transitions = plan.get("transitions", [])
        has_v2_transitions = any(
            t.get("transition_type") in ("loop_hold", "drop_swap", "loop_roll", "eq_blend")
            for t in transitions
        )

        if has_v2_transitions:
            # Pre-extract loop segments for transitions that need them
            temp_loop_dir = _preprocess_loops(plan, config)
            # Generate v2 script with per-transition assembly
            script = _generate_liquidsoap_script_v2(plan, output_path, config, temp_loop_dir)
        else:
            # Legacy: all bass_swap or no transition_type field
            script = _generate_liquidsoap_script_legacy(plan, output_path, config)

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
        _write_mix_metadata(output_path, playlist_id, timestamp, transitions=plan.get("transitions"))

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
        # Cleanup temp loop files
        if temp_loop_dir:
            cleanup_temp_loops(temp_loop_dir)


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
        _write_mix_metadata(output_path, playlist_id, timestamp, transitions=transitions)

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


def _generate_liquidsoap_script_legacy(
    plan: dict, output_path: str, config: dict, m3u_path: str = ""
) -> str:
    """
    Generate Liquidsoap offline mixing script with pro DJ DSP.

    Architecture: sequence([tracks]) + cross(dj_transition) for sequential
    playback with bass-swap crossfades, sub-bass cleanup, and limiting.

    Args:
        plan: Transitions plan dict with transitions list
        output_path: Path to output file
        config: Render config (output format, bitrate, crossfade duration)
        m3u_path: Path to M3U playlist file (optional, for file path reference)

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 320)
    fallback_xfade = config.get("render", {}).get("crossfade_duration_seconds", 4.0)

    transitions = plan.get("transitions", [])

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    # Compute bar-aligned crossfade duration from average BPM
    bpms = [t.get("bpm") for t in transitions if t.get("bpm")]
    if bpms:
        avg_bpm = sum(bpms) / len(bpms)
        xfade_duration = 8 * 4 * 60.0 / avg_bpm  # 8 bars
    else:
        avg_bpm = 0
        xfade_duration = fallback_xfade

    script = []

    # ==================== HEADER ====================
    script.append("# AutoDJ-Headless Pro DJ Mix")
    script.append("# Architecture: sequence() + cross() with bass swap, filter, limiter")
    script.append(f"# Crossfade: {xfade_duration:.1f}s (8 bars at {avg_bpm:.0f} BPM)" if avg_bpm else f"# Crossfade: {xfade_duration:.1f}s (fallback)")
    script.append("")

    # ==================== TRANSITION FUNCTION ====================
    script.append("# === DJ TRANSITION (bass swap + incoming filter) ===")
    script.append(f"def dj_transition(a, b) =")
    script.append(f"  # cross() passes records with .source, .db_level, .metadata")
    script.append(f"  # Outgoing: bass kill via high-pass filter (cut below 200Hz) + fade out")
    script.append(f"  a_cut = filter.iir.butterworth.high(frequency=200.0, order=2, a.source)")
    script.append(f"  a_faded = fade.out(type=\"sin\", duration={xfade_duration:.1f}, a_cut)")
    script.append(f"  # Incoming: start filtered (Butterworth LPF @ 2500Hz) + fade in")
    script.append(f"  b_filtered = filter.iir.butterworth.low(frequency=2500.0, order=2, b.source)")
    script.append(f"  b_faded = fade.in(type=\"sin\", duration={xfade_duration:.1f}, b_filtered)")
    script.append(f"  add(normalize=false, [a_faded, b_faded])")
    script.append("end")
    script.append("")

    # ==================== TRACK DEFINITIONS ====================
    script.append("# === TRACK DEFINITIONS ===")

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
        title = trans.get("title", "")
        artist = trans.get("artist", "")

        # Section-aware timing: use outro_start if available for cue_out
        outro_start = trans.get("outro_start_seconds")
        if outro_start is not None and outro_start > 0:
            cue_out_frames = int(outro_start * 44100)

        # Convert frames to seconds
        cue_in_sec = _frames_to_seconds(cue_in_frames)
        cue_out_sec = _frames_to_seconds(cue_out_frames)

        # Calculate stretch ratio for BPM matching
        stretch_ratio = _calculate_stretch_ratio(native_bpm, target_bpm)

        script.append(f"# Track {idx + 1}: {artist} - {title}" if artist else f"# Track {idx + 1}: {track_id}")
        script.append(f"#   BPM: {native_bpm} -> {target_bpm}, Stretch: {stretch_ratio:.3f}")

        # Build annotate URI with cue points (Liquidsoap 2.1 metadata-based cueing)
        annotations = []
        if cue_in_sec > 0:
            annotations.append(f"liq_cue_in={cue_in_sec:.3f}")
        if cue_out_sec > 0:
            annotations.append(f"liq_cue_out={cue_out_sec:.3f}")

        if annotations:
            annotate_str = ",".join(annotations)
            script.append(f'{track_var} = once(single("annotate:{annotate_str}:{file_path}"))')
            script.append(f"{track_var} = cue_cut({track_var})")
        else:
            script.append(f'{track_var} = once(single("{file_path}"))')

        # Apply time-stretching for BPM matching
        if stretch_ratio != 1.0:
            script.append(f"{track_var} = stretch(ratio={stretch_ratio:.3f}, {track_var})")

        script.append("")

    # ==================== SEQUENCING + CROSSFADE ====================
    if len(track_vars) == 1:
        # Single track — no sequence/cross needed
        script.append("# Single track, no crossfade")
        script.append(f"mixed = {track_vars[0]}")
    else:
        script.append("# === SEQUENTIAL PLAYBACK + CROSSFADE ===")
        track_list = ", ".join(track_vars)
        script.append(f"playlist = sequence([{track_list}])")
        script.append(f"mixed = cross(duration={xfade_duration:.1f}, dj_transition, playlist)")

    script.append("")

    # ==================== MASTER PROCESSING ====================
    script.append("# === MASTER PROCESSING ===")
    script.append("# Sub-bass rumble removal (< 30Hz)")
    script.append("mixed = filter.iir.butterworth.high(frequency=30.0, order=2, mixed)")
    script.append("")
    script.append("# Soft limiter (prevent clipping from overlapping transitions)")
    script.append("mixed = compress(threshold=-1.0, ratio=20.0, attack=0.1, release=50.0, mixed)")
    script.append("")

    # ==================== OUTPUT ====================
    script.append("# === OUTPUT ===")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, clock(sync="none", mixed))'
        )
    elif output_format == "flac":
        script.append(
            f'output.file(%flac, "{output_path}", '
            f'fallible=true, on_stop=shutdown, clock(sync="none", mixed))'
        )
    else:
        logger.warning(f"Unknown output format: {output_format}, defaulting to MP3")
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, clock(sync="none", mixed))'
        )

    script.append("")

    return "\n".join(script)


# Backward-compatible alias for existing tests and callers
_generate_liquidsoap_script = _generate_liquidsoap_script_legacy


def _preprocess_loops(plan: dict, config: dict) -> Optional[str]:
    """
    Pre-extract loop segments for transitions that need them.

    Scans the transition list, identifies which transitions need
    loop segments (loop_hold, loop_roll), and creates WAV files
    in a temp directory.

    Args:
        plan: Transitions plan dict
        config: Render config

    Returns:
        Path to temp directory containing loop files, or None if no loops needed
    """
    transitions = plan.get("transitions", [])
    needs_loops = any(
        t.get("transition_type") in ("loop_hold", "loop_roll")
        for t in transitions
    )

    if not needs_loops:
        return None

    temp_dir = create_temp_loop_dir()
    logger.info(f"Pre-processing loop segments in {temp_dir}")

    for idx, trans in enumerate(transitions):
        tt = trans.get("transition_type", "bass_swap")
        file_path = trans.get("file_path", "")
        bpm = trans.get("bpm") or 128.0

        if tt == "loop_hold":
            loop_start = trans.get("loop_start_seconds", 0.0)
            loop_end = trans.get("loop_end_seconds", 0.0)
            loop_repeats = trans.get("loop_repeats", 2)
            if loop_start >= 0 and loop_end > loop_start:
                output = str(Path(temp_dir) / f"t{idx}_loop.wav")
                success = create_loop_hold(
                    file_path, loop_start, loop_end, loop_repeats, output,
                )
                if success:
                    trans["_loop_wav_path"] = output
                    logger.debug(f"Transition {idx}: loop_hold WAV ready")
                else:
                    logger.warning(f"Transition {idx}: loop_hold extraction failed, falling back to bass_swap")
                    trans["transition_type"] = "bass_swap"

        elif tt == "loop_roll":
            loop_start = trans.get("loop_start_seconds", 0.0)
            roll_stages_json = trans.get("roll_stages")
            if roll_stages_json:
                try:
                    stages = json.loads(roll_stages_json) if isinstance(roll_stages_json, str) else roll_stages_json
                    # Convert lists to tuples
                    stages = [(s[0], s[1]) for s in stages]
                except (json.JSONDecodeError, IndexError, TypeError):
                    stages = [(8, 1), (4, 1), (2, 1), (1, 2)]
            else:
                stages = [(8, 1), (4, 1), (2, 1), (1, 2)]

            output = str(Path(temp_dir) / f"t{idx}_roll.wav")
            success = create_loop_roll(
                file_path, loop_start, bpm, stages, output,
            )
            if success:
                trans["_loop_wav_path"] = output
                logger.debug(f"Transition {idx}: loop_roll WAV ready")
            else:
                logger.warning(f"Transition {idx}: loop_roll extraction failed, falling back to bass_swap")
                trans["transition_type"] = "bass_swap"

    return temp_dir


def _generate_bpm_ramped_incoming(
    in_var: str,
    next_file: str,
    next_bpm: float,
    next_target: float,
    overlap_sec: float,
    in_cue_out: float,
    lpf_freq: float,
    ramp_strategy: str,
    script: list,
    in_cue_in: float = 0.0,
) -> str:
    """
    Generate Liquidsoap code for BPM-ramped incoming track.

    Handles 4 strategies by creating time-segmented sources with different stretch ratios.

    Args:
        in_var: Variable name for incoming track (e.g., "t01_in")
        next_file: Path to incoming audio file
        next_bpm: Native BPM of incoming track
        next_target: Target BPM for incoming track
        overlap_sec: Overlap duration in seconds
        in_cue_out: Cue-out time in seconds
        lpf_freq: LPF cutoff frequency for filtering
        ramp_strategy: "no_ramp", "ramp_linear", "ramp_fast", or "ramp_delayed"
        script: List of script lines to append to
        in_cue_in: Cue-in time in seconds (default 0.0, can be overridden for drop_swap)

    Returns:
        Variable name of the final incoming track (may be different if ramping applied)
    """
    if not next_bpm or next_bpm <= 0:
        next_bpm = 128.0

    next_stretch = _calculate_stretch_ratio(next_bpm, next_target)
    bar_sec = 4 * 60.0 / next_target if next_target > 0 else 1.0

    if ramp_strategy == "no_ramp":
        # Standard: single stretch ratio for entire duration
        script.append(f'# Incoming: no BPM ramp (stay at matched target BPM)')
        script.append(f'{in_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
        script.append(f"{in_var} = cue_cut({in_var})")
        if next_stretch != 1.0:
            script.append(f"{in_var} = stretch(ratio={next_stretch:.3f}, {in_var})")
        script.append(f"{in_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_var})")
        script.append(f"{in_var} = fade.in(type=\"sin\", duration={overlap_sec:.1f}, {in_var})")
        return in_var

    elif ramp_strategy == "ramp_linear":
        # Linear glide from target to native BPM over overlap
        # Split into 2 segments: first half at target, second half at native
        script.append(f'# Incoming: linear BPM ramp (target {next_target:.1f} → native {next_bpm:.1f} over {overlap_sec:.1f}s)')

        half_sec = overlap_sec / 2.0
        native_stretch = 1.0  # Native BPM = stretch ratio 1.0

        # First half: target BPM
        in_1_var = f"{in_var}_seg1"
        mid_cue = in_cue_in + half_sec
        script.append(f'{in_1_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={mid_cue:.3f}:{next_file}"))')
        script.append(f"{in_1_var} = cue_cut({in_1_var})")
        if next_stretch != 1.0:
            script.append(f"{in_1_var} = stretch(ratio={next_stretch:.3f}, {in_1_var})")
        script.append(f"{in_1_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_1_var})")
        script.append(f"{in_1_var} = fade.in(type=\"sin\", duration={half_sec:.1f}, {in_1_var})")

        # Second half: native BPM (smooth glide back)
        in_2_var = f"{in_var}_seg2"
        script.append(f'{in_2_var} = once(single("annotate:liq_cue_in={mid_cue:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
        script.append(f"{in_2_var} = cue_cut({in_2_var})")
        if native_stretch != 1.0:
            script.append(f"{in_2_var} = stretch(ratio={native_stretch:.3f}, {in_2_var})")
        script.append(f"{in_2_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_2_var})")
        script.append(f"{in_2_var} = fade.in(type=\"sin\", duration={half_sec:.1f}, {in_2_var})")

        # Layer segments
        script.append(f"{in_var} = add(normalize=false, [{in_1_var}, {in_2_var}])")
        return in_var

    elif ramp_strategy == "ramp_fast":
        # Aggressive transition in first bar, then settle to native
        script.append(f'# Incoming: fast BPM ramp (first bar aggressive, then settle to native {next_bpm:.1f})')

        fast_sec = min(bar_sec, overlap_sec / 4.0)  # First bar or 1/4 of overlap
        settle_sec = overlap_sec - fast_sec

        # First segment: target BPM (aggressive)
        in_1_var = f"{in_var}_fast"
        fast_cue_out = in_cue_in + fast_sec
        script.append(f'{in_1_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={fast_cue_out:.3f}:{next_file}"))')
        script.append(f"{in_1_var} = cue_cut({in_1_var})")
        if next_stretch != 1.0:
            script.append(f"{in_1_var} = stretch(ratio={next_stretch:.3f}, {in_1_var})")
        script.append(f"{in_1_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_1_var})")
        script.append(f"{in_1_var} = fade.in(type=\"sin\", duration={fast_sec:.1f}, {in_1_var})")

        # Second segment: settle at native BPM
        in_2_var = f"{in_var}_settle"
        script.append(f'{in_2_var} = once(single("annotate:liq_cue_in={fast_cue_out:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
        script.append(f"{in_2_var} = cue_cut({in_2_var})")
        script.append(f"{in_2_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_2_var})")
        script.append(f"{in_2_var} = fade.in(type=\"sin\", duration={settle_sec:.1f}, {in_2_var})")

        # Layer segments
        script.append(f"{in_var} = add(normalize=false, [{in_1_var}, {in_2_var}])")
        return in_var

    elif ramp_strategy == "ramp_delayed":
        # Stay at target BPM during overlap, then transition after
        # For now, implement as: matched during overlap, then fade back hint
        script.append(f'# Incoming: delayed BPM ramp (stay matched during overlap, hint native after)')
        script.append(f'{in_var} = once(single("annotate:liq_cue_in={in_cue_in:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
        script.append(f"{in_var} = cue_cut({in_var})")
        if next_stretch != 1.0:
            script.append(f"{in_var} = stretch(ratio={next_stretch:.3f}, {in_var})")
        script.append(f"{in_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_var})")
        script.append(f"{in_var} = fade.in(type=\"sin\", duration={overlap_sec:.1f}, {in_var})")
        return in_var

    else:
        # Unknown strategy, fallback to no_ramp
        return _generate_bpm_ramped_incoming(
            in_var, next_file, next_bpm, next_target, overlap_sec, in_cue_out, lpf_freq, "no_ramp", script
        )


def _generate_liquidsoap_script_v2(
    plan: dict, output_path: str, config: dict, temp_loop_dir: Optional[str] = None,
) -> str:
    """
    Generate Liquidsoap script with per-transition manual assembly (v2).

    Architecture: sequence([body, transition, body, ...]) with add() layering.
    Each transition gets its own type-specific DSP chain.
    NO cross() — full per-transition control.

    Args:
        plan: Transitions plan dict
        output_path: Path to output file
        config: Render config
        temp_loop_dir: Path to pre-extracted loop WAV files

    Returns:
        Liquidsoap script as string
    """
    output_format = config.get("render", {}).get("output_format", "mp3")
    mp3_bitrate = config.get("render", {}).get("mp3_bitrate", 320)
    transitions = plan.get("transitions", [])

    if not transitions:
        logger.error("No transitions in plan")
        return ""

    script = []
    script.append("# AutoDJ-Headless Pro DJ Mix v2")
    script.append("# Architecture: sequence([body, transition, body, ...]) with per-transition DSP")
    script.append("")

    sequence_parts = []

    for idx, trans in enumerate(transitions):
        file_path = trans.get("file_path", "")
        native_bpm = trans.get("bpm")
        target_bpm = trans.get("target_bpm", native_bpm)
        cue_in_frames = trans.get("cue_in_frames", 0)
        cue_out_frames = trans.get("cue_out_frames")
        title = trans.get("title", "")
        artist = trans.get("artist", "")
        transition_type = trans.get("transition_type", "bass_swap")
        overlap_bars = trans.get("overlap_bars", 8)
        hpf_freq = trans.get("hpf_frequency", 200.0)
        lpf_freq = trans.get("lpf_frequency", 2500.0)
        incoming_start_sec = trans.get("incoming_start_seconds")
        next_track_id = trans.get("next_track_id")

        # Section-aware timing: use outro_start if available for cue_out
        outro_start = trans.get("outro_start_seconds")
        if outro_start is not None and outro_start > 0:
            cue_out_frames = int(outro_start * 44100)

        cue_in_sec = _frames_to_seconds(cue_in_frames)
        cue_out_sec = _frames_to_seconds(cue_out_frames)
        stretch_ratio = _calculate_stretch_ratio(native_bpm, target_bpm)

        effective_bpm = native_bpm if native_bpm and native_bpm > 0 else 128.0
        bar_duration = 4 * 60.0 / effective_bpm
        overlap_sec = overlap_bars * bar_duration

        is_last_track = (next_track_id is None)
        next_trans = transitions[idx + 1] if idx + 1 < len(transitions) else None

        # === TRACK BODY ===
        # Body: from cue_in (or after prev transition's incoming head) to transition start
        body_var = f"body_{idx}"

        # Determine body start: if this track is incoming from a previous transition,
        # start from where the transition head ended
        if idx > 0:
            prev_trans = transitions[idx - 1]
            prev_incoming_start = prev_trans.get("incoming_start_seconds")
            if prev_incoming_start is not None:
                body_cue_in = prev_incoming_start
            else:
                # Fallback: start from overlap_bars into the track
                prev_overlap = prev_trans.get("overlap_bars", 8)
                prev_bpm = prev_trans.get("bpm") or 128.0
                body_cue_in = prev_overlap * 4 * 60.0 / prev_bpm
        else:
            body_cue_in = cue_in_sec

        # Determine body end: where the transition zone starts
        if is_last_track:
            body_cue_out = cue_out_sec
        else:
            if cue_out_sec > overlap_sec:
                body_cue_out = cue_out_sec - overlap_sec
            else:
                body_cue_out = cue_out_sec

        script.append(f"# === TRACK {idx} BODY: {artist} - {title} ===" if artist else f"# === TRACK {idx} BODY ===")
        script.append(f"#   BPM: {native_bpm} -> {target_bpm}, Stretch: {stretch_ratio:.3f}")

        annotations = []
        if body_cue_in > 0:
            annotations.append(f"liq_cue_in={body_cue_in:.3f}")
        if body_cue_out > 0:
            annotations.append(f"liq_cue_out={body_cue_out:.3f}")

        if annotations:
            annotate_str = ",".join(annotations)
            script.append(f'{body_var} = once(single("annotate:{annotate_str}:{file_path}"))')
            script.append(f"{body_var} = cue_cut({body_var})")
        else:
            script.append(f'{body_var} = once(single("{file_path}"))')

        if stretch_ratio != 1.0:
            script.append(f"{body_var} = stretch(ratio={stretch_ratio:.3f}, {body_var})")

        script.append("")
        sequence_parts.append(body_var)

        # === TRANSITION ZONE ===
        if not is_last_track and next_trans:
            next_file = next_trans.get("file_path", "")
            next_bpm = next_trans.get("bpm")
            next_target = next_trans.get("target_bpm", next_bpm)
            next_stretch = _calculate_stretch_ratio(next_bpm, next_target)
            next_drop_sec = trans.get("drop_position_seconds")

            trans_var = f"transition_{idx}_{idx+1}"
            out_var = f"t{idx}{idx+1}_out"
            in_var = f"t{idx}{idx+1}_in"

            script.append(f"# === TRANSITION {idx}->{idx+1}: {transition_type.upper()} ({overlap_bars} bars) ===")

            if transition_type == "loop_hold" and trans.get("_loop_wav_path"):
                # Outgoing: pre-extracted loop WAV
                loop_wav = trans["_loop_wav_path"]
                script.append(f'# Outgoing: pre-extracted loop')
                script.append(f'{out_var} = once(single("{loop_wav}"))')
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = filter.iir.butterworth.high(frequency={hpf_freq:.1f}, order=2, {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={overlap_sec:.1f}, {out_var})")

                # Incoming: with BPM ramping strategy
                in_cue_out = overlap_sec
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, overlap_sec, in_cue_out,
                    lpf_freq, bpm_ramp_strat, script
                )

            elif transition_type == "loop_roll" and trans.get("_loop_wav_path"):
                # Outgoing: pre-extracted roll WAV
                roll_wav = trans["_loop_wav_path"]
                script.append(f'# Outgoing: progressive halving roll')
                script.append(f'{out_var} = once(single("{roll_wav}"))')
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = filter.iir.butterworth.high(frequency={hpf_freq:.1f}, order=2, {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={overlap_sec:.1f}, {out_var})")

                # Incoming: with BPM ramping (last half of overlap for loop_roll)
                in_overlap_sec = overlap_sec / 2.0  # Fade in over last 8 bars of 16
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, in_overlap_sec, in_overlap_sec,
                    lpf_freq, bpm_ramp_strat, script
                )

            elif transition_type == "drop_swap":
                # Short punchy transition: fast fade, no LPF on incoming
                out_start = body_cue_out
                out_end = cue_out_sec

                script.append(f'# Outgoing: fast fade out')
                script.append(f'{out_var} = once(single("annotate:liq_cue_in={out_start:.3f},liq_cue_out={out_end:.3f}:{file_path}"))')
                script.append(f"{out_var} = cue_cut({out_var})")
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={overlap_sec:.1f}, {out_var})")

                # Incoming at drop position: with BPM ramping, but NO LPF (full power)
                drop_sec = next_drop_sec if next_drop_sec else 0.0
                drop_end = drop_sec + overlap_sec
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")

                # For drop_swap with BPM ramping, use no filter (lpf_freq = 20000 means off)
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, overlap_sec, drop_end,
                    20000.0, bpm_ramp_strat, script, in_cue_in=drop_sec
                )

            elif transition_type == "eq_blend":
                # Long gradual blend with frequency sweep over first 1 bar
                # Calculate 1 bar duration (4 beats at target BPM)
                bar_sec = (60.0 / target_bpm) * 4
                bar_sec = min(bar_sec, overlap_sec / 4.0)  # Don't exceed 1/4 of overlap

                out_start = body_cue_out
                out_end = cue_out_sec

                script.append(f'# Outgoing: EQ sweep over first bar, then fade out')

                # Aggressive HPF for first 1 bar (strong bass cut)
                out_bar1_var = f"{out_var}_bar1"
                script.append(f'{out_bar1_var} = once(single("annotate:liq_cue_in={out_start:.3f},liq_cue_out={out_start + bar_sec:.3f}:{file_path}"))')
                script.append(f"{out_bar1_var} = cue_cut({out_bar1_var})")
                if stretch_ratio != 1.0:
                    script.append(f"{out_bar1_var} = stretch(ratio={stretch_ratio:.3f}, {out_bar1_var})")
                script.append(f"{out_bar1_var} = filter.iir.butterworth.high(frequency=200.0, order=2, {out_bar1_var})")
                script.append(f"{out_bar1_var} = fade.out(type=\"sin\", duration={overlap_sec:.1f}, {out_bar1_var})")

                # Subtle HPF for remaining bars (settle into steady state)
                if overlap_sec > bar_sec * 1.5:
                    out_remaining_var = f"{out_var}_remain"
                    script.append(f'{out_remaining_var} = once(single("annotate:liq_cue_in={out_start + bar_sec:.3f},liq_cue_out={out_end:.3f}:{file_path}"))')
                    script.append(f"{out_remaining_var} = cue_cut({out_remaining_var})")
                    if stretch_ratio != 1.0:
                        script.append(f"{out_remaining_var} = stretch(ratio={stretch_ratio:.3f}, {out_remaining_var})")
                    script.append(f"{out_remaining_var} = filter.iir.butterworth.high(frequency={hpf_freq:.1f}, order=2, {out_remaining_var})")
                    script.append(f"{out_remaining_var} = fade.out(type=\"sin\", duration={overlap_sec - bar_sec:.1f}, {out_remaining_var})")
                    script.append(f"{out_var} = add(normalize=false, [{out_bar1_var}, {out_remaining_var}])")
                else:
                    script.append(f"{out_var} = {out_bar1_var}")

                # Incoming: warm LPF for first bar, then open up gradually
                in_cue_out = overlap_sec
                script.append(f'# Incoming: EQ sweep over first bar, then open up')

                # Aggressive LPF for first 1 bar (keep it warm, not bright)
                in_bar1_var = f"{in_var}_bar1"
                script.append(f'{in_bar1_var} = once(single("annotate:liq_cue_in=0.0,liq_cue_out={bar_sec:.3f}:{next_file}"))')
                script.append(f"{in_bar1_var} = cue_cut({in_bar1_var})")
                if next_stretch != 1.0:
                    script.append(f"{in_bar1_var} = stretch(ratio={next_stretch:.3f}, {in_bar1_var})")
                script.append(f"{in_bar1_var} = filter.iir.butterworth.low(frequency=500.0, order=2, {in_bar1_var})")
                script.append(f"{in_bar1_var} = fade.in(type=\"sin\", duration={bar_sec:.1f}, {in_bar1_var})")

                # Open filter for remaining bars (gradually brighten)
                if in_cue_out > bar_sec * 1.5:
                    in_remaining_var = f"{in_var}_remain"
                    script.append(f'{in_remaining_var} = once(single("annotate:liq_cue_in={bar_sec:.3f},liq_cue_out={in_cue_out:.3f}:{next_file}"))')
                    script.append(f"{in_remaining_var} = cue_cut({in_remaining_var})")
                    if next_stretch != 1.0:
                        script.append(f"{in_remaining_var} = stretch(ratio={next_stretch:.3f}, {in_remaining_var})")
                    script.append(f"{in_remaining_var} = filter.iir.butterworth.low(frequency={lpf_freq:.1f}, order=2, {in_remaining_var})")
                    script.append(f"{in_remaining_var} = fade.in(type=\"sin\", duration={in_cue_out - bar_sec:.1f}, {in_remaining_var})")
                    script.append(f"{in_var} = add(normalize=false, [{in_bar1_var}, {in_remaining_var}])")
                else:
                    script.append(f"{in_var} = {in_bar1_var}")

            else:
                # bass_swap (default)
                out_start = body_cue_out
                out_end = cue_out_sec

                script.append(f'# Outgoing: HPF bass kill + fade out')
                script.append(f'{out_var} = once(single("annotate:liq_cue_in={out_start:.3f},liq_cue_out={out_end:.3f}:{file_path}"))')
                script.append(f"{out_var} = cue_cut({out_var})")
                if stretch_ratio != 1.0:
                    script.append(f"{out_var} = stretch(ratio={stretch_ratio:.3f}, {out_var})")
                script.append(f"{out_var} = filter.iir.butterworth.high(frequency={hpf_freq:.1f}, order=2, {out_var})")
                script.append(f"{out_var} = fade.out(type=\"sin\", duration={overlap_sec:.1f}, {out_var})")

                # Incoming: with BPM ramping strategy
                in_cue_out = overlap_sec
                bpm_ramp_strat = trans.get("bpm_ramp_strategy", "no_ramp")
                _generate_bpm_ramped_incoming(
                    in_var, next_file, next_bpm, next_target, overlap_sec, in_cue_out,
                    lpf_freq, bpm_ramp_strat, script
                )

            # Layer outgoing + incoming
            script.append(f"{trans_var} = add(normalize=false, [{out_var}, {in_var}])")
            script.append("")
            sequence_parts.append(trans_var)

    # === ASSEMBLY ===
    script.append("# === ASSEMBLY ===")
    if len(sequence_parts) == 1:
        script.append(f"mixed = {sequence_parts[0]}")
    else:
        parts_str = ", ".join(sequence_parts)
        script.append(f"mixed = sequence([{parts_str}])")
    script.append("")

    # === MASTER PROCESSING ===
    script.append("# === MASTER PROCESSING ===")
    script.append("# Sub-bass rumble removal (< 30Hz)")
    script.append("mixed = filter.iir.butterworth.high(frequency=30.0, order=2, mixed)")
    script.append("")
    script.append("# Soft limiter (prevent clipping from overlapping transitions)")
    script.append("mixed = compress(threshold=-1.0, ratio=20.0, attack=0.1, release=50.0, mixed)")
    script.append("")

    # === OUTPUT ===
    script.append("# === OUTPUT ===")
    if output_format == "mp3":
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, clock(sync="none", mixed))'
        )
    elif output_format == "flac":
        script.append(
            f'output.file(%flac, "{output_path}", '
            f'fallible=true, on_stop=shutdown, clock(sync="none", mixed))'
        )
    else:
        script.append(
            f'output.file(%mp3(bitrate={mp3_bitrate}), "{output_path}", '
            f'fallible=true, on_stop=shutdown, clock(sync="none", mixed))'
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


def _write_mix_metadata(output_path: str, playlist_id: str, timestamp: str, transitions: Optional[list] = None) -> bool:
    """
    Write ID3 metadata to output mix file (SPEC.md § 4.4).

    Args:
        output_path: Path to output file
        playlist_id: Playlist identifier
        timestamp: Generation timestamp (ISO format)
        transitions: Optional list of transition dicts for richer metadata

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

        # Build richer title/artist from transitions metadata
        title = f"AutoDJ Mix {timestamp[:10]}"
        artist = "AutoDJ"
        if transitions:
            # Use seed track (first) artist for title
            seed_artist = transitions[0].get("artist")
            if seed_artist:
                title = f"AutoDJ Mix - {seed_artist} et al."
                artist = "AutoDJ"

        # Handle MP3 files
        if output_path.lower().endswith('.mp3'):
            try:
                # Try to read/create ID3 tags
                try:
                    audio = EasyID3(output_path)
                except Exception as e:
                    # If ID3 header missing, initialize it using mutagen's ID3 class
                    if "doesn't start with an ID3 tag" in str(e):
                        logger.debug(f"Initializing ID3v2 header for {output_path}")
                        from mutagen.id3 import ID3
                        try:
                            # Create empty ID3v2.4 tag
                            audio = ID3()
                            audio.save(output_path, v2_version=4)
                            # Now read it back as EasyID3
                            audio = EasyID3(output_path)
                        except Exception as init_err:
                            logger.warning(f"Failed to initialize ID3 header: {init_err}")
                            return False
                    else:
                        raise

                # Write metadata
                audio['title'] = title
                audio['artist'] = artist
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
                audio['title'] = title
                audio['artist'] = artist
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
        script = _generate_liquidsoap_script_legacy(plan, output_path, self.config, playlist_m3u_path)
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
            _write_mix_metadata(output_path, playlist_id, timestamp, transitions=plan.get("transitions"))

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
