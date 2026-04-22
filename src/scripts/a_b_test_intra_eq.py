#!/usr/bin/env python3
"""
A/B Test Generator for Intra-Track EQ Cuts.

Generates multiple variants of a single track with different EQ strategies:
- A: Baseline (no EQ cuts)
- B: Moderate (2-3 high-confidence cuts)
- C: Aggressive (all detected cuts)

Usage:
    python src/scripts/a_b_test_intra_eq.py --track-id "track_uuid" --output-dir "/path/to/output"
    
Example:
    python src/scripts/a_b_test_intra_eq.py --track-id "never_enough_bsls" --output-dir "./a_b_tests"
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import librosa
import soundfile as sf
import numpy as np
from scipy import signal

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Import autodj modules
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.db import Database
from autodj.generate.eq_selector import IntraTrackEQSelector, EQCutOpportunity


def load_track_audio(file_path: str, sr: int = 44100) -> tuple:
    """
    Load audio file.

    Args:
        file_path: Path to audio file
        sr: Sample rate (default 44100 Hz for CD quality, no resampling)

    Returns:
        Tuple (audio_array, sample_rate)
    """
    logger.info(f"Loading audio at {sr}Hz: {file_path}")
    audio, sr_native = librosa.load(file_path, sr=sr, mono=False)
    logger.info(f"  Shape: {audio.shape}, SR: {sr_native}")
    return audio, sr_native


def apply_eq_cut(
    audio: np.ndarray,
    cut: EQCutOpportunity,
    bpm: float,
    sr: int,
) -> np.ndarray:
    """
    Apply a single EQ cut to audio with envelope.

    Args:
        audio: Audio array (mono 1D or stereo 2D: [channels, samples])
        cut: EQCutOpportunity object
        bpm: Tempo in BPM
        sr: Sample rate

    Returns:
        Audio with EQ cut applied
    """
    logger.info(
        f"Applying {cut.cut_type} at bar {cut.bar}: "
        f"{cut.filter_params['type']} @ {cut.filter_params.get('freq', 'N/A')}Hz"
    )

    # Check if stereo or mono
    is_stereo = audio.ndim > 1
    if is_stereo:
        audio_length = audio.shape[1]
    else:
        audio_length = len(audio)

    # Calculate bar and timing
    bar_duration_samples = int((60 / bpm) * 4 * sr)  # 4 beats per bar
    start_sample = cut.bar * bar_duration_samples

    envelope_data = cut.envelope
    attack_samples = int(envelope_data["attack_ms"] * sr / 1000)
    hold_bars = envelope_data["hold_bars"]
    hold_samples = int(hold_bars * bar_duration_samples)
    release_samples = int(envelope_data["release_ms"] * sr / 1000)

    # Ensure we don't exceed audio length
    end_sample = min(
        start_sample + attack_samples + hold_samples + release_samples, audio_length
    )
    if start_sample >= audio_length:
        logger.warning(f"Cut starts after audio ends (bar {cut.bar}), skipping")
        return audio

    # Design filter
    nyquist = sr / 2.0
    filter_type = cut.filter_params.get("type", "low_pass")
    freq = cut.filter_params.get("freq", 100)
    q = cut.filter_params.get("q", 1.0)

    # Normalized frequency
    norm_freq = freq / nyquist
    norm_freq = np.clip(norm_freq, 0.001, 0.999)

    # Create filter
    try:
        if filter_type == "low_pass":
            b, a = signal.butter(4, norm_freq, btype="low", analog=False)
        elif filter_type == "high_pass":
            b, a = signal.butter(4, norm_freq, btype="high", analog=False)
        elif filter_type == "band_stop":
            # Bandstop (notch) around freq with Q
            bandwidth = freq / q
            low = (freq - bandwidth / 2) / nyquist
            high = (freq + bandwidth / 2) / nyquist
            low = np.clip(low, 0.001, 0.999)
            high = np.clip(high, 0.001, 0.999)
            if low < high:
                b, a = signal.butter(4, [low, high], btype="bandstop", analog=False)
            else:
                logger.warning(f"Invalid bandstop range, skipping filter")
                return audio
        else:
            logger.warning(f"Unknown filter type: {filter_type}")
            return audio
    except Exception as e:
        logger.warning(f"Filter design failed: {e}, skipping")
        return audio

    # Build envelope (0 = dry/unfiltered, 1 = fully filtered)
    envelope_len = end_sample - start_sample
    envelope = np.ones(envelope_len)
    attack_end = min(attack_samples, envelope_len)
    hold_end = min(attack_samples + hold_samples, envelope_len)
    release_end = envelope_len

    # Attack phase: gradually introduce filter (0 → 1)
    if attack_end > 0:
        envelope[:attack_end] = np.linspace(0, 1, attack_end)
    
    # Hold phase: maintain full filter
    if hold_end > attack_end:
        envelope[attack_end:hold_end] = 1.0
    
    # Release phase: gradually remove filter (1 → 0)
    if release_end > hold_end:
        envelope[hold_end:release_end] = np.linspace(1, 0, release_end - hold_end)

    # Apply filter and blend for each channel
    if is_stereo:
        for ch in range(audio.shape[0]):
            segment = audio[ch, start_sample:end_sample].copy()
            try:
                filtered_segment = signal.filtfilt(b, a, segment)
            except Exception as e:
                logger.warning(f"Filter application failed on channel {ch}: {e}, skipping")
                return audio
            
            # Blend: dry when envelope=0, filtered when envelope=1
            blended_segment = segment * (1 - envelope) + filtered_segment * envelope
            audio[ch, start_sample:end_sample] = blended_segment
    else:
        segment = audio[start_sample:end_sample].copy()
        try:
            filtered_segment = signal.filtfilt(b, a, segment)
        except Exception as e:
            logger.warning(f"Filter application failed: {e}, skipping")
            return audio
        
        # Blend: dry when envelope=0, filtered when envelope=1
        blended_segment = segment * (1 - envelope) + filtered_segment * envelope
        audio[start_sample:end_sample] = blended_segment

    return audio


def generate_variants(
    track_id: str,
    audio_file: str,
    output_dir: Path,
    db: Database,
) -> Dict[str, Any]:
    """
    Generate A/B/C test variants.

    Args:
        track_id: Track database ID
        audio_file: Path to audio file
        output_dir: Where to save variants
        db: Database connection

    Returns:
        Metadata dict with info about generated variants
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get track analysis
    analysis = db.get_track_analysis(track_id)
    if not analysis:
        logger.error(f"Track {track_id} not found in analysis")
        return None

    metadata = db.get_track(track_id)
    if not metadata:
        logger.error(f"Track {track_id} not found in metadata")
        return None

    bpm = metadata.bpm or 120
    title = metadata.title or "Unknown"

    logger.info(f"\n{'='*60}")
    logger.info(f"Track: {title} (BPM: {bpm})")
    logger.info(f"{'='*60}")

    # Load audio
    audio, sr = load_track_audio(audio_file)

    # Analyze for EQ opportunities
    selector = IntraTrackEQSelector(min_confidence=0.70)
    opportunities = selector.analyze_track(analysis)

    logger.info(f"\nDetected {len(opportunities)} EQ opportunities:")
    for opp in opportunities:
        logger.info(f"  - {opp.cut_type} @ bar {opp.bar} (confidence: {opp.confidence:.2f})")

    # Generate variants
    variants = {}

    # A: Baseline (no cuts)
    logger.info("\n[A] BASELINE: No EQ cuts (control)")
    audio_a = audio.copy()
    variant_a = f"{title}_A_baseline.wav".replace(" ", "_").replace("/", "_")
    path_a = output_dir / variant_a
    # Write at 24-bit to preserve float precision better than 16-bit
    audio_to_save = audio_a.T if audio_a.ndim > 1 else audio_a
    sf.write(str(path_a), audio_to_save, sr, subtype='PCM_24')
    logger.info(f"  ✅ Saved: {variant_a} (24-bit)")
    variants["A_baseline"] = {
        "path": str(path_a),
        "cuts": [],
        "description": "Control: no EQ automation",
    }

    # B: Moderate (top 2-3 cuts)
    logger.info("\n[B] MODERATE: Conservative EQ cuts")
    cuts_b = selector.select_cuts(opportunities, strategy="moderate")
    audio_b = audio.copy()
    for cut in cuts_b:
        audio_b = apply_eq_cut(audio_b, cut, bpm, sr)
    variant_b = f"{title}_B_moderate.wav".replace(" ", "_").replace("/", "_")
    path_b = output_dir / variant_b
    audio_to_save = audio_b.T if audio_b.ndim > 1 else audio_b
    sf.write(str(path_b), audio_to_save, sr, subtype='PCM_24')
    logger.info(f"  ✅ Saved: {variant_b} (24-bit)")
    variants["B_moderate"] = {
        "path": str(path_b),
        "cuts": [c.to_dict() for c in cuts_b],
        "description": f"Moderate: {len(cuts_b)} EQ cuts",
    }

    # C: Aggressive (all cuts)
    logger.info("\n[C] AGGRESSIVE: All EQ cuts")
    cuts_c = selector.select_cuts(opportunities, strategy="aggressive")
    audio_c = audio.copy()
    for cut in cuts_c:
        audio_c = apply_eq_cut(audio_c, cut, bpm, sr)
    variant_c = f"{title}_C_aggressive.wav".replace(" ", "_").replace("/", "_")
    path_c = output_dir / variant_c
    audio_to_save = audio_c.T if audio_c.ndim > 1 else audio_c
    sf.write(str(path_c), audio_to_save, sr, subtype='PCM_24')
    logger.info(f"  ✅ Saved: {variant_c} (24-bit)")
    variants["C_aggressive"] = {
        "path": str(path_c),
        "cuts": [c.to_dict() for c in cuts_c],
        "description": f"Aggressive: {len(cuts_c)} EQ cuts",
    }

    # Save metadata
    metadata_file = output_dir / f"{title}_metadata.json".replace(" ", "_").replace("/", "_")
    metadata_dict = {
        "track_id": track_id,
        "title": title,
        "bpm": bpm,
        "sample_rate": int(sr),
        "variants": variants,
        "all_opportunities": [o.to_dict() for o in opportunities],
    }
    with open(metadata_file, "w") as f:
        json.dump(metadata_dict, f, indent=2)
    logger.info(f"\n📋 Metadata saved: {metadata_file}")

    logger.info(f"\n{'='*60}")
    logger.info("A/B Test Complete!")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Listen to A (baseline) vs B (moderate) vs C (aggressive)")
    logger.info(f"{'='*60}\n")

    return metadata_dict


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Generate A/B test variants for intra-track EQ")
    parser.add_argument("--track-id", required=True, help="Track ID in database or track title")
    parser.add_argument("--audio-file", help="Path to audio file (auto-detect if not provided)")
    parser.add_argument("--output-dir", default="./a_b_tests", help="Output directory")

    args = parser.parse_args()

    # Connect to database
    db = Database()
    db.connect()

    try:
        track_input = args.track_id
        output_dir = Path(args.output_dir)

        # Try to find track by ID first, then by title
        metadata = db.get_track(track_input)
        if not metadata:
            logger.info(f"Track ID not found, searching by title: {track_input}")
            # Search by title in database
            cursor = db.conn.cursor()
            cursor.execute(
                "SELECT id, title, file_path, bpm FROM tracks WHERE title LIKE ? LIMIT 1",
                (f"%{track_input}%",)
            )
            result = cursor.fetchone()
            if result:
                track_id = result["id"]
                metadata = dict(result)
                logger.info(f"Found track: {metadata['title']}")
            else:
                logger.error(f"Track not found: {track_input}")
                return 1
        else:
            track_id = track_input

        # Get track analysis
        analysis = db.get_track_analysis(track_id)
        if not analysis:
            logger.error(f"Track analysis not found for {track_id}")
            logger.info("Run 'make analyze' first to analyze the library")
            return 1

        # Auto-detect audio file if not provided
        audio_file = args.audio_file or metadata.get("file_path")
        if not audio_file or not Path(audio_file).exists():
            logger.error(f"Audio file not found: {audio_file}")
            return 1

        # Generate variants
        result = generate_variants(track_id, audio_file, output_dir, db)
        if not result:
            return 1

        return 0

    finally:
        db.disconnect()


if __name__ == "__main__":
    exit(main())
