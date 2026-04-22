#!/usr/bin/env python3
"""
EQ Preprocessing Pipeline

Applies EQ annotations to audio tracks BEFORE Liquidsoap mixing.

This is simpler than Liquidsoap DSP generation:
1. Load audio track
2. Read EQ opportunities from annotation
3. Apply filters using eq_applier
4. Save processed track
5. Liquidsoap mixes the processed tracks

Result: Bass cuts and EQ effects are baked into tracks before mixing.
"""

import logging
import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Any, Optional
import soundfile as sf
from scipy import signal

logger = logging.getLogger(__name__)


class EQPreprocessor:
    """Apply EQ opportunities to audio tracks before mixing."""
    
    def __init__(self, sample_rate: int = 44100):
        self.sr = sample_rate
        self.eq_opportunities_applied = 0
    
    def process_track(
        self,
        audio_path: str,
        eq_annotation: Dict[str, Any],
        output_path: str,
        bpm: float = 128.0,
    ) -> bool:
        """
        Apply all EQ opportunities to a track.
        
        Args:
            audio_path: Input audio file
            eq_annotation: Dict with 'eq_opportunities' list
            output_path: Where to save processed audio
            bpm: Track BPM (for bar timing calculations)
        
        Returns:
            True if successful
        """
        try:
            logger.info(f"📊 Processing: {Path(audio_path).name}")
            
            # Load audio - try soundfile first (for WAV), fallback to librosa (supports ALAC via FFmpeg)
            try:
                y, sr = sf.read(audio_path, dtype='float32')
            except Exception as e:
                logger.warning(f"  ⚠️ soundfile failed ({e}), trying librosa...")
                import librosa
                y, sr = librosa.load(audio_path, sr=self.sr, mono=True)
                
            if sr != self.sr:
                logger.warning(f"  ⚠️ Sample rate mismatch: {sr} vs {self.sr}, resampling...")
                import librosa
                y = librosa.resample(y, orig_sr=sr, target_sr=self.sr)
            
            logger.info(f"  ✅ Loaded: {len(y)} samples @ {self.sr}Hz")
            
            # Get EQ opportunities
            opportunities = eq_annotation.get('eq_opportunities', [])
            logger.info(f"  🎛️ Applying {len(opportunities)} EQ opportunities...")
            
            # Calculate timing
            beats_per_bar = 4
            seconds_per_bar = (60.0 / bpm) * beats_per_bar
            samples_per_bar = int(seconds_per_bar * self.sr)
            
            # Apply each opportunity
            for opp in opportunities:
                try:
                    opp_type = opp.get('type', 'unknown')
                    bar = opp.get('bar', 0)
                    freq = opp.get('frequency', 1000)
                    mag_db = opp.get('magnitude_db', -6)
                    duration_bars = opp.get('bars_duration', 4)
                    
                    # Calculate sample positions
                    start_sample = bar * samples_per_bar
                    end_sample = (bar + duration_bars) * samples_per_bar
                    end_sample = min(end_sample, len(y))
                    
                    # Skip if out of bounds
                    if start_sample >= len(y):
                        continue
                    
                    # Apply EQ to this section
                    y = self._apply_eq_section(
                        y,
                        opp_type,
                        freq,
                        mag_db,
                        start_sample,
                        end_sample,
                        self.sr
                    )
                    
                    self.eq_opportunities_applied += 1
                    
                except Exception as e:
                    logger.warning(f"  ⚠️ Failed to apply {opp_type} @ bar {bar}: {e}")
            
            # Normalize to prevent clipping
            max_val = np.max(np.abs(y))
            if max_val > 1.0:
                y = y / (max_val * 1.01)  # Leave 1% headroom
            
            # Save processed audio
            sf.write(output_path, y, self.sr, subtype='PCM_16')
            logger.info(f"  ✅ Saved: {output_path} ({len(y)} samples)")
            
            return True
            
        except Exception as e:
            logger.error(f"  ❌ Processing failed: {e}")
            return False
    
    def _apply_eq_section(
        self,
        audio: np.ndarray,
        eq_type: str,
        frequency: float,
        magnitude_db: float,
        start_sample: int,
        end_sample: int,
        sr: int,
    ) -> np.ndarray:
        """
        Apply EQ to a section of audio with envelope.
        
        Args:
            audio: Input audio array
            eq_type: 'bass_cut', 'high_cut', 'mid_swap', etc.
            frequency: Center frequency (Hz)
            magnitude_db: Cut depth (-dB)
            start_sample: Start position
            end_sample: End position
            sr: Sample rate
        
        Returns:
            Audio with EQ applied
        """
        # Generate envelope (attack/hold/release)
        duration = end_sample - start_sample
        attack_samples = int(0.01 * sr)  # 10ms attack
        release_samples = int(0.05 * sr)  # 50ms release
        hold_samples = duration - attack_samples - release_samples
        
        # Create envelope curve
        envelope = np.ones(duration)
        
        # Attack: 0 → -mag (ramp in)
        if attack_samples > 0:
            envelope[:attack_samples] = np.linspace(0, 1.0, attack_samples)
        
        # Release: -mag → 0 (ramp out)
        if release_samples > 0:
            envelope[-release_samples:] = np.linspace(1.0, 0, release_samples)
        
        # Normalize magnitude (convert dB to linear)
        magnitude_linear = 10 ** (magnitude_db / 20.0)  # -8dB → 0.398
        envelope = 1.0 - (envelope * (1.0 - magnitude_linear))
        
        # Apply filter based on type
        if eq_type == 'bass_cut':
            # High-pass filter (remove bass)
            filtered = self._apply_highpass(
                audio[start_sample:end_sample],
                frequency,
                sr
            )
        elif eq_type == 'high_cut':
            # Low-pass filter (remove highs)
            filtered = self._apply_lowpass(
                audio[start_sample:end_sample],
                frequency,
                sr
            )
        elif eq_type == 'mid_swap':
            # Peaking filter (cut mids)
            filtered = self._apply_peaking(
                audio[start_sample:end_sample],
                frequency,
                magnitude_db,
                sr,
                q=2.0
            )
        else:
            # Default: low-pass
            filtered = self._apply_lowpass(
                audio[start_sample:end_sample],
                frequency,
                sr
            )
        
        # Apply envelope
        # Fix: Expand envelope to 2D for stereo/multi-channel compatibility
        envelope_2d = envelope[:, np.newaxis] if len(envelope.shape) == 1 else envelope
        filtered = filtered * envelope_2d
        
        # Blend with original (envelope-based crossfade)
        original = audio[start_sample:end_sample].copy()
        blended = (filtered * envelope_2d) + (original * (1.0 - envelope_2d))
        
        # Copy back to audio
        audio[start_sample:end_sample] = blended
        
        return audio
    
    def _apply_highpass(self, audio: np.ndarray, freq: float, sr: int) -> np.ndarray:
        """High-pass filter using Butterworth."""
        nyq = sr / 2.0
        normal_freq = freq / nyq
        
        # Clamp to valid range
        normal_freq = max(0.001, min(0.999, normal_freq))
        
        try:
            b, a = signal.butter(4, normal_freq, btype='high')
            return signal.filtfilt(b, a, audio)
        except Exception as e:
            logger.warning(f"HPF failed: {e}, returning original")
            return audio
    
    def _apply_lowpass(self, audio: np.ndarray, freq: float, sr: int) -> np.ndarray:
        """Low-pass filter using Butterworth."""
        nyq = sr / 2.0
        normal_freq = freq / nyq
        
        # Clamp to valid range
        normal_freq = max(0.001, min(0.999, normal_freq))
        
        try:
            b, a = signal.butter(4, normal_freq, btype='low')
            return signal.filtfilt(b, a, audio)
        except Exception as e:
            logger.warning(f"LPF failed: {e}, returning original")
            return audio
    
    def _apply_peaking(
        self,
        audio: np.ndarray,
        freq: float,
        gain_db: float,
        sr: int,
        q: float = 2.0
    ) -> np.ndarray:
        """
        Peaking (parametric) filter.
        
        Creates a bell curve at the specified frequency.
        Useful for surgical cuts (bass cuts, mid reduction).
        """
        nyq = sr / 2.0
        w0 = 2 * np.pi * freq / sr
        
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2 * q)
        
        # Convert gain from dB to linear
        gain_linear = 10 ** (gain_db / 40.0)  # Use /40 for peaking EQ
        
        # Peaking filter coefficients
        b0 = 1 + alpha * gain_linear
        b1 = -2 * cos_w0
        b2 = 1 - alpha * gain_linear
        a0 = 1 + alpha / gain_linear
        a1 = -2 * cos_w0
        a2 = 1 - alpha / gain_linear
        
        # Normalize
        b = np.array([b0/a0, b1/a0, b2/a0])
        a = np.array([1.0, a1/a0, a2/a0])
        
        try:
            return signal.filtfilt(b, a, audio)
        except Exception as e:
            logger.warning(f"Peaking filter failed: {e}, returning original")
            return audio


def preprocess_transitions(
    transitions_json_path: str,
    output_dir: Path,
    eq_enabled: bool = True,
) -> bool:
    """
    Pre-process all tracks in a transitions file with their EQ annotations.
    
    Args:
        transitions_json_path: Path to transitions.json
        output_dir: Where to save processed audio files
        eq_enabled: Whether to apply EQ
    
    Returns:
        True if successful
    """
    try:
        print(f"\n🎛️🎛️🎛️ EQ PREPROCESSOR CALLED! eq_enabled={eq_enabled}")
        print(f"    Loading: {transitions_json_path}")
        with open(transitions_json_path) as f:
            plan = json.load(f)
        print(f"    ✅ Loaded JSON successfully, {len(plan.get('transitions', []))} transitions")
        
        transitions = plan.get('transitions', [])
        
        if not eq_enabled or not transitions:
            logger.info("EQ preprocessing skipped (disabled or no transitions)")
            return True
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        preprocessor = EQPreprocessor(sample_rate=44100)
        
        logger.info(f"🎛️ EQ Pre-processing {len(transitions)} tracks...")
        
        for idx, trans in enumerate(transitions, 1):
            file_path = trans.get('file_path', '')
            track_id = trans.get('track_id', f'track_{idx}')
            
            if not file_path or not Path(file_path).exists():
                logger.warning(f"  ⚠️ Track {idx} not found: {file_path}")
                continue
            
            if 'eq_annotation' not in trans:
                logger.info(f"  ⏭️ Track {idx}: No EQ annotation, using original")
                # Copy original
                output_path = output_dir / f"{track_id}_eq.wav"
                import shutil
                shutil.copy(file_path, output_path)
                trans['file_path'] = str(output_path)
                continue
            
            # Process with EQ
            output_path = output_dir / f"{track_id}_eq.wav"
            annotation = trans['eq_annotation']
            bpm = trans.get('bpm', 128.0)
            
            success = preprocessor.process_track(
                file_path,
                annotation,
                str(output_path),
                bpm
            )
            
            if success:
                # Update transitions to point to processed file
                trans['file_path'] = str(output_path)
                logger.info(f"  ✅ Track {idx}: {preprocessor.eq_opportunities_applied} EQ applied")
            else:
                logger.warning(f"  ❌ Track {idx}: Processing failed, using original")
        
        # Save updated transitions
        with open(transitions_json_path, 'w') as f:
            json.dump(plan, f, indent=2)
        
        logger.info(f"✅ EQ pre-processing complete! {preprocessor.eq_opportunities_applied} EQ opportunities applied")
        return True
        
    except Exception as e:
        logger.error(f"EQ preprocessing failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    # Example usage
    transitions_file = '/home/mcauchy/autodj-headless/data/playlists/transitions-20260217-185711.json'
    output_dir = Path('/tmp/eq_processed')
    
    success = preprocess_transitions(transitions_file, output_dir, eq_enabled=True)
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")
