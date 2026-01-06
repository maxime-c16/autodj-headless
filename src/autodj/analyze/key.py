"""
Key Detection using essentia or keyfinder-cli.

Per SPEC.md § 5.1:
- Uses essentia-streaming or keyfinder-cli subprocess
- Budget: ≤ 200 MiB peak memory (essentia) or ≤ 100 MiB (keyfinder)
- Single file at a time
- Output: Camelot notation (1A, 1B, ..., 12B)
"""

import logging
from typing import Optional
import subprocess

logger = logging.getLogger(__name__)

# Mapping from standard key notation to Camelot notation
# Standard: C, C#/Db, D, D#/Eb, E, F, F#/Gb, G, G#/Ab, A, A#/Bb, B
# Major: A, B, B, C#, D, D#/Eb, E, F#, G, G#/Ab, A, B (offset by 9)
# Minor: A, B, B, C#, D, D#/Eb, E, F#, G, G#/Ab, A, B (offset by 9)

STANDARD_TO_CAMELOT_MAJOR = {
    "C": "8B",
    "C#": "3B",
    "Db": "3B",
    "D": "10B",
    "D#": "5B",
    "Eb": "5B",
    "E": "12B",
    "F": "7B",
    "F#": "2B",
    "Gb": "2B",
    "G": "9B",
    "G#": "4B",
    "Ab": "4B",
    "A": "11B",
    "A#": "6B",
    "Bb": "6B",
    "B": "1B",
}

STANDARD_TO_CAMELOT_MINOR = {
    "C": "5A",
    "C#": "12A",
    "Db": "12A",
    "D": "7A",
    "D#": "2A",
    "Eb": "2A",
    "E": "9A",
    "F": "4A",
    "F#": "11A",
    "Gb": "11A",
    "G": "6A",
    "G#": "1A",
    "Ab": "1A",
    "A": "8A",
    "A#": "3A",
    "Bb": "3A",
    "B": "10A",
}


def _essentia_detect_key(audio_path: str, config: dict, max_duration: float = 30.0) -> Optional[str]:
    """
    Detect key using essentia library (memory-optimized).

    Memory-optimized: only analyzes first 30 seconds to stay within container limits.

    Args:
        audio_path: Path to audio file
        config: Config dict
        max_duration: Maximum seconds to analyze (default 30s for memory efficiency)

    Returns:
        Camelot notation or None if detection failed
    """
    try:
        import essentia.standard as es
        import numpy as np
        import os

        logger.debug("Using essentia for key detection (memory-optimized)")

        # Check file size - skip essentia for large files to avoid OOM
        file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
        if file_size_mb > 20:
            logger.debug(f"File too large ({file_size_mb:.1f}MB) - skipping essentia to avoid OOM")
            return None

        # Load audio with sample limiting
        sample_rate = 44100
        loader = es.MonoLoader(filename=audio_path, sampleRate=sample_rate)
        audio = loader()

        # Limit to max_duration to avoid OOM
        max_samples = int(max_duration * sample_rate)
        if len(audio) > max_samples:
            # Use middle portion (skip intro which might have different key)
            start_offset = min(len(audio) // 4, int(10 * sample_rate))  # Skip first 10s max
            audio = audio[start_offset:start_offset + max_samples]
            logger.debug(f"Analyzing {len(audio)/sample_rate:.1f}s sample")

        # Key detection
        key_detector = es.KeyExtractor()
        key, scale, confidence = key_detector(audio)

        logger.debug(f"Essentia result: key={key}, scale={scale}, confidence={confidence:.2f}")

        # Use the key (note) and scale (mode) directly from essentia
        note = key
        mode = scale.lower()

        # Convert to Camelot
        mapping = STANDARD_TO_CAMELOT_MAJOR if mode == "major" else STANDARD_TO_CAMELOT_MINOR
        camelot_key = mapping.get(note)

        if camelot_key:
            logger.info(f"✅ Key detected: {key} → {camelot_key} (confidence: {confidence:.2f})")
            return camelot_key
        else:
            logger.warning(f"Unknown note: {note}")
            return None

    except ImportError:
        logger.debug("Essentia not available")
        return None
    except Exception as e:
        logger.debug(f"Essentia key detection failed: {e}")
        return None


def _keyfinder_cli_detect_key(audio_path: str, config: dict) -> Optional[str]:
    """
    Detect key using keyfinder-cli subprocess.

    Args:
        audio_path: Path to audio file
        config: Config dict

    Returns:
        Camelot notation or None if detection failed
    """
    try:
        logger.debug("Using keyfinder-cli for key detection")

        # Run keyfinder-cli
        result = subprocess.run(
            ["keyfinder-cli", audio_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            logger.warning(f"keyfinder-cli failed: {result.stderr}")
            return None

        output = result.stdout.strip()
        logger.debug(f"keyfinder-cli output: {output}")

        # Parse output (format: "Key: A major, Camelot: 8B" or similar)
        # Try to extract Camelot notation if present
        if "Camelot:" in output:
            camelot_part = output.split("Camelot:")[-1].strip()
            camelot_key = camelot_part.split()[0]  # Get first token
            logger.info(f"✅ Key detected via keyfinder-cli: {camelot_key}")
            return camelot_key
        else:
            # Try to parse key notation and convert
            if "Key:" in output:
                key_part = output.split("Key:")[-1].strip().split(",")[0]
                parts = key_part.split()
                if len(parts) >= 2:
                    note, mode = parts[0], parts[1].lower()
                    mapping = (
                        STANDARD_TO_CAMELOT_MAJOR if mode == "major" else STANDARD_TO_CAMELOT_MINOR
                    )
                    camelot_key = mapping.get(note)
                    if camelot_key:
                        logger.info(f"✅ Key detected via keyfinder-cli: {key_part} → {camelot_key}")
                        return camelot_key

        logger.warning(f"Could not parse keyfinder-cli output: {output}")
        return None

    except FileNotFoundError:
        logger.warning("keyfinder-cli not found in PATH")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("keyfinder-cli timeout")
        return None
    except Exception as e:
        logger.error(f"keyfinder-cli detection failed: {e}", exc_info=True)
        return None


def detect_key(audio_path: str, config: dict) -> Optional[str]:
    """
    Detect musical key from audio file.

    Args:
        audio_path: Path to audio file
        config: Key detection config dict with:
            - method: "essentia" (default) or "keyfinder-cli"
            - window_size: Window size for analysis

    Returns:
        Key in Camelot notation (e.g., "9A", "1B") or None if detection failed
    """
    method = config.get("key_detection", {}).get("method", "essentia")

    if method == "keyfinder-cli":
        result = _keyfinder_cli_detect_key(audio_path, config)
        if result:
            return result
        # Fall back to essentia if keyfinder fails
        return _essentia_detect_key(audio_path, config)
    else:
        # Default to essentia
        result = _essentia_detect_key(audio_path, config)
        if result:
            return result
        # Fall back to keyfinder if essentia fails
        return _keyfinder_cli_detect_key(audio_path, config)
