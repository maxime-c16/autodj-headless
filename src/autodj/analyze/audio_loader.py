"""
Audio Loading & Caching Module
================================

Provides a shared audio cache so that multiple analysis modules
(spectral, loudness, adaptive_eq) can reuse the same loaded audio
data without redundant disk I/O.

Per SPEC.md: one track at a time, explicit memory cleanup.

Author: Claude Opus 4.6 DSP Implementation
Date: 2026-02-07
"""

import gc
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np

try:
    import scipy.io.wavfile as wavfile
    import scipy.signal as signal
except ImportError:
    raise ImportError("scipy required: pip install scipy")

logger = logging.getLogger(__name__)


class AudioCache:
    """Shared audio loading and caching.

    Loads audio files once and provides the data to multiple analysis
    modules, eliminating redundant disk reads. Supports configurable
    sample rate and explicit memory cleanup.

    Usage:
        cache = AudioCache(sample_rate=44100)
        audio, sr = cache.load(filepath)
        # ... use audio in spectral, loudness, etc.
        cache.clear()  # free memory after track is done
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        self.sample_rate = sample_rate
        self._cache: Dict[str, Tuple[np.ndarray, int]] = {}

    def load(
        self,
        filepath: str,
        mono: bool = True,
    ) -> Tuple[np.ndarray, int]:
        """Load audio file, returning cached data if available.

        Args:
            filepath: Path to audio file
            mono: If True, convert stereo to mono

        Returns:
            Tuple of (audio_data as float32, sample_rate)

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If format not supported
        """
        cache_key = f"{filepath}:{'mono' if mono else 'stereo'}"

        if cache_key in self._cache:
            logger.debug(f"AudioCache hit: {Path(filepath).name}")
            return self._cache[cache_key]

        logger.debug(f"AudioCache miss: {Path(filepath).name}")
        audio, sr = _load_audio_from_disk(filepath, self.sample_rate, mono)
        self._cache[cache_key] = (audio, sr)
        return audio, sr

    def clear(self) -> None:
        """Free all cached audio data and force garbage collection."""
        n = len(self._cache)
        self._cache.clear()
        gc.collect()
        if n > 0:
            logger.debug(f"AudioCache cleared ({n} entries)")

    def __len__(self) -> int:
        return len(self._cache)

    def __contains__(self, filepath: str) -> bool:
        return any(filepath in k for k in self._cache)


def _load_audio_from_disk(
    filepath: str,
    target_sr: int = 44100,
    mono: bool = True,
) -> Tuple[np.ndarray, int]:
    """Load audio file from disk.

    Args:
        filepath: Path to audio file
        target_sr: Target sample rate
        mono: Convert to mono if True

    Returns:
        Tuple of (audio float32, sample_rate)
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {filepath}")

    suffix = path.suffix.lower()

    if suffix == ".wav":
        sr, audio = wavfile.read(filepath)
        # Normalize to float32 [-1.0, 1.0]
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        elif audio.dtype == np.int32:
            audio = audio.astype(np.float32) / 2147483648.0
        elif audio.dtype == np.float64:
            audio = audio.astype(np.float32)
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32) / np.iinfo(audio.dtype).max

        # Convert stereo to mono if needed
        if mono and audio.ndim > 1:
            audio = np.mean(audio, axis=1)

        # Resample if needed
        if sr != target_sr:
            if audio.ndim == 1:
                audio = signal.resample_poly(
                    audio, target_sr, sr
                ).astype(np.float32)
            else:
                n_out = int(len(audio) * target_sr / sr)
                resampled = np.zeros(
                    (n_out, audio.shape[1]), dtype=np.float32
                )
                for ch in range(audio.shape[1]):
                    resampled[:, ch] = signal.resample_poly(
                        audio[:, ch], target_sr, sr
                    ).astype(np.float32)
                audio = resampled
            sr = target_sr

        return audio, sr

    else:
        # Non-WAV: use librosa
        try:
            import librosa
            audio, sr = librosa.load(filepath, sr=target_sr, mono=mono)
            if not mono and audio.ndim == 2:
                audio = audio.T  # librosa returns (channels, samples)
            return audio.astype(np.float32), sr
        except ImportError:
            raise ValueError(
                f"librosa required for {suffix} files. pip install librosa"
            )
