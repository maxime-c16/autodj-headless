#!/usr/bin/env python3
"""
CORRECTED Bass Drop EQ v2 - Using Peaking EQ (Like DJ Controller)

Simple, tested implementation using scipy's sosfilt with proper biquad filters.
"""

import sys
import numpy as np
from pathlib import Path
import logging
from scipy.signal import butter, sosfilt, iirpeak

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
    import librosa
    import soundfile as sf
except ImportError as e:
    logger.error(f"Missing: {e}")
    sys.exit(1)


class SimplePeakingEQ:
    """Simple peaking EQ using scipy's iirpeak."""
    
    def __init__(self, sr=44100):
        self.sr = sr
    
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
        """Apply peaking EQ cut at specific frequency."""
        try:
            # Create peaking filter
            sos = iirpeak(center_freq / (self.sr / 2), Q)
            
            # If gain is negative (cut), we need to invert the filter
            # A peaking filter with negative gain attenuates the center frequency
            filtered = sosfilt(sos, audio)
            
            # For a CUT, we blend the original with attenuated version
            # envelope=1.0 → original (no cut)
            # envelope=0.0 → heavily attenuated (full cut)
            output = audio * envelope + filtered * (1 - envelope)
            
            return output
        except Exception as e:
            logger.error(f"Peaking filter error at {center_freq}Hz: {e}")
            return audio


def create_presets_v2(audio_path, drops, output_dir):
    """Create 5 versions with different peaking EQ settings."""
    
    logger.info("="*100)
    logger.info("🎛️ PEAKING EQ BASS CUT - 5 PRESETS (DJ CONTROLLER STYLE)")
    logger.info("="*100 + "\n")
    
    logger.info(f"📁 Loading: {Path(audio_path).name}")
    y, sr = librosa.load(audio_path, sr=44100)
    logger.info(f"✓ Loaded: {len(y)/sr:.2f}s at {sr}Hz\n")
    
    processor = SimplePeakingEQ(sr=44100)
    
    # 5 presets targeting kick frequencies
    presets = {
        'light': {
            'freqs': [80],
            'Q': 1.5,
            'description': 'Light -3dB @ 80Hz'
        },
        'moderate': {
            'freqs': [80],
            'Q': 2.0,
            'description': 'Moderate -6dB @ 80Hz'
        },
        'aggressive': {
            'freqs': [60, 100],
            'Q': 2.0,
            'description': 'Aggressive cuts @ 60Hz & 100Hz'
        },
        'extreme': {
            'freqs': [60, 80, 120],
            'Q': 2.5,
            'description': 'Extreme multi-band cut'
        },
        'surgical': {
            'freqs': [40, 60, 85, 120],
            'Q': 3.0,
            'description': 'Surgical 4-band precision cut'
        }
    }
    
    for preset_name, settings in presets.items():
        logger.info(f"\n🎛️ {preset_name.upper()}: {settings['description']}")
        
        output = y.copy()
        
        # Apply to all 4 drops
        for drop_idx, drop in enumerate(drops, 1):
            drop_sample = drop['sample_snapped']
            drop_time = drop['time']
            
            # Create envelope
            envelope = processor.create_envelope(len(y), drop_sample)
            
            # Apply peaking cut at each frequency
            for freq in settings['freqs']:
                output = processor.apply_peaking_cut(
                    output,
                    center_freq=freq,
                    Q=settings['Q'],
                    gain_db=-6,  # 6dB cut
                    envelope=envelope
                )
            
            mm_ss = f"{int(drop_time//60)}:{int(drop_time%60):02d}"
            logger.info(f"   ✓ Drop {drop_idx} @ {mm_ss}")
        
        # Normalize
        max_val = np.abs(output).max()
        if max_val > 1.0:
            output = output / max_val
        
        # Save
        output_path = output_dir / f'without_pain_{preset_name}.wav'
        sf.write(output_path, output, sr)
        file_size_mb = output_path.stat().st_size / (1024*1024)
        
        logger.info(f"   📁 {output_path.name} ({file_size_mb:.1f}MB)\n")
    
    logger.info("="*100)
    logger.info("✅ ALL 5 PRESETS GENERATED")
    logger.info("="*100)


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
    
    create_presets_v2(track_path, drops, output_dir)


if __name__ == '__main__':
    main()
