#!/usr/bin/env python3
"""
Beat-Synced DJ EQ System with 1/2/3/4 Bar Release Options

Uses librosa beat detection for ACCURATE beat grid alignment.
Generates 4 versions with fade-in (2 bars before) + different release times:
- traktor_1bar_after.wav    (bass cut 2 bars before + 1 bar into drop)
- traktor_2bars_after.wav   (bass cut 2 bars before + 2 bars into drop)
- traktor_3bars_after.wav   (bass cut 2 bars before + 3 bars into drop)
- traktor_4bars_after.wav   (bass cut 2 bars before + 4 bars into drop)
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


class BeatSyncedDJEqualizer:
    """DJ EQ with beat-accurate synchronization."""
    
    def __init__(self, sr=44100):
        self.sr = sr
    
    def detect_beat_grid(self, y, sr=44100):
        """Detect beat grid using librosa with high accuracy."""
        logger.info("🎵 Detecting beat grid...")
        
        # Estimate tempo and beat frames
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr)
        
        # tempo is returned as a scalar float
        tempo = float(tempo)
        
        # Convert beat frames to samples
        beat_samples = librosa.frames_to_samples(beats, hop_length=512)
        beat_times = librosa.frames_to_time(beats, sr=sr, hop_length=512)
        
        logger.info(f"   Detected BPM: {tempo:.1f}")
        logger.info(f"   Total beats: {len(beat_samples)}")
        logger.info(f"   First 5 beats at: {beat_times[:5]}")
        
        return tempo, beat_samples, beat_times
    
    def find_bar_boundaries(self, beat_samples, beat_times, reference_drop_time, num_beats_per_bar=4):
        """
        Find bar boundaries relative to a drop point.
        Returns sample indices for: drop point and bar boundaries.
        """
        # Find the beat closest to the drop time
        drop_beat_idx = np.argmin(np.abs(beat_times - reference_drop_time))
        
        # Snap to nearest beat
        drop_sample = beat_samples[drop_beat_idx]
        drop_beat_time = beat_times[drop_beat_idx]
        
        logger.info(f"   Drop time: {reference_drop_time:.2f}s → Snapped to beat @ {drop_beat_time:.2f}s (sample {drop_sample})")
        
        # Calculate bar boundaries (1 bar = 4 beats by default)
        bars = {}
        for bar_num in range(-3, 6):  # -3 to +5 bars around drop
            beat_idx = drop_beat_idx + (bar_num * num_beats_per_bar)
            if 0 <= beat_idx < len(beat_samples):
                bars[bar_num] = {
                    'sample': beat_samples[beat_idx],
                    'time': beat_times[beat_idx],
                }
        
        return drop_sample, drop_beat_time, bars
    
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
    
    def create_envelope(self, total_samples, cut_start_sample, cut_end_sample,
                       attack_ms=50, release_ms=0):
        """
        Create precise envelope between exact sample boundaries.
        
        Args:
            total_samples: Total audio length
            cut_start_sample: Sample where bass cut STARTS (fade in)
            cut_end_sample: Sample where bass cut ENDS (instant cutoff)
            attack_ms: Fade-in duration
            release_ms: Fade-out duration (set to 0 for instant release)
        """
        attack_samples = int(attack_ms * self.sr / 1000)
        release_samples = int(release_ms * self.sr / 1000)
        
        envelope = np.ones(total_samples, dtype=np.float32)
        
        # Attack (fade in the cut from 0 to 1)
        attack_start = max(0, cut_start_sample - attack_samples)
        if cut_start_sample > attack_start:
            for i in range(attack_start, cut_start_sample):
                envelope[i] = (i - attack_start) / (cut_start_sample - attack_start)
        
        # Hold (full cut, envelope = 0 means full EQ effect)
        envelope[cut_start_sample:cut_end_sample] = 0.0
        
        # Release (optional fade out - if release_ms > 0)
        if release_samples > 0:
            release_end = min(total_samples, cut_end_sample + release_samples)
            if release_end > cut_end_sample:
                for i in range(cut_end_sample, release_end):
                    envelope[i] = (release_end - i) / (release_end - cut_end_sample)
        # else: instant cutoff (envelope jumps from 0 to 1)
        
        return envelope
    
    def apply_eq(self, audio, bands, envelope):
        """Apply multi-band EQ with envelope."""
        output = audio.copy()
        
        for band in bands:
            sos = self.design_peaking_biquad(band['freq'], band['Q'], band['gain_db'])
            filtered = sosfilt(sos, output)
            # envelope=1 means normal, envelope=0 means full EQ cut
            output = output * envelope + filtered * (1 - envelope)
        
        return output


def main():
    logger.info("="*130)
    logger.info("🎧 BEAT-SYNCED DJ EQ SYSTEM - 1/2/3/4 Bar Release Options")
    logger.info("="*130 + "\n")
    
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    output_dir = Path(__file__).parent / 'output'
    output_dir.mkdir(exist_ok=True)
    
    logger.info(f"📁 Loading: {Path(track_path).name}")
    y, sr = librosa.load(track_path, sr=44100)
    logger.info(f"✓ Loaded: {len(y)/sr:.2f}s\n")
    
    # Detect beat grid
    eq = BeatSyncedDJEqualizer(sr=44100)
    tempo, beat_samples, beat_times = eq.detect_beat_grid(y, sr)
    logger.info("")
    
    # Test drop point (1:32 = 92.37s)
    reference_drop_time = 92.37
    drop_sample, drop_beat_time, bars = eq.find_bar_boundaries(beat_samples, beat_times, reference_drop_time)
    logger.info("")
    
    # Aggressive EQ preset (like the one that worked well)
    eq_bands = [
        {'freq': 70, 'Q': 2.5, 'gain_db': -9},
        {'freq': 100, 'Q': 2.0, 'gain_db': -7},
        {'freq': 150, 'Q': 1.5, 'gain_db': -4},
    ]
    
    # Generate 4 versions with 1, 2, 3, 4 bars after drop
    versions = [
        {'name': 'traktor_1bar_after', 'bars_after': 1},
        {'name': 'traktor_2bars_after', 'bars_after': 2},
        {'name': 'traktor_3bars_after', 'bars_after': 3},
        {'name': 'traktor_4bars_after', 'bars_after': 4},
    ]
    
    for version in versions:
        bars_after = version['bars_after']
        logger.info(f"🎛️ Generating: {version['name'].upper()}")
        
        # Cut starts 2 bars BEFORE drop
        cut_start = bars[-2]['sample']
        
        # Cut ends N bars AFTER drop
        cut_end = bars[bars_after]['sample']
        
        cut_start_time = bars[-2]['time']
        cut_end_time = bars[bars_after]['time']
        
        logger.info(f"   Cut: {cut_start_time:.2f}s → {cut_end_time:.2f}s")
        logger.info(f"   Envelope: 2 bars before + {bars_after} bar(s) after drop")
        
        # Create envelope
        envelope = eq.create_envelope(len(y), cut_start, cut_end, attack_ms=50, release_ms=0)
        
        # Apply EQ
        output = eq.apply_eq(y, eq_bands, envelope)
        
        # Normalize
        max_val = np.abs(output).max()
        if max_val > 1.0:
            output = output / max_val
        
        # Save
        output_path = output_dir / f'without_pain_{version["name"]}.wav'
        sf.write(output_path, output, sr)
        file_size_mb = output_path.stat().st_size / (1024*1024)
        
        logger.info(f"   📁 {output_path.name} ({file_size_mb:.1f}MB)\n")
    
    logger.info("="*130)
    logger.info("✅ ALL 4 BEAT-SYNCED VERSIONS GENERATED (1/2/3/4 bars after drop)")
    logger.info("="*130 + "\n")


if __name__ == '__main__':
    main()
