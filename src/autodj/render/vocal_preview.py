"""
Vocal Preview Mixing Engine (Phase 4)

Layers vocal loops from upcoming tracks into current track
during non-vocal sections for smooth transitions.

Features:
- Time-stretching for tempo matching
- HPF filtering to prevent phasing
- Smooth amplitude envelopes
- Key compatibility checking
- Automatic preview injection

Author: AutoDJ Pro Mixer
Date: 2026-02-12
"""

import numpy as np
from typing import Optional, Tuple, List
import logging

logger = logging.getLogger(__name__)


class VocalPreviewMixer:
    """Mix vocal previews from next track into current track."""

    def __init__(self, sr: int = 44100):
        """Initialize mixer.

        Args:
            sr: Sample rate (default 44100)
        """
        self.sr = sr
        self.hop_length = 512

    def extract_loop_audio(
        self, audio: np.ndarray, loop_start: float, loop_end: float
    ) -> np.ndarray:
        """Extract audio for a loop region.

        Args:
            audio: Full track audio
            loop_start: Start time in seconds
            loop_end: End time in seconds

        Returns:
            Audio samples for the loop
        """
        start_sample = int(loop_start * self.sr)
        end_sample = int(loop_end * self.sr)

        start_sample = max(0, start_sample)
        end_sample = min(end_sample, len(audio))

        if start_sample >= end_sample:
            return np.array([], dtype=np.float32)

        return audio[start_sample:end_sample].copy()

    def time_stretch_audio(
        self, audio: np.ndarray, source_bpm: float, target_bpm: float
    ) -> np.ndarray:
        """Time-stretch audio to match target BPM.

        Simple phase vocoder using librosa if available, else basic interpolation.

        Args:
            audio: Audio to stretch
            source_bpm: Original BPM
            target_bpm: Target BPM

        Returns:
            Time-stretched audio
        """
        if source_bpm == target_bpm or source_bpm <= 0 or target_bpm <= 0:
            return audio

        stretch_factor = target_bpm / source_bpm

        try:
            import librosa
            stretched = librosa.effects.time_stretch(audio, rate=stretch_factor)
            return stretched.astype(np.float32)
        except ImportError:
            # Fallback: simple linear interpolation
            n_samples = int(len(audio) / stretch_factor)
            indices = np.linspace(0, len(audio) - 1, n_samples)
            stretched = np.interp(indices, np.arange(len(audio)), audio)
            return stretched.astype(np.float32)

    def apply_highpass_filter(
        self, audio: np.ndarray, cutoff_hz: float = 300.0
    ) -> np.ndarray:
        """Apply high-pass filter to reduce low-frequency phasing.

        Args:
            audio: Audio to filter
            cutoff_hz: Cutoff frequency in Hz

        Returns:
            Filtered audio
        """
        try:
            from scipy import signal

            nyquist = self.sr / 2.0
            normalized_cutoff = cutoff_hz / nyquist

            if normalized_cutoff <= 0 or normalized_cutoff >= 1:
                return audio

            # Butterworth 4th-order HPF
            sos = signal.butter(4, normalized_cutoff, btype="high", output="sos")
            filtered = signal.sosfilt(sos, audio)
            return filtered.astype(np.float32)
        except Exception as e:
            logger.warning(f"HPF filter failed: {e}, returning unfiltered audio")
            return audio

    def create_amplitude_envelope(
        self,
        total_samples: int,
        fade_in_samples: int,
        fade_out_samples: int,
        peak_level_db: float = -18.0,
    ) -> np.ndarray:
        """Create smooth amplitude envelope (fade in, hold, fade out).

        Args:
            total_samples: Total number of samples
            fade_in_samples: Samples for fade-in
            fade_out_samples: Samples for fade-out
            peak_level_db: Peak level in dB

        Returns:
            Amplitude envelope array (0.0-1.0)
        """
        envelope = np.ones(total_samples, dtype=np.float32)

        # Convert dB to linear (0.0-1.0)
        peak_linear = 10 ** (peak_level_db / 20.0)

        # Fade in (0 → peak)
        fade_in_samples = min(fade_in_samples, total_samples)
        if fade_in_samples > 0:
            envelope[:fade_in_samples] = np.linspace(0.0, peak_linear, fade_in_samples)

        # Fade out (peak → 0)
        fade_out_start = total_samples - fade_out_samples
        fade_out_samples = min(fade_out_samples, total_samples)
        if fade_out_samples > 0:
            envelope[-fade_out_samples:] = np.linspace(
                peak_linear, 0.0, fade_out_samples
            )

        # Hold middle at peak
        if fade_in_samples < fade_out_start:
            envelope[fade_in_samples:fade_out_start] = peak_linear

        return envelope

    def inject_vocal_preview(
        self,
        mix: np.ndarray,
        preview: np.ndarray,
        inject_start_samples: int,
        level_db: float = -18.0,
    ) -> np.ndarray:
        """Layer vocal preview into mix at specified time.

        Args:
            mix: Main mix audio
            preview: Preview audio to layer
            inject_start_samples: Sample offset to start injection
            level_db: Level of preview in dB

        Returns:
            Mixed audio
        """
        if len(preview) == 0:
            return mix

        # Ensure preview doesn't exceed mix length
        inject_end = inject_start_samples + len(preview)
        if inject_end > len(mix):
            preview = preview[: len(mix) - inject_start_samples]
            inject_end = len(mix)

        if inject_start_samples < 0 or inject_start_samples >= len(mix):
            return mix

        # Convert dB to linear
        level_linear = 10 ** (level_db / 20.0)

        # Add preview to mix
        mix[inject_start_samples:inject_end] += preview * level_linear

        # Prevent clipping (soft limiting)
        max_val = np.max(np.abs(mix))
        if max_val > 0.95:
            mix = mix * (0.95 / max_val)

        return mix

    def create_preview_mix(
        self,
        current_audio: np.ndarray,
        current_bpm: float,
        next_audio: np.ndarray,
        next_bpm: float,
        next_loop_start: float,
        next_loop_end: float,
        current_key: str,
        next_key: str,
        current_has_vocals: bool,
        current_vocal_regions: Optional[List[Tuple[float, float]]] = None,
        transition_position: float = 20.0,  # Seconds before transition
        fade_duration: float = 10.0,  # Fade in duration
    ) -> np.ndarray:
        """Create mix with vocal preview layering.

        Args:
            current_audio: Current track audio
            current_bpm: Current track BPM
            next_audio: Next track audio
            next_bpm: Next track BPM
            next_loop_start: Vocal loop start in next track
            next_loop_end: Vocal loop end in next track
            current_key: Current track key
            next_key: Next track key
            current_has_vocals: Does current track have vocals?
            current_vocal_regions: Vocal region time ranges in current track
            transition_position: Seconds from end to start preview
            fade_duration: Duration of fade-in in seconds

        Returns:
            Mixed audio with preview
        """
        from autodj.analyze.structure import detect_key_compatibility

        # Check key compatibility
        if not detect_key_compatibility(current_key, next_key):
            logger.warning(f"Keys incompatible ({current_key} vs {next_key}), skipping preview")
            return current_audio.copy()

        # Check if current track has non-vocal sections
        if current_has_vocals and current_vocal_regions:
            # Find first non-vocal region
            current_duration = len(current_audio) / self.sr
            has_nonvocal = False
            nonvocal_start = None

            # Simple check: see if end of track is non-vocal
            last_vocal_end = max([end for start, end in current_vocal_regions], default=0)
            if last_vocal_end < current_duration - 5:  # Last 5s non-vocal
                has_nonvocal = True
                nonvocal_start = last_vocal_end

            if not has_nonvocal:
                logger.warning("No non-vocal sections found for preview injection")
                return current_audio.copy()
        else:
            nonvocal_start = 0

        # Extract next track's vocal loop
        vocal_preview = self.extract_loop_audio(next_audio, next_loop_start, next_loop_end)

        if len(vocal_preview) < self.sr:  # Less than 1 second
            logger.warning("Vocal preview too short")
            return current_audio.copy()

        # Time-stretch to match current BPM
        vocal_preview = self.time_stretch_audio(vocal_preview, next_bpm, current_bpm)

        # Apply HPF to prevent phasing with bass
        vocal_preview = self.apply_highpass_filter(vocal_preview, cutoff_hz=300.0)

        # Calculate injection point (transition_position seconds before end)
        current_duration_sec = len(current_audio) / self.sr
        inject_time_sec = max(nonvocal_start, current_duration_sec - transition_position)
        inject_samples = int(inject_time_sec * self.sr)

        # Create amplitude envelope
        fade_samples = int(fade_duration * self.sr)
        fade_out_samples = int(5.0 * self.sr)  # 5s fade out
        envelope = self.create_amplitude_envelope(
            len(vocal_preview),
            fade_in_samples=fade_samples,
            fade_out_samples=fade_out_samples,
            peak_level_db=-18.0,  # Subtle level
        )

        # Apply envelope
        # Fix: Expand envelope to 2D for stereo/multi-channel compatibility
        envelope_2d = envelope[:, np.newaxis] if len(envelope.shape) == 1 else envelope
        vocal_preview_enveloped = vocal_preview * envelope_2d

        # Mix into current audio
        mix = current_audio.copy()
        mix = self.inject_vocal_preview(
            mix, vocal_preview_enveloped, inject_samples, level_db=0.0
        )

        logger.info(
            f"✓ Vocal preview injected: {inject_time_sec:.1f}s, "
            f"duration {len(vocal_preview)/self.sr:.1f}s, level -18dB"
        )

        return mix
