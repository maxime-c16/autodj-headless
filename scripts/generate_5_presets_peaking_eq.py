#!/usr/bin/env python3
"""
CORRECTED Bass Drop EQ - Using Peaking EQ (Like DJ Controller)

The issue: High-pass filter removes everything BELOW cutoff
The solution: Peaking EQ targets SPECIFIC frequency bands (like DJ knobs)

DJ 3-Band EQ Frequency Ranges:
- LOW (Bass): 20-250 Hz    → Targets kick drum (60-100 Hz)
- MID: 300 Hz - 4 kHz       → Vocals, snare
- HIGH (Treble): 2-20 kHz   → Cymbals, presence

For bass cut, we use a PEAKING filter at the kick's fundamental frequency.
Typical kick frequencies:
- Deep kick: 40-60 Hz
- Mid kick: 60-100 Hz  
- Punchy kick: 100-150 Hz
"""

import sys
import numpy as np
from pathlib import Path
import logging
from scipy.signal import butter, sosfilt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import librosa
    import soundfile as sf
except ImportError as e:
    logger.error(f"Missing: {e}")
    sys.exit(1)


class PeakingEQProcessor:
    """Use peaking EQ filters like DJ controllers."""
    
    def __init__(self, sr=44100):
        self.sr = sr
    
    def design_peaking_filter(self, center_freq, Q, gain_db, sr):
        """
        Design a peaking filter using biquad coefficients.
        This is how DJ EQs actually work.
        
        center_freq: frequency to boost/cut
        Q: width (higher Q = narrower)
        gain_db: positive = boost, negative = cut
        """
        w0 = 2 * np.pi * center_freq / sr
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2 * Q)
        
        A = 10 ** (gain_db / 40)
        
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
        
        # Normalize
        b = [b0/a0, b1/a0, b2/a0]
        a = [1, a1/a0, a2/a0]
        
        return b, a
    
    def apply_peaking_eq(self, audio, center_freq, Q, gain_db, envelope):
        """Apply peaking EQ with envelope modulation."""
        b, a = self.design_peaking_filter(center_freq, Q, gain_db, self.sr)
        
        # Apply filter
        filtered = sosfilt(np.array([[b[0], b[1], b[2], 1, a[1], a[2]]]), audio)
        
        # Envelope blending
        output = audio * envelope + (filtered - audio) * (1 - envelope)
        
        return output
    
    def create_smooth_envelope(self, total_samples, drop_sample, bpm=128,
                              pre_cut_bars=2, extend_bars=4,
                              attack_ms=50, release_ms=200):
        """Create smooth automation envelope."""
        bar_samples = int((60.0 / bpm) * 4 * self.sr)
        
        cut_start = drop_sample - pre_cut_bars * bar_samples
        cut_end = drop_sample + extend_bars * bar_samples
        
        attack_samples = int(attack_ms * self.sr / 1000)
        release_samples = int(release_ms * self.sr / 1000)
        
        envelope = np.ones(total_samples, dtype=np.float32)
        
        # Fade in
        if attack_samples > 0:
            attack_start = max(0, cut_start - attack_samples)
            for i in range(attack_start, cut_start):
                if cut_start != attack_start:
                    envelope[i] = 1.0 - (cut_start - i) / (cut_start - attack_start)
        
        # Hold (full effect)
        envelope[cut_start:cut_end] = 0.0
        
        # Release
        release_end = min(total_samples, cut_end + release_samples)
        for i in range(cut_end, release_end):
            if release_end != cut_end:
                envelope[i] = (i - cut_end) / (release_end - cut_end)
        
        return envelope


def create_5_presets(audio_path, drops, output_dir):
    """Create 5 versions with different peaking EQ settings."""
    
    logger.info("="*100)
    logger.info("🎛️ PEAKING EQ BASS CUT - 5 PRESETS")
    logger.info("="*100 + "\n")
    
    y, sr = librosa.load(audio_path, sr=44100)
    processor = PeakingEQProcessor(sr=44100)
    
    # 5 different EQ settings
    presets = {
        'light': {
            'center_freqs': [60],      # Target kick fundamental
            'Q': 2.0,                   # Wider Q = broader effect
            'gain_db': -3,              # Subtle cut
            'description': 'Light -3dB cut @ 60Hz'
        },
        'moderate': {
            'center_freqs': [80],
            'Q': 2.5,
            'gain_db': -6,
            'description': 'Moderate -6dB cut @ 80Hz'
        },
        'aggressive': {
            'center_freqs': [80, 120],  # Multi-band cut
            'Q': 2.0,
            'gain_db': -8,
            'description': 'Aggressive -8dB @ 80Hz & 120Hz'
        },
        'extreme': {
            'center_freqs': [60, 100, 150],  # Triple-band
            'Q': 1.5,
            'gain_db': -10,
            'description': 'Extreme -10dB @ 60/100/150Hz'
        },
        'surgical': {
            'center_freqs': [50, 80, 120, 180],  # Quad-band precision
            'Q': 3.0,
            'gain_db': -12,
            'description': 'Surgical -12dB across 4 bands'
        }
    }
    
    results = {}
    
    for preset_name, settings in presets.items():
        logger.info(f"\n🎛️ Processing: {preset_name.upper()}")
        logger.info(f"   {settings['description']}")
        
        output = y.copy()
        
        # Apply to all 4 drops
        for drop_num, drop in enumerate(drops, 1):
            drop_sample = drop['sample_snapped']
            
            # Create envelope
            envelope = processor.create_smooth_envelope(
                len(y), drop_sample, bpm=128,
                pre_cut_bars=2, extend_bars=4,
                attack_ms=50, release_ms=200
            )
            
            # Apply peaking EQ at each center frequency
            for center_freq in settings['center_freqs']:
                output = processor.apply_peaking_eq(
                    output,
                    center_freq=center_freq,
                    Q=settings['Q'],
                    gain_db=settings['gain_db'],
                    envelope=envelope
                )
            
            logger.info(f"   ✓ Drop {drop_num}/4 @ {drop['time']:.2f}s")
        
        # Normalize
        max_val = np.abs(output).max()
        if max_val > 1.0:
            output = output / max_val
            logger.info(f"   ⚠️ Normalized (peak: {max_val:.2f})")
        
        # Save
        output_path = output_dir / f'without_pain_{preset_name}.wav'
        sf.write(output_path, output, sr)
        
        file_size_mb = output_path.stat().st_size / (1024*1024)
        logger.info(f"   📁 Saved: {output_path.name} ({file_size_mb:.2f} MB)")
        
        results[preset_name] = {
            'file': output_path.name,
            'description': settings['description'],
            'center_freqs': settings['center_freqs'],
            'Q': settings['Q'],
            'gain_db': settings['gain_db']
        }
    
    return results


def main():
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    # 4 detected drops
    drops = [
        {'sample_snapped': int(46.21 * 44100), 'time': 46.21},
        {'sample_snapped': int(92.37 * 44100), 'time': 92.37},
        {'sample_snapped': int(127.12 * 44100), 'time': 127.12},
        {'sample_snapped': int(197.06 * 44100), 'time': 197.06},
    ]
    
    results = create_5_presets(track_path, drops, output_dir)
    
    logger.info("\n" + "="*100)
    logger.info("📊 SUMMARY")
    logger.info("="*100 + "\n")
    
    print(f"{'Preset':<15} {'Frequencies':<25} {'Q':<6} {'Gain':<8} {'Description':<35}")
    print("-" * 100)
    
    for preset_name in ['light', 'moderate', 'aggressive', 'extreme', 'surgical']:
        r = results[preset_name]
        freqs = ', '.join(f"{f}Hz" for f in r['center_freqs'])
        print(f"{preset_name:15} {freqs:25} {r['Q']:<6.1f} {r['gain_db']:<8.0f} {r['description']:35}")
    
    print(f"\n✅ All files saved to: {output_dir}\n")


if __name__ == '__main__':
    main()
