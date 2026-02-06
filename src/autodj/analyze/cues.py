"""
Cue Point Detection: Identify Cue-In, Cue-Out, and optional loop windows.

Per SPEC.md § 5.1:
- Cue-In: First energetic downbeat (using aubio onset detection)
- Cue-Out: Energy drop before mix-out
- Loop window: Optional (16-32 bars)
- Budget: ≤ 100 MiB peak memory

Phase 1 Enhancement: Use aubio onset detection for more accurate cue points.
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


def _snap_to_beat(sample_pos: int, bpm: float, sample_rate: int) -> int:
    """Snap a sample position to the nearest beat boundary."""
    samples_per_beat = int((60.0 / bpm) * sample_rate)
    beat_number = round(sample_pos / samples_per_beat)
    return int(beat_number * samples_per_beat)


def _detect_onsets_aubio(audio_path: str, sample_rate: int, hop_size: int) -> list:
    """
    Detect onset points using aubio's onset detection.
    
    Onsets are attack points where new notes/drums typically start.
    More accurate than energy-based detection for finding cue points.
    
    Args:
        audio_path: Path to audio file
        sample_rate: Sample rate in Hz
        hop_size: Hop size for onset detection
        
    Returns:
        List of onset frame indices
    """
    try:
        source = aubio.source(audio_path, hop_size=hop_size)
        onset_detector = aubio.onset("default", hop_size=hop_size, samplerate=source.samplerate)
        
        onsets = []
        while True:
            samples, num_read = source()
            onset_detector(samples)
            if onset_detector.got_onset():
                # got_onset() returns True when an onset is detected
                # source.tell() returns current sample position
                onsets.append(source.tell())
            if num_read < hop_size:
                break
        
        logger.debug(f"Aubio onset detection found {len(onsets)} onsets")
        return onsets
        
    except Exception as e:
        logger.warning(f"Aubio onset detection failed: {e}")
        return []


def detect_cues(audio_path: str, bpm: float, config: dict) -> Optional[CuePoints]:
    """
    Detect cue points from audio file using aubio onset detection + energy analysis.

    Enhanced Algorithm (Phase 1):
    1. Detect onsets using aubio (attack points)
    2. Calculate RMS energy across the track
    3. Find cue_in: First onset that exceeds energy threshold (intro end)
    4. Find cue_out: Last onset before significant energy drop (outro start)
    5. Snap both to nearest beat boundary using BPM

    Args:
        audio_path: Path to audio file
        bpm: BPM of the track (used for beat-aligned cue detection)
        config: Analysis config dict with aubio parameters

    Returns:
        CuePoints object or None if detection failed
    """
    try:
        hop_size = config.get("aubio_hop_size", 512)

        # Load audio for analysis
        logger.debug(f"Loading audio for cue detection: {audio_path}")
        source = aubio.source(audio_path, hop_size=hop_size)
        sample_rate = source.samplerate

        # Phase 1: Detect onsets using aubio (more accurate than energy alone)
        logger.debug(f"Detecting onsets with aubio...")
        onsets = _detect_onsets_aubio(audio_path, sample_rate, hop_size)
        
        # Phase 2: Process audio for energy analysis
        source.seek(0)  # Reset to beginning
        energies = []
        frame_count = 0
        total_samples = 0

        while True:
            samples, num_read = source()
            if num_read == 0:
                break

            # Calculate frame energy (RMS)
            frame_energy = float(np.sqrt(np.mean(samples ** 2)))
            energies.append(frame_energy)

            frame_count += 1
            total_samples += num_read

            if num_read < hop_size:
                break

        if not energies or len(energies) < 10:
            logger.warning("Insufficient audio data for cue detection")
            return None

        # Convert to numpy array and normalize
        energy_array = np.array(energies)
        energy_array = np.maximum(energy_array, 1e-6)  # Avoid log(0)

        # Smooth with larger window for robust detection (~4 seconds)
        window_frames = max(1, int(4 * sample_rate / hop_size))
        smoothed = np.convolve(energy_array, np.ones(window_frames) / window_frames, mode="same")

        # Normalize to 0-1 range
        smoothed_norm = (smoothed - smoothed.min()) / (smoothed.max() - smoothed.min() + 1e-6)

        # === CUE IN DETECTION (IMPROVED) ===
        # Use first onset that exceeds 20% of normalized energy range
        # This is more accurate than energy peak alone
        cue_in_threshold = 0.2
        cue_in_frame = None
        
        if onsets:
            # Find first onset above energy threshold
            for onset_frame in onsets:
                if onset_frame < len(smoothed_norm) and smoothed_norm[onset_frame] > cue_in_threshold:
                    cue_in_frame = int(onset_frame)
                    break
        
        # Fallback to energy-based if no suitable onset found
        if cue_in_frame is None:
            above_threshold = np.where(smoothed_norm > cue_in_threshold)[0]
            if len(above_threshold) > 0:
                cue_in_frame = int(above_threshold[0])
            else:
                cue_in_frame = 0

        # === CUE OUT DETECTION (IMPROVED) ===
        # Use last onset before significant energy drop
        cue_out_threshold = 0.15
        cue_out_frame = None
        
        if onsets:
            # Find last onset with sufficient energy
            for onset_frame in reversed(onsets):
                if onset_frame < len(smoothed_norm) and smoothed_norm[onset_frame] > cue_out_threshold:
                    cue_out_frame = int(onset_frame)
                    break
        
        # Fallback to energy-based if no suitable onset found
        if cue_out_frame is None:
            above_out_threshold = np.where(smoothed_norm > cue_out_threshold)[0]
            if len(above_out_threshold) > 0:
                cue_out_frame = int(above_out_threshold[-1])
            else:
                cue_out_frame = len(smoothed_norm) - 1

        # Ensure minimum track length (at least 30 seconds usable)
        min_frames = int(30 * sample_rate / hop_size)
        if cue_out_frame - cue_in_frame < min_frames:
            # Reset to use most of the track
            cue_in_frame = 0
            cue_out_frame = len(smoothed_norm) - 1

        # Convert to sample positions
        cue_in_samples = cue_in_frame * hop_size
        cue_out_samples = min(cue_out_frame * hop_size, total_samples - 1)

        # Snap to beat boundaries for clean DJ transitions
        if bpm > 0:
            cue_in_samples = _snap_to_beat(cue_in_samples, bpm, sample_rate)
            cue_out_samples = _snap_to_beat(cue_out_samples, bpm, sample_rate)

        # Ensure cue_out > cue_in and within bounds
        cue_in_samples = max(0, cue_in_samples)
        cue_out_samples = min(cue_out_samples, total_samples - 1)

        if cue_out_samples <= cue_in_samples:
            cue_out_samples = total_samples - 1

        # Convert to native Python int for SQLite compatibility
        cue_in_samples = int(cue_in_samples)
        cue_out_samples = int(cue_out_samples)

        usable_duration = (cue_out_samples - cue_in_samples) / sample_rate
        logger.info(
            f"✅ Cues detected (aubio-enhanced): in={cue_in_samples} ({cue_in_samples/sample_rate:.1f}s), "
            f"out={cue_out_samples} ({cue_out_samples/sample_rate:.1f}s) "
            f"[usable: {usable_duration:.1f}s, {len(onsets)} onsets detected]"
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
