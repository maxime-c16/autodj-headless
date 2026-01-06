"""
BPM Detection using aubio.

Per SPEC.md § 5.1:
- Uses aubio streaming mode
- Budget: ≤ 150 MiB peak memory
- Single file at a time
"""

import logging
from typing import Optional
import aubio

logger = logging.getLogger(__name__)


def detect_bpm(audio_path: str, config: dict) -> Optional[float]:
    """
    Detect BPM from audio file using aubio onset detection + tempogram.

    Args:
        audio_path: Path to audio file
        config: Analysis config dict with:
            - aubio_hop_size: Frame hop size
            - aubio_buf_size: Buffer size
            - bpm_search_range: [min_bpm, max_bpm]
            - confidence_threshold: Minimum confidence (0-1)

    Returns:
        BPM value (float, range 50-200) or None if detection failed
    """
    try:
        # Get config parameters
        hop_size = config.get("aubio_hop_size", 512)
        buf_size = config.get("aubio_buf_size", 4096)
        bpm_range = config.get("bpm_search_range", [50, 200])
        confidence_threshold = config.get("confidence_threshold", 0.5)

        # Load audio
        logger.debug(f"Loading audio: {audio_path}")
        source = aubio.source(audio_path, hop_size=hop_size)

        # Create tempo detector
        tempo = aubio.tempo("default", buf_size=buf_size, hop_size=hop_size)

        # Process audio in frames
        frames_processed = 0
        total_frames = 0

        while True:
            samples, num_read = source()
            if num_read == 0:
                break

            tempo(samples)
            frames_processed += num_read
            total_frames += num_read

            # Stop after processing entire file (or safety limit)
            if num_read < hop_size:
                break

        # Get detected BPM
        detected_bpm = tempo.get_bpm()

        logger.debug(f"Detected BPM: {detected_bpm:.1f} (confidence: {tempo.get_confidence():.2f})")

        # Validate BPM is within configured range
        if not (bpm_range[0] <= detected_bpm <= bpm_range[1]):
            logger.warning(
                f"Detected BPM {detected_bpm:.1f} outside range {bpm_range}. Rejecting."
            )
            return None

        # Check confidence threshold
        confidence = tempo.get_confidence()
        if confidence < confidence_threshold:
            logger.warning(
                f"BPM detection confidence {confidence:.2f} below threshold {confidence_threshold}. Rejecting."
            )
            return None

        logger.info(f"✅ BPM detected: {detected_bpm:.1f} (confidence: {confidence:.2f})")
        return detected_bpm

    except Exception as e:
        logger.error(f"BPM detection failed for {audio_path}: {e}", exc_info=True)
        return None
