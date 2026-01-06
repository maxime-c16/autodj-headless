"""
Cue Point Detection: Identify Cue-In, Cue-Out, and optional loop windows.

Per SPEC.md § 5.1:
- Cue-In: First energetic downbeat
- Cue-Out: Energy drop before mix-out
- Loop window: Optional (16-32 bars)
- Budget: ≤ 100 MiB peak memory
"""

import logging
from typing import Optional
import aubio
import numpy as np

logger = logging.getLogger(__name__)


class CuePoints:
    """Container for cue point data."""

    def __init__(
        self,
        cue_in: int,
        cue_out: int,
        loop_start: Optional[int] = None,
        loop_length: Optional[int] = None,
    ):
        """
        Args:
            cue_in: Frame offset for start (@ 44.1 kHz)
            cue_out: Frame offset for end
            loop_start: Optional frame offset for loop
            loop_length: Optional loop length in bars
        """
        self.cue_in = cue_in
        self.cue_out = cue_out
        self.loop_start = loop_start
        self.loop_length = loop_length

    def __repr__(self) -> str:
        return f"CuePoints(in={self.cue_in}, out={self.cue_out}, loop_start={self.loop_start})"


def detect_cues(audio_path: str, bpm: float, config: dict) -> Optional[CuePoints]:
    """
    Detect cue points from audio file using energy analysis + onset detection.

    Args:
        audio_path: Path to audio file
        bpm: BPM of the track (used for beat-aligned cue detection)
        config: Analysis config dict with aubio parameters

    Returns:
        CuePoints object or None if detection failed
    """
    try:
        hop_size = config.get("aubio_hop_size", 512)
        buf_size = config.get("aubio_buf_size", 4096)

        # Load audio
        logger.debug(f"Loading audio for cue detection: {audio_path}")
        source = aubio.source(audio_path, hop_size=hop_size)
        sample_rate = source.samplerate

        # Create onset detector for cue-in detection
        onset_detector = aubio.onset("energy", buf_size=buf_size, hop_size=hop_size)

        # Process audio and collect onset/energy data
        energies = []
        onsets = []
        frame_count = 0
        total_samples = 0

        while True:
            samples, num_read = source()
            if num_read == 0:
                break

            # Calculate frame energy (RMS)
            frame_energy = np.sqrt(np.mean(samples ** 2))
            energies.append(frame_energy)

            # Detect onset
            is_onset = onset_detector(samples)
            if is_onset:
                onsets.append(frame_count)

            frame_count += 1
            total_samples += num_read

            if num_read < hop_size:
                break

        if not energies or len(energies) < 10:
            logger.warning("Insufficient audio data for cue detection")
            return None

        # Convert to numpy arrays for analysis
        energy_array = np.array(energies)
        energy_array = np.maximum(energy_array, 1e-6)  # Avoid log(0)
        energy_db = 20 * np.log10(energy_array / energy_array.max())

        # Calculate smoothed energy with moving average
        window_size = max(1, len(energy_db) // 50)  # ~2% of track
        smoothed_energy = np.convolve(energy_db, np.ones(window_size) / window_size, mode="same")

        # Find cue-in: first energetic peak or first onset
        threshold = smoothed_energy.max() * 0.6  # 60% of max
        above_threshold = np.where(smoothed_energy > threshold)[0]

        if len(above_threshold) > 0:
            cue_in_frame = above_threshold[0]
        elif len(onsets) > 0:
            # Fallback: use first detected onset
            cue_in_frame = onsets[0]
        else:
            # Last resort: start from beginning
            cue_in_frame = 0

        # Find cue-out: energy drop in tail or use 95% of track
        tail_start = max(0, int(len(smoothed_energy) * 0.8))
        tail_energy = smoothed_energy[tail_start:]

        if len(tail_energy) > 10:
            # Find where energy drops significantly
            energy_diffs = np.diff(tail_energy)
            # Find drops (negative differences)
            drops = np.where(energy_diffs < -np.std(energy_diffs))[0]
            if len(drops) > 0:
                cue_out_frame = tail_start + drops[0]
            else:
                # If no clear drop, use 95% point
                cue_out_frame = int(len(smoothed_energy) * 0.95)
        else:
            cue_out_frame = len(smoothed_energy) - 1

        # Ensure cue_out > cue_in
        if cue_out_frame <= cue_in_frame:
            cue_out_frame = len(smoothed_energy) - 1

        # Convert frame indices to sample offsets
        cue_in_samples = cue_in_frame * hop_size
        cue_out_samples = min(cue_out_frame * hop_size, total_samples - 1)

        logger.info(
            f"✅ Cues detected: in={cue_in_samples}, out={cue_out_samples} "
            f"(duration: {(cue_out_samples - cue_in_samples) / sample_rate:.1f}s)"
        )

        return CuePoints(
            cue_in=cue_in_samples,
            cue_out=cue_out_samples,
            loop_start=None,
            loop_length=None,
        )

    except Exception as e:
        logger.error(f"Cue detection failed for {audio_path}: {e}", exc_info=True)
        return None
