#!/usr/bin/env python3
"""
SHOWCASE: Vocal Preview Layering Technique

Demonstrates the complete vocal preview mixing workflow:
1. Detect vocal regions in tracks (Phase 1)
2. Tag loops with vocal prominence (Phase 2)  
3. Check key compatibility (Phase 3)
4. Layer vocal previews (Phase 4)

Using "Enough Blood - EP" test album.
"""

import sys
import json
from pathlib import Path
from dataclasses import asdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.db import Database
from autodj.config import Config
from autodj.analyze.audio_loader import AudioCache
from autodj.analyze.structure import (
    analyze_track_structure,
    detect_key_compatibility,
)
from autodj.render.vocal_preview import VocalPreviewMixer
import logging

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def showcase_vocal_preview():
    """Create showcase mix with vocal preview layering."""

    print("=" * 90)
    print("SHOWCASE: Vocal Preview Layering Technique")
    print("Phases 1-4 Implementation Demo")
    print("=" * 90)

    # Connect to database
    db = Database()
    db.connect()

    try:
        # Load all tracks
        tracks = db.list_tracks()
        if len(tracks) < 2:
            logger.error("Need at least 2 tracks for showcase")
            return False

        logger.info(f"✓ Loaded {len(tracks)} tracks from database\n")

        # Audio cache
        audio_cache = AudioCache(sample_rate=44100)

        # Showcase: Layer track 2 vocal preview into track 1
        track1 = tracks[0]
        track2 = tracks[1]

        logger.info(f"1️⃣ CURRENT TRACK: {track1.title} by {track1.artist}")
        logger.info(f"   BPM: {track1.bpm:.1f}, Key: {track1.key}")
        logger.info(f"2️⃣ NEXT TRACK: {track2.title} by {track2.artist}")
        logger.info(f"   BPM: {track2.bpm:.1f}, Key: {track2.key}\n")

        # Load audio
        logger.info("📁 Loading audio files...")
        try:
            audio1, sr1 = audio_cache.load(track1.file_path, mono=True)
            audio2, sr2 = audio_cache.load(track2.file_path, mono=True)
            logger.info(f"   ✓ Track 1: {len(audio1)/sr1:.1f}s")
            logger.info(f"   ✓ Track 2: {len(audio2)/sr2:.1f}s\n")
        except FileNotFoundError:
            logger.error("Audio files not found")
            return False

        # Analyze structures (Phase 1-2)
        logger.info("🔍 PHASE 1-2: Analyze vocal regions and loop prominence...")
        structure1 = analyze_track_structure(audio1, sr1, track1.bpm)
        structure2 = analyze_track_structure(audio2, sr2, track2.bpm)

        logger.info(f"   Track 1: {len(structure1.vocal_regions)} vocal regions")
        for i, (start, end) in enumerate(structure1.vocal_regions[:2], 1):
            logger.info(f"      Region {i}: {start:.1f}s - {end:.1f}s")

        logger.info(f"   Track 2: {len(structure2.vocal_regions)} vocal regions")
        for i, (start, end) in enumerate(structure2.vocal_regions[:2], 1):
            logger.info(f"      Region {i}: {start:.1f}s - {end:.1f}s")

        # Find best vocal loop in track 2
        best_loop = None
        best_prominence = 0.0
        for loop in structure2.loop_regions:
            if loop.vocal_prominence > best_prominence and loop.label in [
                "drop_loop",
                "chorus_loop",
            ]:
                best_loop = loop
                best_prominence = loop.vocal_prominence

        if not best_loop:
            logger.warning("No suitable vocal loop found in next track")
            return False

        logger.info(
            f"\n   ✓ Best vocal loop: {best_loop.label} "
            f"({best_prominence:.1%} vocal, {best_loop.length_bars} bars)\n"
        )

        # Check key compatibility (Phase 3)
        logger.info("🎵 PHASE 3: Check key compatibility...")
        compatible = detect_key_compatibility(track1.key, track2.key)
        logger.info(f"   {track1.key} + {track2.key} = {'✅ Compatible' if compatible else '❌ Incompatible'}\n")

        if not compatible:
            logger.warning("Keys incompatible, preview not recommended")
            return False

        # Create vocal preview mix (Phase 4)
        logger.info("🎧 PHASE 4: Create vocal preview mix...")
        mixer = VocalPreviewMixer(sr=sr1)

        showcase_mix = mixer.create_preview_mix(
            current_audio=audio1,
            current_bpm=track1.bpm,
            next_audio=audio2,
            next_bpm=track2.bpm,
            next_loop_start=best_loop.start_seconds,
            next_loop_end=best_loop.end_seconds,
            current_key=track1.key,
            next_key=track2.key,
            current_has_vocals=structure1.has_vocal,
            current_vocal_regions=structure1.vocal_regions,
            transition_position=20.0,  # 20s before end
            fade_duration=10.0,  # 10s fade in
        )

        logger.info(f"   ✓ Mix created: {len(showcase_mix)/sr1:.1f}s\n")

        # Summary
        print("=" * 90)
        print("✅ SHOWCASE COMPLETE")
        print("=" * 90)
        print(f"\n📊 Results:")
        print(f"   • Vocal regions detected (Phase 1): ✅")
        print(f"   • Loop vocal prominence tagged (Phase 2): ✅")
        print(f"   • Key compatibility checked (Phase 3): ✅")
        print(f"   • Vocal preview mixed (Phase 4): ✅")
        print(f"\n🎧 Vocal Preview Features:")
        print(f"   • Next track vocal loop: {best_loop.label}")
        print(f"   • Vocal prominence: {best_prominence:.1%}")
        print(f"   • Injection point: ~20s before transition")
        print(f"   • Level: -18dB (subtle)")
        print(f"   • Fade duration: 10s")
        print(f"   • Time-stretched to: {track1.bpm:.1f} BPM")
        print(f"   • HPF filter applied: ✅ (prevent phasing)")
        print(f"\n📁 Mix ready for export!")

        audio_cache.clear()
        return True

    except Exception as e:
        logger.error(f"Showcase failed: {e}", exc_info=True)
        return False

    finally:
        db.disconnect()


if __name__ == "__main__":
    success = showcase_vocal_preview()
    sys.exit(0 if success else 1)
