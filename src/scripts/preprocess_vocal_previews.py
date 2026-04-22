#!/usr/bin/env python3
"""
Vocal Preview Preprocessor

Pre-processes transitions.json to add vocal preview mixing layers.
Runs BEFORE Liquidsoap rendering to enhance each track with vocal previews
from the next track during non-vocal sections.

Per design: Detects vocal regions in current track, finds best vocal loop
from next track, creates professional mixing blend, saves as intermediate WAV,
and references in transitions.json.

Usage:
    python preprocess_vocal_previews.py transitions.json output_dir
"""

import sys
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import numpy as np

# Add src/ to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.db import Database
from autodj.config import Config
from autodj.analyze.audio_loader import AudioCache
from autodj.analyze.structure import (
    analyze_track_structure,
    detect_key_compatibility,
)
from autodj.render.vocal_preview import VocalPreviewMixer

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def preprocess_vocal_previews(
    transitions_json_path: str,
    output_dir: str,
    config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Pre-process transitions.json to add vocal preview mixing.

    For each track in the playlist, detects vocal regions, finds the best
    vocal loop from the next track, creates a professional mixing blend,
    and saves as intermediate WAV. Updates transitions.json with paths.

    Args:
        transitions_json_path: Path to transitions.json from playlist generation
        output_dir: Directory to save intermediate vocal preview WAVs
        config: Optional config dict (loads from file if not provided)

    Returns:
        True if successful, False otherwise
    """
    try:
        # Load config
        if config is None:
            config = Config.load()

        # Load transitions
        logger.info(f"Loading transitions from {transitions_json_path}")
        with open(transitions_json_path, "r") as f:
            plan = json.load(f)

        transitions = plan.get("transitions", [])
        if len(transitions) < 2:
            logger.warning("Less than 2 tracks, skipping vocal preview preprocessing")
            return True

        # Create output directory
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Connect to database
        db = Database()
        db.connect()

        try:
            # Audio cache for loading tracks
            audio_cache = AudioCache(sample_rate=44100)
            sr = 44100

            # Load all track audios and structures
            logger.info(f"Loading {len(transitions)} tracks...")
            track_data = []

            for idx, trans in enumerate(transitions):
                file_path = trans.get("file_path")
                track_id = trans.get("track_id")

                if not file_path:
                    logger.warning(f"Transition {idx}: No file_path, skipping")
                    track_data.append(None)
                    continue

                try:
                    # Load audio
                    audio, _ = audio_cache.load(file_path, mono=True, sr=sr)

                    # Get or analyze structure
                    try:
                        analysis = db.get_track_analysis(track_id)
                        if not analysis:
                            logger.info(f"  Analyzing {Path(file_path).name}...")
                            native_bpm = trans.get("bpm", 128.0)
                            structure = analyze_track_structure(audio, sr, native_bpm)
                        else:
                            # Reconstruct structure from analysis
                            from autodj.analyze.structure import TrackStructure
                            structure = TrackStructure(
                                sections=analysis.get("sections", []),
                                loop_regions=analysis.get("loop_regions", []),
                                vocal_regions=analysis.get("vocal_regions", []),
                                has_vocal=analysis.get("has_vocal", False),
                            )
                    except Exception as e:
                        logger.warning(f"  Could not get analysis for track {idx}: {e}")
                        structure = None

                    track_data.append({
                        "audio": audio,
                        "structure": structure,
                        "file_path": file_path,
                        "bpm": trans.get("bpm", 128.0),
                        "key": trans.get("key", "unknown"),
                    })

                    logger.info(f"  ✓ Track {idx}: {len(audio)/sr:.1f}s")

                except Exception as e:
                    logger.error(f"Could not load track {idx}: {e}")
                    track_data.append(None)

            # Process transitions: for each track, create vocal preview with next track
            logger.info(f"\nGenerating vocal preview mixing...")
            mixer = VocalPreviewMixer(sr=sr)

            for idx in range(len(transitions) - 1):
                current_trans = transitions[idx]
                next_trans = transitions[idx + 1]

                current_data = track_data[idx]
                next_data = track_data[idx + 1]

                # Skip if either track couldn't be loaded
                if current_data is None or next_data is None:
                    logger.warning(f"Transition {idx}→{idx+1}: Skipping (missing audio)")
                    continue

                current_audio = current_data["audio"]
                current_structure = current_data["structure"]
                current_bpm = current_data["bpm"]
                current_key = current_data["key"]

                next_audio = next_data["audio"]
                next_structure = next_data["structure"]
                next_bpm = next_data["bpm"]
                next_key = next_data["key"]

                # Check if current track has non-vocal sections
                if current_structure is None or not current_structure.vocal_regions:
                    logger.debug(f"Transition {idx}→{idx+1}: No vocal regions detected, skipping")
                    continue

                # Find best vocal loop in next track
                if next_structure is None or not next_structure.loop_regions:
                    logger.debug(f"Transition {idx}→{idx+1}: No loops in next track, skipping")
                    continue

                # Select loops with good vocal prominence
                vocal_loops = [
                    loop for loop in next_structure.loop_regions
                    if loop.vocal_prominence > 0.3 and loop.label in ["drop_loop", "chorus_loop", "breakdown_loop"]
                ]

                if not vocal_loops:
                    # Fallback: use highest prominence loop
                    vocal_loops = sorted(
                        next_structure.loop_regions,
                        key=lambda x: x.vocal_prominence,
                        reverse=True
                    )[:1]

                if not vocal_loops:
                    logger.debug(f"Transition {idx}→{idx+1}: No suitable vocal loop, skipping")
                    continue

                best_loop = vocal_loops[0]

                # Check key compatibility
                compatible = detect_key_compatibility(current_key, next_key)
                if not compatible:
                    logger.warning(f"Transition {idx}→{idx+1}: Keys incompatible ({current_key} vs {next_key}), skipping")
                    continue

                try:
                    logger.info(f"Transition {idx}→{idx+1}: Creating vocal preview...")
                    logger.info(f"  Current: {current_trans.get('title', 'Unknown')} ({current_bpm:.0f} BPM, {current_key})")
                    logger.info(f"  Next: {next_trans.get('title', 'Unknown')} ({next_bpm:.0f} BPM, {next_key})")
                    logger.info(f"  Vocal loop: {best_loop.label} ({best_loop.vocal_prominence:.1%} vocal)")

                    # Limit audio length for preprocessing (no point mixing beyond 5 minutes)
                    max_duration = min(len(current_audio) / sr, 300.0)
                    current_audio_limited = current_audio[: int(max_duration * sr)]

                    # Create vocal preview mix
                    preview_mix = mixer.create_preview_mix(
                        current_audio=current_audio_limited,
                        current_bpm=current_bpm,
                        next_audio=next_audio,
                        next_bpm=next_bpm,
                        next_loop_start=best_loop.start_seconds,
                        next_loop_end=best_loop.end_seconds,
                        current_key=current_key,
                        next_key=next_key,
                        current_has_vocals=current_structure.has_vocal,
                        current_vocal_regions=current_structure.vocal_regions,
                        transition_position=15.0,  # 15s before end
                        fade_duration=8.0,  # 8s fade-in
                    )

                    # Save as intermediate WAV
                    output_wav = output_path / f"vocal_preview_{idx}_{idx+1}.wav"

                    import scipy.io.wavfile as wavfile

                    # Convert to int16 for WAV
                    max_val = np.max(np.abs(preview_mix))
                    if max_val > 0:
                        preview_mix_int16 = (preview_mix / max_val * 32767).astype(np.int16)
                    else:
                        preview_mix_int16 = preview_mix.astype(np.int16)

                    wavfile.write(str(output_wav), sr, preview_mix_int16)

                    # Add vocal_preview_wav path to transition
                    current_trans["vocal_preview_wav"] = str(output_wav)
                    current_trans["vocal_preview_enabled"] = True
                    current_trans["vocal_preview_loop"] = best_loop.label
                    current_trans["vocal_preview_prominence"] = round(best_loop.vocal_prominence, 3)

                    logger.info(f"  ✓ Vocal preview saved: {output_wav.name}")

                except Exception as e:
                    logger.error(f"Failed to create vocal preview for transition {idx}→{idx+1}: {e}")
                    current_trans["vocal_preview_enabled"] = False
                    continue

            # Save enhanced transitions.json
            logger.info(f"\nSaving enhanced transitions to {transitions_json_path}...")
            with open(transitions_json_path, "w") as f:
                json.dump(plan, f, indent=2)

            logger.info(f"✅ Vocal preview preprocessing complete!")
            return True

        finally:
            db.disconnect()
            audio_cache.clear()

    except Exception as e:
        logger.error(f"Vocal preview preprocessing failed: {e}", exc_info=True)
        return False


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: preprocess_vocal_previews.py transitions.json [output_dir]")
        print("")
        print("Arguments:")
        print("  transitions.json  Path to transitions.json from playlist generation")
        print("  output_dir        Directory for intermediate WAV files (default: ./vocal_previews)")
        return 1

    transitions_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "./vocal_previews"

    success = preprocess_vocal_previews(transitions_path, output_dir)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
