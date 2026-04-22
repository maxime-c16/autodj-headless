#!/usr/bin/env python3
"""
CORRECTED Bass Drop EQ v3 - Using Manual Peaking Biquad Filter

This uses the standard audio DSP cookbook formulas for peaking EQ.
Reference: RBJ Audio EQ Cookbook
"""

import sys
import numpy as np
from pathlib import Path
import logging
from scipy.signal import sosfilt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import librosa
    import soundfile as sf
except ImportError as e:
    logger.error(f"Missing: {e}")
    sys.exit(1)


class BiquadPeakingEQ:
    """Peaking EQ using RBJ cookbook biquad formulas."""
    
    def __init__(self, sr=44100):
        self.sr = sr
    
    def design_peaking_biquad(self, center_freq, Q, gain_db):
        """
        Design peaking biquad filter using RBJ cookbook.
        gain_db: positive = boost, negative = cut
        """
        A = 10 ** (gain_db / 40)
        w0 = 2 * np.pi * center_freq / self.sr
        sin_w0 = np.sin(w0)
        cos_w0 = np.cos(w0)
        alpha = sin_w0 / (2 * Q)
        
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
        
        # Return SOS format: [b0, b1, b2, a0, a1, a2] / a0
        return np.array([[b0/a0, b1/a0, b2/a0, 1, a1/a0, a2/a0]])
    
    def create_envelope(self, total_samples, drop_sample, bpm=128,
                       pre_cut_bars=2, extend_bars=4,
                       attack_ms=50, release_ms=200):
        """Create smooth automation envelope."""
        bar_samples = int((60.0 / bpm) * 4 * self.sr)
        
        cut_start = max(0, drop_sample - pre_cut_bars * bar_samples)
        cut_end = min(total_samples, drop_sample + extend_bars * bar_samples)
        
        attack_samples = int(attack_ms * self.sr / 1000)
        release_samples = int(release_ms * self.sr / 1000)
        
        envelope = np.ones(total_samples, dtype=np.float32)
        
        # Fade in
        if attack_samples > 0:
            attack_start = max(0, cut_start - attack_samples)
            if cut_start > attack_start:
                for i in range(attack_start, cut_start):
                    envelope[i] = 1.0 - (cut_start - i) / (cut_start - attack_start)
        
        # Hold
        envelope[cut_start:cut_end] = 0.0
        
        # Release
        release_end = min(total_samples, cut_end + release_samples)
        if release_end > cut_end:
            for i in range(cut_end, release_end):
                envelope[i] = (i - cut_end) / (release_end - cut_end)
        
        return envelope
    
    def apply_peaking_cut(self, audio, center_freq, Q, gain_db, envelope):
        """Apply peaking EQ cut with envelope modulation."""
        sos = self.design_peaking_biquad(center_freq, Q, gain_db)
        
        # Apply filter
        filtered = sosfilt(sos, audio)
        
        # Blend original and filtered based on envelope
        # envelope=1.0 → original (no cut)
        # envelope=0.0 → filtered (full cut effect)
        output = audio * envelope + filtered * (1 - envelope)
        
        return output


def main():
    logger.info("="*100)
    logger.info("🎛️ PEAKING EQ BASS CUT - 5 PRESETS (DJ CONTROLLER STYLE)")
    logger.info("="*100 + "\n")
    
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    logger.info(f"📁 Loading: {Path(track_path).name}")
    y, sr = librosa.load(track_path, sr=44100)
    logger.info(f"✓ Loaded: {len(y)/sr:.2f}s\n")
    
    # 4 detected drops
    drops = [
        {'sample_snapped': int(46.21 * 44100), 'time': 46.21, 'label': '0:46'},
        {'sample_snapped': int(92.37 * 44100), 'time': 92.37, 'label': '1:32'},
        {'sample_snapped': int(127.12 * 44100), 'time': 127.12, 'label': '2:07'},
        {'sample_snapped': int(197.06 * 44100), 'time': 197.06, 'label': '3:17'},
    ]
    
    processor = BiquadPeakingEQ(sr=44100)
    
    # 5 presets
    presets = {
        'light': {
            'freqs': [80],
            'Q': 1.0,
            'gain_db': -3,
            'description': 'Light: -3dB @ 80Hz (Q=1.0)'
        },
        'moderate': {
            'freqs': [80],
            'Q': 2.0,
            'gain_db': -6,
            'description': 'Moderate: -6dB @ 80Hz (Q=2.0)'
        },
        'aggressive': {
            'freqs': [60, 100],
            'Q': 2.0,
            'gain_db': -6,
            'description': 'Aggressive: -6dB @ 60Hz & 100Hz'
        },
        'extreme': {
            'freqs': [50, 80, 120],
            'Q': 2.5,
            'gain_db': -8,
            'description': 'Extreme: -8dB @ 50/80/120Hz'
        },
        'surgical': {
            'freqs': [40, 60, 85, 120, 180],
            'Q': 3.0,
            'gain_db': -10,
            'description': 'Surgical: -10dB @ 5-band precision'
        }
    }
    
    for preset_name, settings in presets.items():
        logger.info(f"🎛️ {preset_name.upper()}: {settings['description']}")
        
        output = y.copy()
        
        # Apply to all 4 drops
        for drop in drops:
            drop_sample = drop['sample_snapped']
            envelope = processor.create_envelope(len(y), drop_sample)
            
            # Apply peaking cut at each frequency
            for freq in settings['freqs']:
                output = processor.apply_peaking_cut(
                    output,
                    center_freq=freq,
                    Q=settings['Q'],
                    gain_db=settings['gain_db'],
                    envelope=envelope
                )
            
            logger.info(f"   ✓ Drop @ {drop['label']}")
        
        # Normalize
        max_val = np.abs(output).max()
        if max_val > 1.0:
            output = output / max_val
        
        # Save
        output_path = output_dir / f'without_pain_{preset_name}.wav'
        sf.write(output_path, output, sr)
        file_size_mb = output_path.stat().st_size / (1024*1024)
        
        logger.info(f"   📁 {output_path.name}\n")
    
    logger.info("="*100)
    logger.info("✅ ALL 5 PRESETS GENERATED - READY TO LISTEN!")
    logger.info("="*100 + "\n")


if __name__ == '__main__':
    main()
