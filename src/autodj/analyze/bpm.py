"""
BPM Detection using essentia (primary) with aubio fallback.

Per SPEC.md § 5.1:
- Uses essentia RhythmExtractor2013 for accuracy
- Fallback to aubio tempo for compatibility
- Budget: ≤ 150 MiB peak memory
- Single file at a time

References:
- https://essentia.upf.edu/tutorial_rhythm_beatdetection.html
- https://github.com/aubio/aubio/issues/227
"""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _normalize_bpm(bpm: float, target_range: Tuple[float, float] = (85, 175)) -> float:
    """
    Normalize BPM to DJ-friendly range by halving or doubling.

    Electronic music typically runs 120-150 BPM. Algorithms often return
    half (60-75) or double (240-300) the actual tempo.

    Args:
        bpm: Detected BPM value
        target_range: Preferred BPM range (min, max)

    Returns:
        Normalized BPM within target range
    """
    min_bpm, max_bpm = target_range

    # Keep doubling if too slow
    while bpm < min_bpm and bpm > 0:
        bpm *= 2

    # Keep halving if too fast
    while bpm > max_bpm:
        bpm /= 2

    return bpm


def _detect_bpm_essentia(audio_path: str, max_duration: float = 60.0) -> Optional[Tuple[float, float]]:
    """
    Detect BPM using essentia's RhythmExtractor2013 (more accurate).

    Memory-optimized: only analyzes first 60 seconds to stay within container limits.

    Args:
        audio_path: Path to audio file
        max_duration: Maximum seconds to analyze (default 60s for memory efficiency)

    Returns:
        Tuple of (bpm, confidence) or None if failed
    """
    try:
        import essentia.standard as es
        import numpy as np

        logger.debug("Using essentia RhythmExtractor2013...")

        # Load audio at 44100 Hz
        sample_rate = 44100
        audio = es.MonoLoader(filename=audio_path, sampleRate=sample_rate)()

        # Limit to max_duration seconds to avoid OOM (512MB container limit)
        max_samples = int(max_duration * sample_rate)
        if len(audio) > max_samples:
            # Analyze middle portion (skip intro/outro which may have different tempo)
            start_offset = min(len(audio) // 4, int(30 * sample_rate))  # Skip first 30s max
            end_offset = start_offset + max_samples
            if end_offset > len(audio):
                end_offset = len(audio)
                start_offset = max(0, end_offset - max_samples)
            audio = audio[start_offset:end_offset]
            logger.debug(f"Analyzing {len(audio)/sample_rate:.1f}s sample (offset {start_offset/sample_rate:.1f}s)")

        # Use degara method (faster, lower memory than multifeature)
        rhythm_extractor = es.RhythmExtractor2013(method="degara")
        bpm, beats, beats_confidence, _, beats_intervals = rhythm_extractor(audio)

        # Calculate overall confidence from beat confidences
        if len(beats_confidence) > 0:
            confidence = float(np.mean(beats_confidence))
        else:
            confidence = 0.5  # Default confidence if no beats detected

        logger.debug(f"Essentia raw BPM: {bpm:.1f}, confidence: {confidence:.2f}")

        if bpm > 0:
            return (float(bpm), confidence)
        return None

    except ImportError:
        logger.debug("Essentia not available")
        return None
    except Exception as e:
        logger.debug(f"Essentia BPM detection failed: {e}")
        return None


def _detect_bpm_aubio(audio_path: str, config: dict) -> Optional[Tuple[float, float]]:
    """
    Detect BPM using aubio tempo (fallback method).

    Returns:
        Tuple of (bpm, confidence) or None if failed
    """
    try:
        import aubio

        logger.debug("Using aubio tempo detection...")

        hop_size = config.get("aubio_hop_size", 512)
        buf_size = config.get("aubio_buf_size", 4096)

        source = aubio.source(audio_path, hop_size=hop_size)
        tempo = aubio.tempo("default", buf_size=buf_size, hop_size=hop_size)

        while True:
            samples, num_read = source()
            if num_read == 0:
                break
            tempo(samples)
            if num_read < hop_size:
                break

        detected_bpm = tempo.get_bpm()
        confidence = tempo.get_confidence()

        logger.debug(f"Aubio raw BPM: {detected_bpm:.1f}, confidence: {confidence:.2f}")

        if detected_bpm > 0:
            return (float(detected_bpm), float(confidence))
        return None

    except Exception as e:
        logger.debug(f"Aubio BPM detection failed: {e}")
        return None


def detect_bpm(audio_path: str, config: dict) -> Optional[float]:
    """
    Detect BPM from audio file using multiple methods.

    Strategy:
    1. Try aubio first (streaming, memory-efficient, works in 512MB container)
    2. If aubio confidence is very low, try essentia on short tracks only
    3. Normalize BPM to DJ-friendly range (85-175 BPM)
    4. Accept lower confidence threshold since we normalize anyway

    Args:
        audio_path: Path to audio file
        config: Analysis config dict

    Returns:
        BPM value (float, range 85-175) or None if detection failed
    """
    import os

    bpm_range = config.get("bpm_search_range", [50, 200])
    # Very lenient threshold - we trust the normalization
    confidence_threshold = config.get("confidence_threshold", 0.05)

    detected_bpm = None
    confidence = 0.0
    method = None

    # Try aubio first (streaming, memory-efficient)
    result = _detect_bpm_aubio(audio_path, config)
    if result:
        detected_bpm, confidence = result
        method = "aubio"

    # If aubio failed or very low confidence, try essentia for small files only
    # (essentia loads entire file into memory - risky for large files in 512MB container)
    if detected_bpm is None or confidence < 0.2:
        try:
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            # Only try essentia for files under 30MB to avoid OOM
            if file_size_mb < 30:
                essentia_result = _detect_bpm_essentia(audio_path)
                if essentia_result:
                    essentia_bpm, essentia_conf = essentia_result
                    # Use essentia if it has better confidence
                    if essentia_conf > confidence:
                        detected_bpm, confidence = essentia_bpm, essentia_conf
                        method = "essentia"
        except Exception as e:
            logger.debug(f"Essentia fallback skipped: {e}")

    # No detection succeeded
    if detected_bpm is None:
        logger.warning("All BPM detection methods failed")
        return None

    # Check minimum confidence (very lenient)
    if confidence < confidence_threshold:
        logger.warning(
            f"BPM confidence {confidence:.2f} below threshold {confidence_threshold}. "
            f"Detected {detected_bpm:.1f} BPM via {method}. Rejecting."
        )
        return None

    # Normalize to DJ-friendly range (handles half/double tempo issues)
    normalized_bpm = _normalize_bpm(detected_bpm, (85, 175))

    # Final validation
    if not (bpm_range[0] <= normalized_bpm <= bpm_range[1]):
        logger.warning(
            f"Normalized BPM {normalized_bpm:.1f} outside range {bpm_range}. Rejecting."
        )
        return None

    logger.info(
        f"✅ BPM detected: {normalized_bpm:.1f} "
        f"(raw: {detected_bpm:.1f}, method: {method}, confidence: {confidence:.2f})"
    )
    return normalized_bpm
