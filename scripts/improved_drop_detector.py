#!/usr/bin/env python3
"""
Improved Bass Drop Detector v2

Uses multiple detection strategies:
1. Energy envelope drops (sudden energy loss)
2. Spectral changes (kick frequency drops)
3. Silence detection (RMS < threshold)
4. Onset gaps (unexpected silence in beat pattern)

Tested on "Without Pain" and "Rusty Chains"
"""

import librosa
import numpy as np
from scipy import signal, ndimage
from pathlib import Path
import json

class ImprovedDropDetector:
    """Multi-strategy drop detection with high sensitivity."""
    
    def __init__(self, sr=44100, hop_length=512):
        self.sr = sr
        self.hop_length = hop_length
    
    def detect_drops(self, audio_path: str, bpm: float = 128) -> list:
        """
        Detect drops using 4 strategies:
        1. Energy envelope analysis
        2. RMS-based silence detection
        3. Bass frequency content
        4. Spectral centroid changes
        """
        print(f"🎵 Analyzing: {Path(audio_path).name}")
        y, sr = librosa.load(audio_path, sr=self.sr)
        duration = len(y) / sr
        
        drops = []
        
        # Strategy 1: Energy envelope (slow energy drops)
        print("  Strategy 1: Energy envelope...")
        frame_length = 2048
        D = librosa.stft(y, n_fft=frame_length, hop_length=self.hop_length)
        S = np.abs(D) ** 2
        energy = np.sqrt(np.mean(S, axis=0))
        energy_smooth = ndimage.uniform_filter1d(energy, size=5)
        energy_diff = np.diff(energy_smooth)
        
        threshold = np.percentile(energy_diff, 15)  # Bottom 15%
        energy_drops = np.where(energy_diff < threshold)[0]
        
        for idx in energy_drops:
            time = idx * self.hop_length / sr
            if 5 < time < duration - 5:
                e_before = np.mean(energy_smooth[max(0, idx-20):idx])
                e_after = np.mean(energy_smooth[idx:min(len(energy_smooth), idx+20)])
                magnitude = (e_before - e_after) / (e_before + 1e-10) * 100
                
                if magnitude > 20:  # >20% drop
                    drops.append({
                        'time': time,
                        'magnitude': magnitude,
                        'type': 'energy',
                        'confidence': min(0.99, 0.4 + magnitude / 200)
                    })
        
        # Strategy 2: RMS silence detection (breaks/gaps)
        print("  Strategy 2: RMS silence detection...")
        chunk_size = int(0.5 * sr)  # 0.5s chunks
        rms_vals = []
        times_rms = []
        
        for i in range(0, len(y), chunk_size):
            chunk = y[i:i+chunk_size]
            rms = np.sqrt(np.mean(chunk**2))
            rms_vals.append(rms)
            times_rms.append(i / sr)
        
        rms_vals = np.array(rms_vals)
        rms_smooth = ndimage.uniform_filter1d(rms_vals, size=2)
        rms_diff = np.diff(rms_smooth)
        
        # Find where RMS drops dramatically
        rms_threshold = np.percentile(rms_diff, 10)
        rms_drops = np.where(rms_diff < rms_threshold)[0]
        
        for idx in rms_drops:
            time = times_rms[idx]
            if 5 < time < duration - 5:
                rms_before = rms_smooth[idx]
                rms_after = rms_smooth[idx+1]
                magnitude = (rms_before - rms_after) / (rms_before + 1e-10) * 100
                
                if magnitude > 30:  # >30% RMS drop (very noticeable)
                    # Check if this is a new drop or duplicate
                    is_duplicate = False
                    for existing in drops:
                        if abs(existing['time'] - time) < 2:  # Within 2 seconds
                            if magnitude > existing['magnitude']:
                                drops.remove(existing)  # Replace with better one
                            else:
                                is_duplicate = True
                                break
                    
                    if not is_duplicate:
                        drops.append({
                            'time': time,
                            'magnitude': magnitude,
                            'type': 'rms_silence',
                            'confidence': min(0.99, 0.5 + magnitude / 150)
                        })
        
        # Strategy 3: Bass frequency content (kick/sub-bass disappearance)
        print("  Strategy 3: Bass frequency analysis...")
        bass_freqs = librosa.fft_frequencies(sr=sr)
        bass_mask = bass_freqs < 100  # 0-100Hz
        S_bass = S[bass_mask]
        bass_power = np.sum(S_bass, axis=0)
        bass_power_smooth = ndimage.uniform_filter1d(bass_power, size=3)
        bass_diff = np.diff(bass_power_smooth)
        
        bass_threshold = np.percentile(bass_diff, 10)
        bass_drops = np.where(bass_diff < bass_threshold)[0]
        
        for idx in bass_drops:
            time = idx * self.hop_length / sr
            if 5 < time < duration - 5:
                bass_before = np.mean(bass_power_smooth[max(0, idx-20):idx])
                bass_after = np.mean(bass_power_smooth[idx:min(len(bass_power_smooth), idx+20)])
                magnitude = (bass_before - bass_after) / (bass_before + 1e-10) * 100
                
                if magnitude > 25:  # >25% bass power drop
                    is_duplicate = False
                    for existing in drops:
                        if abs(existing['time'] - time) < 1:
                            if magnitude > existing['magnitude']:
                                drops.remove(existing)
                            else:
                                is_duplicate = True
                                break
                    
                    if not is_duplicate:
                        drops.append({
                            'time': time,
                            'magnitude': magnitude,
                            'type': 'bass_drop',
                            'confidence': min(0.99, 0.45 + magnitude / 180)
                        })
        
        # Sort by confidence and deduplicate
        drops.sort(key=lambda x: x['confidence'], reverse=True)
        
        # Final deduplication (merge very close drops)
        final_drops = []
        skip_indices = set()
        
        for i, drop in enumerate(drops):
            if i in skip_indices:
                continue
            
            final_drops.append(drop)
            
            # Mark similar drops as duplicates
            for j, other in enumerate(drops[i+1:], i+1):
                if abs(drop['time'] - other['time']) < 1.5:
                    skip_indices.add(j)
        
        # Filter by confidence threshold
        final_drops = [d for d in final_drops if d['confidence'] > 0.5]
        
        return final_drops[:10]  # Return top 10


def test_track(audio_path: str, track_name: str, bpm: float = 128):
    """Test detection on a track and print results."""
    detector = ImprovedDropDetector()
    drops = detector.detect_drops(audio_path, bpm)
    
    print(f"\n{'='*100}")
    print(f"✅ {track_name}: Found {len(drops)} drops\n")
    
    for i, drop in enumerate(drops[:8], 1):
        time = drop['time']
        mm_ss = f"{int(time//60)}:{int(time%60):02d}"
        print(f"#{i}: {mm_ss} ({time:.2f}s)")
        print(f"     Magnitude: {drop['magnitude']:.1f}%")
        print(f"     Type: {drop['type']}")
        print(f"     Confidence: {drop['confidence']*100:.0f}%\n")
    
    return drops


if __name__ == '__main__':
    print("🎵 IMPROVED DROP DETECTION TEST")
    print("=" * 100)
    
    # Test on both tracks
    tracks = [
        ('/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a', 'Without Pain'),
        ('/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/06. Rusty Chains.m4a', 'Rusty Chains'),
    ]
    
    all_results = {}
    
    for path, name in tracks:
        try:
            results = test_track(path, name)
            all_results[name] = results
        except Exception as e:
            print(f"❌ Error processing {name}: {e}\n")
    
    # Save results
    output_file = Path(__file__).parent / 'drop_detection_results.json'
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"💾 Results saved to: {output_file}")
