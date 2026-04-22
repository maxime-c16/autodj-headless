#!/usr/bin/env python3
"""
Professional Beat-Synced DJ EQ Module

Integrates into autodj pipeline with:
- Beat-accurate timing via librosa
- Peaking EQ filters (professional Traktor standard)
- Instant release (no ramp)
- Multi-drop support
- Preset system

Replace old eq_pass technique with pro peaking filters.
"""

import logging
import numpy as np
from typing import Tuple, Dict, List, Optional
from dataclasses import dataclass
from pathlib import Path
from scipy.signal import sosfilt

logger = logging.getLogger(__name__)

try:
    import librosa
except ImportError:
    logger.error("librosa required. pip install librosa")


@dataclass
class DropPoint:
    """Single drop point with beat-synced boundaries."""
    reference_time: float  # User-specified time (will be snapped to beat)
    snapped_time: float   # Actual beat-snapped time
    snapped_sample: int   # Sample position after snapping
    bar_boundaries: Dict  # Bar-aligned sample positions


@dataclass
class DJEQPreset:
    """Professional DJ EQ preset definition."""
    name: str
    description: str
    bands: List[Dict]  # List of {freq, Q, gain_db}
    bars_after_drop: int  # How many bars after drop to hold the cut


class PeakingFilterBank:
    """Professional peaking EQ filter design (RBJ cookbook)."""
    
    def __init__(self, sr: int = 44100):
        self.sr = sr
    
    def design_peaking(self, freq: float, Q: float, gain_db: float) -> np.ndarray:
        """
        Design RBJ peaking filter (professional DJ standard).
        
        Args:
            freq: Center frequency in Hz
            Q: Quality factor
            gain_db: Gain in dB (negative for cut)
        
        Returns:
            SOS (second-order sections) array for scipy.signal.sosfilt
        """
        A = 10 ** (gain_db / 40)
        w0 = 2 * np.pi * freq / self.sr
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2 * Q)
        
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
        
        return np.array([[b0/a0, b1/a0, b2/a0, 1, a1/a0, a2/a0]])
    
    def apply_filters(self, audio: np.ndarray, bands: List[Dict], 
                     envelope: np.ndarray) -> np.ndarray:
        """
        Apply multi-band peaking EQ with envelope automation.
        
        Args:
            audio: Input audio signal
            bands: List of band dicts with freq, Q, gain_db
            envelope: Automation envelope (1=bypass, 0=full cut)
        
        Returns:
            EQ-processed audio
        """
        output = audio.copy()
        
        for band in bands:
            sos = self.design_peaking(band['freq'], band['Q'], band['gain_db'])
            filtered = sosfilt(sos, output)
            # Blend between dry (output) and wet (filtered) using envelope
            # Fix: Expand envelope to 2D for stereo/multi-channel compatibility
            envelope_2d = envelope[:, np.newaxis] if len(envelope.shape) == 1 else envelope
            output = output * envelope_2d + filtered * (1 - envelope_2d)
        
        return output


class BeatSyncedDJEQ:
    """Professional beat-synced DJ EQ automation."""
    
    def __init__(self, sr: int = 44100):
        self.sr = sr
        self.filter_bank = PeakingFilterBank(sr=sr)
    
    def detect_beat_grid(self, audio: np.ndarray) -> Tuple[float, np.ndarray, np.ndarray]:
        """
        Detect beat grid using librosa (detects actual song tempo).
        
        Returns:
            (tempo_bpm, beat_samples, beat_times)
        """
        logger.info("🎵 Detecting beat grid...")
        tempo, beats = librosa.beat.beat_track(y=audio, sr=self.sr)
        tempo = float(tempo)
        
        beat_samples = librosa.frames_to_samples(beats, hop_length=512)
        beat_times = librosa.frames_to_time(beats, sr=self.sr, hop_length=512)
        
        logger.info(f"   Detected BPM: {tempo:.1f}")
        logger.info(f"   Total beats: {len(beat_samples)}")
        
        return tempo, beat_samples, beat_times
    
    def snap_to_beat(self, reference_time: float, beat_times: np.ndarray,
                    beat_samples: np.ndarray) -> Tuple[float, int]:
        """
        Snap a reference time to the nearest beat.
        
        Returns:
            (snapped_time, snapped_sample)
        """
        beat_idx = np.argmin(np.abs(beat_times - reference_time))
        snapped_time = float(beat_times[beat_idx])
        snapped_sample = int(beat_samples[beat_idx])
        return snapped_time, snapped_sample
    
    def build_bar_grid(self, drop_beat_idx: int, beat_samples: np.ndarray,
                      beat_times: np.ndarray, num_beats_per_bar: int = 4) -> Dict:
        """Build bar boundaries from drop beat index."""
        bars = {}
        for bar_num in range(-3, 6):
            beat_idx = drop_beat_idx + (bar_num * num_beats_per_bar)
            if 0 <= beat_idx < len(beat_samples):
                bars[bar_num] = {
                    'sample': int(beat_samples[beat_idx]),
                    'time': float(beat_times[beat_idx]),
                }
        return bars
    
    def create_instant_envelope(self, total_samples: int, cut_start: int,
                               cut_end: int, attack_ms: int = 50) -> np.ndarray:
        """
        Create envelope with fade-in and INSTANT release.
        
        Args:
            total_samples: Total audio length
            cut_start: Sample where cut starts (fade in)
            cut_end: Sample where cut ends (INSTANT cutoff, no ramp)
            attack_ms: Fade-in duration
        
        Returns:
            Envelope array (1=bypass, 0=full cut)
        """
        attack_samples = int(attack_ms * self.sr / 1000)
        envelope = np.ones(total_samples, dtype=np.float32)
        
        # Attack fade-in
        attack_start = max(0, cut_start - attack_samples)
        if cut_start > attack_start:
            for i in range(attack_start, cut_start):
                envelope[i] = (i - attack_start) / (cut_start - attack_start)
        
        # Instant hold (no ramp)
        envelope[cut_start:cut_end] = 0.0
        
        return envelope
    
    def process_drop(self, audio: np.ndarray, drop_point: DropPoint,
                    preset: DJEQPreset) -> np.ndarray:
        """
        Apply DJ EQ to a single drop with beat-synced automation.
        
        Args:
            audio: Full track audio
            drop_point: DropPoint with beat-synced boundaries
            preset: DJEQPreset with EQ bands and timing
        
        Returns:
            EQ-processed audio
        """
        # Build envelope
        cut_start = drop_point.bar_boundaries[-2]['sample']
        cut_end = drop_point.bar_boundaries[preset.bars_after_drop]['sample']
        
        envelope = self.create_instant_envelope(len(audio), cut_start, cut_end)
        
        # Apply peaking filters
        output = self.filter_bank.apply_filters(audio, preset.bands, envelope)
        
        return output


# Professional presets (Traktor standard 70Hz bass knob)
PRESETS = {
    'aggressive_1bar': DJEQPreset(
        name='aggressive_1bar',
        description='Aggressive bass cut, returns 1 bar after drop (instant)',
        bands=[
            {'freq': 70, 'Q': 2.5, 'gain_db': -9},
            {'freq': 100, 'Q': 2.0, 'gain_db': -7},
            {'freq': 150, 'Q': 1.5, 'gain_db': -4},
        ],
        bars_after_drop=1
    ),
    'aggressive_2bars': DJEQPreset(
        name='aggressive_2bars',
        description='Aggressive bass cut, returns 2 bars after drop (instant)',
        bands=[
            {'freq': 70, 'Q': 2.5, 'gain_db': -9},
            {'freq': 100, 'Q': 2.0, 'gain_db': -7},
            {'freq': 150, 'Q': 1.5, 'gain_db': -4},
        ],
        bars_after_drop=2
    ),
    'extreme_4bars': DJEQPreset(
        name='extreme_4bars',
        description='Extreme bass kill, returns 4 bars after drop (instant)',
        bands=[
            {'freq': 50, 'Q': 3.0, 'gain_db': -12},
            {'freq': 70, 'Q': 3.0, 'gain_db': -12},
            {'freq': 100, 'Q': 2.5, 'gain_db': -10},
            {'freq': 200, 'Q': 1.5, 'gain_db': -5},
        ],
        bars_after_drop=4
    ),
}


def main():
    """Test integration."""
    logger.info("="*130)
    logger.info("🎧 Professional Beat-Synced DJ EQ Module")
    logger.info("="*130)
    
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    logger.info(f"\n📁 Loading: {Path(track_path).name}")
    y, sr = librosa.load(track_path, sr=44100)
    logger.info(f"✓ Loaded: {len(y)/sr:.2f}s\n")
    
    # Initialize
    eq = BeatSyncedDJEQ(sr=44100)
    
    # Detect beat grid
    tempo, beat_samples, beat_times = eq.detect_beat_grid(y)
    logger.info("")
    
    # Snap drop to beat
    reference_drop = 92.37  # 1:32
    snapped_time, snapped_sample = eq.snap_to_beat(reference_drop, beat_times, beat_samples)
    drop_beat_idx = np.argmin(np.abs(beat_times - reference_drop))
    
    logger.info(f"Drop: {reference_drop}s → Snapped: {snapped_time:.2f}s\n")
    
    # Build bar grid
    bar_grid = eq.build_bar_grid(drop_beat_idx, beat_samples, beat_times)
    
    # Create drop point
    drop_point = DropPoint(
        reference_time=reference_drop,
        snapped_time=snapped_time,
        snapped_sample=snapped_sample,
        bar_boundaries=bar_grid
    )
    
    # Process with each preset
    for preset_name, preset in PRESETS.items():
        logger.info(f"🎛️ {preset_name.upper()}")
        logger.info(f"   {preset.description}")
        
        output = eq.process_drop(y, drop_point, preset)
        
        # Normalize
        max_val = np.abs(output).max()
        if max_val > 1.0:
            output = output / max_val
        
        # Save
        import soundfile as sf
        output_path = output_dir / f'without_pain_{preset_name}.wav'
        sf.write(output_path, output, sr)
        
        logger.info(f"   ✅ {output_path.name}\n")
    
    logger.info("="*130)
    logger.info("✅ Professional DJ EQ pipeline ready for integration")
    logger.info("="*130)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
