#!/usr/bin/env python3
"""
Traktor S3 MK2 Standard DJ EQ System

Uses ACTUAL Traktor/Pioneer DJ mixer frequencies:
- LOW (Bass): 70 Hz  (cuts kick drum)
- MID: 1000 Hz (cuts vocals/drums)
- HIGH (Treble): 13000 Hz (cuts cymbals/presence)

This matches standard DJ 3-band EQ used on Pioneer DJM, Rane, A&H, etc.
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


class TraktorDJEqualizer:
    """DJ EQ using Traktor/Pioneer standard frequencies."""
    
    def __init__(self, sr=44100):
        self.sr = sr
    
    def design_peaking_biquad(self, freq, Q, gain_db):
        """RBJ cookbook peaking filter."""
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
    
    def create_envelope(self, total_samples, drop_sample, bpm=128,
                       pre_bars=2, hold_bars=4,
                       attack_ms=50, release_ms=200):
        """Smooth automation envelope."""
        bar_samples = int((60.0 / bpm) * 4 * self.sr)
        
        cut_start = max(0, drop_sample - pre_bars * bar_samples)
        cut_end = min(total_samples, drop_sample + hold_bars * bar_samples)
        
        attack_samples = int(attack_ms * self.sr / 1000)
        release_samples = int(release_ms * self.sr / 1000)
        
        envelope = np.ones(total_samples, dtype=np.float32)
        
        # Attack
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
    
    def apply_eq(self, audio, bands, envelope):
        """Apply multi-band EQ with envelope."""
        output = audio.copy()
        
        for band in bands:
            sos = self.design_peaking_biquad(band['freq'], band['Q'], band['gain_db'])
            filtered = sosfilt(sos, output)
            output = output * envelope + filtered * (1 - envelope)
        
        return output


def main():
    logger.info("="*120)
    logger.info("🎧 TRAKTOR DJ EQ SYSTEM - Standard Pioneer/Traktor Frequencies")
    logger.info("="*120 + "\n")
    
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    logger.info(f"📁 Loading: {Path(track_path).name}")
    y, sr = librosa.load(track_path, sr=44100)
    logger.info(f"✓ Loaded: {len(y)/sr:.2f}s\n")
    
    drops = [
        {'sample': int(46.21 * 44100), 'time': '0:46'},
        {'sample': int(92.37 * 44100), 'time': '1:32'},
        {'sample': int(127.12 * 44100), 'time': '2:07'},
        {'sample': int(197.06 * 44100), 'time': '3:17'},
    ]
    
    # 5 presets using Traktor standard frequencies (70Hz low, 1000Hz mid, 13kHz high)
    # CORRECTED: hold_bars = bars AFTER drop (pre_bars=2 is fixed)
    # Total effect = 2 (before) + hold_bars (after) = total bars
    presets = {
        'traktor_light': {
            'description': 'Light bass cut (2 bars total effect)',
            'bands': [
                {'freq': 70, 'Q': 1.5, 'gain_db': -3},
            ],
            'hold_bars': 0,  # 2 before + 0 after = 2 bars total
        },
        'traktor_moderate': {
            'description': 'Moderate bass cut (4 bars total effect)',
            'bands': [
                {'freq': 70, 'Q': 2.0, 'gain_db': -6},
                {'freq': 100, 'Q': 1.5, 'gain_db': -4},
            ],
            'hold_bars': 2,  # 2 before + 2 after = 4 bars total
        },
        'traktor_aggressive': {
            'description': 'Aggressive bass cut (4 bars total effect)',
            'bands': [
                {'freq': 70, 'Q': 2.5, 'gain_db': -9},
                {'freq': 100, 'Q': 2.0, 'gain_db': -7},
                {'freq': 150, 'Q': 1.5, 'gain_db': -4},
            ],
            'hold_bars': 2,  # 2 before + 2 after = 4 bars total
        },
        'traktor_extreme': {
            'description': 'Extreme bass cut (6 bars total effect)',
            'bands': [
                {'freq': 50, 'Q': 3.0, 'gain_db': -12},
                {'freq': 70, 'Q': 3.0, 'gain_db': -12},
                {'freq': 100, 'Q': 2.5, 'gain_db': -10},
                {'freq': 200, 'Q': 1.5, 'gain_db': -5},
            ],
            'hold_bars': 4,  # 2 before + 4 after = 6 bars total
        },
        'traktor_full_bass_kill': {
            'description': 'FULL bass kill (6 bars maximum as requested)',
            'bands': [
                {'freq': 50, 'Q': 3.5, 'gain_db': -15},
                {'freq': 70, 'Q': 3.5, 'gain_db': -15},
                {'freq': 100, 'Q': 3.0, 'gain_db': -12},
                {'freq': 150, 'Q': 2.5, 'gain_db': -10},
                {'freq': 1000, 'Q': 2.0, 'gain_db': -4},
            ],
            'hold_bars': 4,  # 2 before + 4 after = 6 bars total
        },
    }
    
    eq = TraktorDJEqualizer(sr=44100)
    
    for preset_name, settings in presets.items():
        logger.info(f"🎛️ {preset_name.upper()}")
        logger.info(f"   {settings['description']}")
        total_bars = 2 + settings['hold_bars']
        logger.info(f"   Total effect: {total_bars} bars (2 before + {settings['hold_bars']} after drop)\n")
        
        output = y.copy()
        
        for drop in drops:
            drop_sample = drop['sample']
            
            envelope = eq.create_envelope(
                len(y), drop_sample, bpm=128,
                pre_bars=2, 
                hold_bars=settings['hold_bars'],  # Use preset-specific hold_bars!
                attack_ms=50, 
                release_ms=200
            )
            
            output = eq.apply_eq(output, settings['bands'], envelope)
            
            logger.info(f"   ✓ Drop @ {drop['time']}")
        
        # Normalize
        max_val = np.abs(output).max()
        if max_val > 1.0:
            output = output / max_val
        
        # Save
        output_path = output_dir / f'without_pain_{preset_name}.wav'
        sf.write(output_path, output, sr)
        file_size_mb = output_path.stat().st_size / (1024*1024)
        
        logger.info(f"   📁 {output_path.name} ({file_size_mb:.1f}MB)\n")
    
    logger.info("="*120)
    logger.info("✅ ALL 5 TRAKTOR-STANDARD PRESETS GENERATED")
    logger.info("="*120 + "\n")


if __name__ == '__main__':
    main()
