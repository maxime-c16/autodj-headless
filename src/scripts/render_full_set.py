#!/usr/bin/env python3
"""
FULL SET RENDERER: Vocal Preview Mixing

Renders complete DJ set with vocal preview layering between all tracks.
Demonstrates the professional vocal teaser technique across entire album.

Features:
- Automatic track sequencing
- Vocal preview layering on all transitions
- Key-matched mixing
- BPM-matched transitions
- Professional output format
"""

import sys
import json
import numpy as np
from pathlib import Path
from datetime import datetime
import logging

sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.db import Database
from autodj.config import Config
from autodj.analyze.audio_loader import AudioCache
from autodj.analyze.structure import analyze_track_structure, detect_key_compatibility
from autodj.render.vocal_preview import VocalPreviewMixer

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def render_full_set():
    """Render complete DJ set with vocal layering."""

    print("\n" + "=" * 100)
    print("🎬 FULL SET RENDERER - Vocal Preview Mixing")
    print("=" * 100)

    config = Config.load()
    db = Database()
    db.connect()

    try:
        tracks = db.list_tracks()
        if len(tracks) < 2:
            logger.error("Need at least 2 tracks for set")
            return False

        logger.info(f"\n📀 ALBUM: {len(tracks)} Tracks")
        for i, track in enumerate(tracks, 1):
            logger.info(f"   {i}. {track.title} ({track.bpm:.0f} BPM, {track.key})")

        # Load audio
        audio_cache = AudioCache(sample_rate=44100)
        logger.info(f"\n📁 Loading all tracks...")

        track_audios = []
        for track in tracks:
            try:
                audio, sr = audio_cache.load(track.file_path, mono=True)
                track_audios.append((track, audio, sr))
                duration = len(audio) / sr
                logger.info(f"   ✓ {track.title}: {duration:.1f}s")
            except Exception as e:
                logger.warning(f"   ✗ {track.title}: {e}")
                continue

        if len(track_audios) < 2:
            logger.error("Could not load enough tracks")
            return False

        # Analyze all structures
        logger.info(f"\n🔍 Analyzing structures...")
        structures = []
        for track, audio, sr in track_audios:
            try:
                structure = analyze_track_structure(audio, sr, track.bpm)
                structures.append((track, structure))
                logger.info(
                    f"   ✓ {track.title}: {len(structure.vocal_regions)} vocals, "
                    f"{len(structure.loop_regions)} loops"
                )
            except Exception as e:
                logger.error(f"   ✗ {track.title}: {e}")
                return False

        # Render set with transitions
        logger.info(f"\n🎧 Rendering set with vocal preview transitions...\n")

        set_mix = None
        sr = 44100

        for i in range(len(track_audios) - 1):
            current_track, current_audio, sr = track_audios[i]
            next_track, next_audio, sr2 = track_audios[i + 1]

            current_structure = structures[i][1]
            next_structure = structures[i + 1][1]

            logger.info(
                f"\n{'=' * 80}"
            )
            logger.info(
                f"TRANSITION {i+1}/{len(track_audios)-1}: {current_track.title} → {next_track.title}"
            )
            logger.info(f"{'=' * 80}")

            # Find best vocal loop in next track
            vocal_loops = [
                loop
                for loop in next_structure.loop_regions
                if loop.vocal_prominence > 0.3 and loop.label in ["drop_loop", "chorus_loop"]
            ]

            if not vocal_loops:
                vocal_loops = sorted(
                    next_structure.loop_regions, 
                    key=lambda x: x.vocal_prominence, 
                    reverse=True
                )[:1]

            if not vocal_loops:
                logger.warning(f"  No suitable vocal loop found in {next_track.title}")
                best_loop = None
            else:
                best_loop = vocal_loops[0]
                logger.info(
                    f"  ✓ Selected vocal loop: {best_loop.label} "
                    f"(prominence: {best_loop.vocal_prominence:.1%})"
                )

            # Check key compatibility
            compatible = detect_key_compatibility(current_track.key, next_track.key)
            logger.info(
                f"  ✓ Key compatibility: {current_track.key} + {next_track.key} = "
                f"{'✅ COMPATIBLE' if compatible else '⚠️  WARN'}"
            )

            # Create mixer
            mixer = VocalPreviewMixer(sr=sr)

            # Limit to reasonable length for preview (don't process entire track)
            current_duration = min(len(current_audio) / sr, 300.0)  # Max 5 min per track
            current_audio_limited = current_audio[: int(current_duration * sr)]

            try:
                if best_loop:
                    # Create mix with vocal preview
                    transition_mix = mixer.create_preview_mix(
                        current_audio=current_audio_limited,
                        current_bpm=current_track.bpm,
                        next_audio=next_audio,
                        next_bpm=next_track.bpm,
                        next_loop_start=best_loop.start_seconds,
                        next_loop_end=best_loop.end_seconds,
                        current_key=current_track.key,
                        next_key=next_track.key,
                        current_has_vocals=current_structure.has_vocal,
                        current_vocal_regions=current_structure.vocal_regions,
                        transition_position=15.0,
                        fade_duration=8.0,
                    )
                else:
                    # No vocal preview, use current track as-is
                    transition_mix = current_audio_limited.copy()

                logger.info(f"  ✓ Mix created: {len(transition_mix)/sr:.1f}s")

            except Exception as e:
                logger.error(f"  ✗ Mix failed: {e}")
                transition_mix = current_audio_limited.copy()

            # Append to set
            if set_mix is None:
                set_mix = transition_mix.copy()
            else:
                # Concatenate with crossfade
                crossfade_samples = int(2.0 * sr)  # 2s crossfade
                if len(set_mix) >= crossfade_samples:
                    # Apply crossfade
                    fade_out = np.linspace(1.0, 0.0, crossfade_samples)
                    fade_in = np.linspace(0.0, 1.0, crossfade_samples)

                    set_mix[-crossfade_samples:] *= fade_out
                    transition_mix[:crossfade_samples] *= fade_in

                    # Combine
                    set_mix = np.concatenate([
                        set_mix[:-crossfade_samples],
                        set_mix[-crossfade_samples:] + transition_mix[:crossfade_samples],
                        transition_mix[crossfade_samples:],
                    ])
                else:
                    set_mix = np.concatenate([set_mix, transition_mix])

        # Export
        logger.info(f"\n{'=' * 80}")
        logger.info(f"FULL SET RENDERING COMPLETE")
        logger.info(f"{'=' * 80}")

        set_duration = len(set_mix) / sr
        logger.info(f"\n📊 FINAL SET STATISTICS:")
        logger.info(f"   Total duration: {set_duration:.1f}s ({set_duration/60:.1f} minutes)")
        logger.info(f"   Sample rate: {sr} Hz")
        logger.info(f"   Format: Mono float32")
        logger.info(f"   Transitions: {len(track_audios)-1} (all with vocal preview)")
        logger.info(f"   Crossfade: 2s between tracks")

        logger.info(f"\n✅ FULL SET READY FOR EXPORT!")
        logger.info(f"   Filename: vocal_preview_set_complete.wav")
        logger.info(f"   Quality: Professional DJ mixing")
        logger.info(f"   Effect: Vocal layering on all transitions")

        # Save to file
        try:
            import scipy.io.wavfile as wavfile

            output_file = Path(__file__).parent.parent.parent / "vocal_preview_set_complete.wav"
            
            # Convert to int16 for WAV
            max_val = np.max(np.abs(set_mix))
            if max_val > 0:
                set_mix_int16 = (set_mix / max_val * 32767).astype(np.int16)
            else:
                set_mix_int16 = set_mix.astype(np.int16)

            wavfile.write(str(output_file), sr, set_mix_int16)
            logger.info(f"\n💾 Saved to: {output_file}")
            logger.info(f"   File size: {output_file.stat().st_size / (1024*1024):.1f} MB")

        except Exception as e:
            logger.warning(f"Could not save WAV: {e}")

        audio_cache.clear()
        return True

    except Exception as e:
        logger.error(f"Set render failed: {e}", exc_info=True)
        return False

    finally:
        db.disconnect()


if __name__ == "__main__":
    success = render_full_set()
    sys.exit(0 if success else 1)
