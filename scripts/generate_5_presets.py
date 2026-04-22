#!/usr/bin/env python3
"""
Bass Drop EQ - 5 Different Preset Versions

Creates 5 variations with different filter settings:
1. LIGHT:    60Hz, 4th-order   (subtle, barely noticeable)
2. MODERATE: 50Hz, 8th-order   (noticeable, musical)
3. AGGRESSIVE: 40Hz, 12th-order (VERY dramatic)
4. EXTREME:  30Hz, 14th-order  (maximum kick removal)
5. SURGICAL: 20Hz, 16th-order  (ultra-precision, remove EVERYTHING)
"""

import sys
import json
import numpy as np
from pathlib import Path
import logging
from typing import List, Dict

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

try:
    import librosa
    import soundfile as sf
    from scipy.signal import butter, sosfilt
    import scipy.ndimage
except ImportError as e:
    logger.error(f"Missing library: {e}")
    sys.exit(1)


class PresetEQProcessor:
    """Generate 5 different EQ preset versions."""
    
    PRESETS = {
        'light': {
            'cutoff_hz': 60,
            'order': 4,
            'description': 'Subtle bass cut - barely noticeable'
        },
        'moderate': {
            'cutoff_hz': 50,
            'order': 8,
            'description': 'Noticeable but musical bass reduction'
        },
        'aggressive': {
            'cutoff_hz': 40,
            'order': 12,
            'description': 'VERY dramatic bass removal'
        },
        'extreme': {
            'cutoff_hz': 30,
            'order': 14,
            'description': 'Maximum kick/sub-bass elimination'
        },
        'surgical': {
            'cutoff_hz': 20,
            'order': 16,
            'description': 'Ultra-precision, remove almost everything below'
        }
    }
    
    def __init__(self, sr=44100, hop_length=512):
        self.sr = sr
        self.hop_length = hop_length
    
    def create_smooth_envelope(self, total_samples, drop_sample, bpm, 
                              pre_cut_bars=2, extend_bars=4, 
                              attack_ms=50, release_ms=100):
        """Create smooth automation envelope for bass cut."""
        bar_samples = int((60.0 / bpm) * 4 * self.sr)
        
        # Key points
        cut_start = drop_sample - pre_cut_bars * bar_samples
        cut_end = drop_sample + extend_bars * bar_samples
        
        attack_samples = int(attack_ms * self.sr / 1000)
        release_samples = int(release_ms * self.sr / 1000)
        
        envelope = np.ones(total_samples, dtype=np.float32)
        
        # Fade in (attack)
        if attack_samples > 0:
            attack_start = max(0, cut_start - attack_samples)
            for i in range(attack_start, cut_start):
                if cut_start != attack_start:
                    envelope[i] = 1.0 - (cut_start - i) / (cut_start - attack_start)
        
        # Hold (full cut)
        envelope[cut_start:cut_end] = 0.0
        
        # Release
        release_end = min(total_samples, cut_end + release_samples)
        for i in range(cut_end, release_end):
            if release_end != cut_end:
                envelope[i] = (i - cut_end) / (release_end - cut_end)
        
        return envelope
    
    def apply_bass_cut(self, audio, envelope, cutoff_hz, order):
        """Apply high-pass filter with envelope modulation."""
        nyquist = self.sr / 2
        normalized_cutoff = np.clip(cutoff_hz / nyquist, 0.001, 0.999)
        
        sos = butter(order, normalized_cutoff, btype='high', output='sos')
        filtered = sosfilt(sos, audio)
        
        # Envelope-based blending
        output = audio * envelope + filtered * (1 - envelope)
        
        return output
    
    def process_track(self, audio_path, drops, bpm=128):
        """Apply EQ cuts for all 4 drops and generate 5 preset versions."""
        logger.info(f"📁 Loading: {Path(audio_path).name}")
        y, sr = librosa.load(audio_path, sr=self.sr)
        
        results = {}
        
        for preset_name, settings in self.PRESETS.items():
            logger.info(f"\n🎛️ Processing preset: {preset_name.upper()}")
            logger.info(f"   {settings['description']}")
            logger.info(f"   Settings: {settings['cutoff_hz']}Hz, {settings['order']}th-order")
            
            output = y.copy()
            
            # Apply all 4 drops
            for i, drop in enumerate(drops, 1):
                drop_sample = drop['sample_snapped']
                
                envelope = self.create_smooth_envelope(
                    len(y), drop_sample, bpm,
                    pre_cut_bars=2,
                    extend_bars=4,
                    attack_ms=50,
                    release_ms=100
                )
                
                output = self.apply_bass_cut(
                    output,
                    envelope,
                    settings['cutoff_hz'],
                    settings['order']
                )
                
                logger.info(f"   ✓ Drop {i}/4 processed")
            
            # Normalize
            max_val = np.abs(output).max()
            if max_val > 1.0:
                output = output / max_val
            
            # Calculate bass reduction
            bass_before = np.abs(y).mean()
            bass_after = np.abs(output).mean()
            reduction_db = 20 * np.log10((bass_after + 1e-10) / (bass_before + 1e-10))
            
            logger.info(f"   Bass reduction: {reduction_db:.2f} dB\n")
            
            results[preset_name] = {
                'audio': output,
                'settings': settings,
                'bass_reduction_db': reduction_db
            }
        
        return results


def main():
    """Generate all 5 preset versions."""
    logger.info("="*100)
    logger.info("🎵 BASS DROP EQ - 5 PRESET VERSIONS")
    logger.info("="*100 + "\n")
    
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    # Use the 4 detected drops
    drops = [
        {'sample_snapped': int(46.21 * 44100), 'time': 46.21},      # 0:46
        {'sample_snapped': int(92.37 * 44100), 'time': 92.37},      # 1:32
        {'sample_snapped': int(127.12 * 44100), 'time': 127.12},    # 2:07
        {'sample_snapped': int(197.06 * 44100), 'time': 197.06},    # 3:17
    ]
    
    processor = PresetEQProcessor()
    results = processor.process_track(track_path, drops)
    
    logger.info("\n" + "="*100)
    logger.info("💾 SAVING ALL 5 VERSIONS")
    logger.info("="*100 + "\n")
    
    # Save each version
    summary = {}
    for preset_name, result in results.items():
        output_path = output_dir / f'without_pain_{preset_name}.wav'
        sf.write(output_path, result['audio'], 44100)
        
        file_size_mb = output_path.stat().st_size / (1024*1024)
        
        logger.info(f"✅ {preset_name.upper():12} → {output_path.name}")
        logger.info(f"   Cutoff: {result['settings']['cutoff_hz']}Hz, Order: {result['settings']['order']}")
        logger.info(f"   Bass reduction: {result['bass_reduction_db']:.2f} dB")
        logger.info(f"   Size: {file_size_mb:.2f} MB\n")
        
        summary[preset_name] = {
            'cutoff_hz': result['settings']['cutoff_hz'],
            'order': result['settings']['order'],
            'description': result['settings']['description'],
            'bass_reduction_db': result['bass_reduction_db'],
            'file': output_path.name,
            'file_size_mb': file_size_mb
        }
    
    # Save summary
    summary_path = output_dir / 'presets_summary.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info("="*100)
    logger.info("✅ ALL 5 VERSIONS COMPLETE!")
    logger.info("="*100 + "\n")
    
    print("\n📊 COMPARISON TABLE:\n")
    print(f"{'Preset':<15} {'Cutoff':<10} {'Order':<8} {'Bass Cut':<12} {'Audibility':<20}")
    print("-" * 80)
    
    for preset_name in ['light', 'moderate', 'aggressive', 'extreme', 'surgical']:
        s = summary[preset_name]
        print(f"{preset_name:15} {s['cutoff_hz']:>3}Hz      {s['order']:>2}        "
              f"{s['bass_reduction_db']:>6.2f} dB   {s['description']:<20}")
    
    print(f"\n💾 All files saved to: {output_dir}")
    print(f"📄 Summary: {summary_path}\n")


if __name__ == '__main__':
    main()
