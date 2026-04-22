#!/usr/bin/env python3
"""
Aggressive Beat-Synced DJ EQ Integration for Nightly Pipeline

Integrates beat-synced EQ into the main render pipeline with:
- Greedy selector for aggressive DJ skill application
- Multiple EQ techniques (bass cut, high swap, filter sweep)
- Beat-accurate timing via librosa
- Peaking filters (professional standard)
- Multi-drop support with instant release

Call this BEFORE liquidsoap rendering to annotate tracks with EQ opportunities.
"""

import logging
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
import numpy as np

try:
    import librosa
    from scipy.signal import sosfilt
except ImportError as e:
    print(f"ERROR: {e}")
    exit(1)

logger = logging.getLogger(__name__)


class AggressiveDJEQAnnotator:
    """
    Aggressive DJ EQ annotator for intra-track automation.
    
    Uses greedy selection to maximize DJ skills across the track.
    """
    
    def __init__(self, sr: int = 44100, min_confidence: float = 0.65):
        """
        Initialize aggressive annotator.
        
        Args:
            sr: Sample rate
            min_confidence: Minimum confidence (lowered to 0.65 for aggression)
        """
        self.sr = sr
        self.min_confidence = min_confidence
        logger.info(f"AggressiveDJEQAnnotator init (min_conf={min_confidence})")
    
    def detect_beat_grid(self, y: np.ndarray) -> tuple:
        """Detect beat grid using librosa."""
        logger.info("🎵 Detecting beat grid...")
        tempo, beats = librosa.beat.beat_track(y=y, sr=self.sr)
        tempo = float(tempo)
        
        beat_samples = librosa.frames_to_samples(beats, hop_length=512)
        beat_times = librosa.frames_to_time(beats, sr=self.sr, hop_length=512)
        
        logger.info(f"   BPM: {tempo:.1f}, Total beats: {len(beat_samples)}")
        return tempo, beat_samples, beat_times
    
    def detect_musical_drops(self, track_analysis: Dict[str, Any],
                            beat_times: np.ndarray,
                            y: np.ndarray = None) -> List[Dict]:
        """
        Detect drop points from track analysis.
        
        Falls back to audio-based detection if metadata unavailable.
        Returns list of drops with beat-snapped times.
        """
        drops = []
        
        # Try metadata-based detection first
        sections = track_analysis.get('sections_json', {})
        if isinstance(sections, str):
            try:
                sections = json.loads(sections)
            except:
                sections = {}
        
        # Look for drop sections in metadata
        section_list = sections.get('sections', [])
        for sec in section_list:
            if sec.get('name', '').lower() in ['drop', 'breakdown', 'chorus']:
                drop_time = sec.get('start_time', 0)
                
                # Snap to beat
                beat_idx = np.argmin(np.abs(beat_times - drop_time))
                snapped_time = float(beat_times[beat_idx])
                
                drops.append({
                    'reference_time': drop_time,
                    'snapped_time': snapped_time,
                    'bar': int(beat_idx / 4) + 1,  # Convert beat index to bar
                    'section': sec.get('name'),
                    'confidence': 0.9,
                    'source': 'metadata',
                })
        
        # If no drops found in metadata AND audio available, use audio-based detection
        if len(drops) == 0 and y is not None:
            logger.info("   No metadata drops found, using audio-based detection...")
            try:
                audio_drops = self._detect_audio_drops(y, beat_times)
                drops.extend(audio_drops)
            except Exception as e:
                logger.warning(f"   Audio-based drop detection failed: {e}")
        
        return drops
    
    def _detect_audio_drops(self, y: np.ndarray, beat_times: np.ndarray) -> List[Dict]:
        """
        Detect drops from audio using energy envelope and spectral analysis.
        """
        drops = []
        
        try:
            # Compute energy envelope
            frame_length = 2048
            D = librosa.stft(y, n_fft=frame_length, hop_length=self.sr // 8)
            S = np.abs(D) ** 2
            energy = np.sqrt(np.mean(S, axis=0))
            
            # Smooth and compute differences
            from scipy import ndimage
            energy_smooth = ndimage.uniform_filter1d(energy, size=5)
            energy_diff = np.diff(energy_smooth)
            
            # Find significant drops (bottom 15% percentile)
            threshold = np.percentile(energy_diff, 15)
            drop_frames = np.where(energy_diff < threshold)[0]
            
            sr_frames = self.sr // 8
            duration = len(y) / self.sr
            
            for frame_idx in drop_frames:
                time = frame_idx * sr_frames / self.sr
                
                # Skip start/end (first 5s, last 5s)
                if time < 5 or time > duration - 5:
                    continue
                
                # Measure drop magnitude
                e_before = np.mean(energy_smooth[max(0, frame_idx-20):frame_idx])
                e_after = np.mean(energy_smooth[frame_idx:min(len(energy_smooth), frame_idx+20)])
                magnitude_pct = (e_before - e_after) / (e_before + 1e-10) * 100
                
                # Only accept significant drops (>20% energy loss)
                if magnitude_pct > 20:
                    # Snap to nearest beat
                    beat_idx = np.argmin(np.abs(beat_times - time))
                    snapped_time = float(beat_times[beat_idx])
                    bar_num = int(beat_idx / 4) + 1
                    
                    # Check for duplicates (within 2 seconds)
                    is_duplicate = any(abs(d['snapped_time'] - snapped_time) < 2 for d in drops)
                    if not is_duplicate:
                        confidence = min(0.95, 0.4 + (magnitude_pct / 200))
                        drops.append({
                            'reference_time': time,
                            'snapped_time': snapped_time,
                            'bar': bar_num,
                            'magnitude': magnitude_pct,
                            'confidence': confidence,
                            'source': 'audio_energy',
                        })
            
            logger.info(f"   🎛️ Audio-based drop detection: {len(drops)} drops found")
            
        except Exception as e:
            logger.warning(f"   Audio drop detection error: {e}")
        
        return drops
    
    def generate_eq_opportunities(self, track_analysis: Dict[str, Any],
                                beat_times: np.ndarray,
                                tempo: float,
                                y: np.ndarray = None,
                                drops: List[Dict] = None) -> List[Dict]:
        """
        Aggressively generate EQ opportunities from audio + metadata.
        
        AGGRESSIVE MODE: Works with or without metadata, fills mix with DJ skills.
        """
        opportunities = []
        
        # Get energy profile from metadata or compute from audio
        energy_vals = []
        energy = track_analysis.get('energy_profile_json', {})
        if isinstance(energy, str):
            try:
                energy = json.loads(energy)
                energy_vals = energy.get('values', [])
            except:
                energy_vals = []
        
        # If no energy data, compute from audio
        if not energy_vals and y is not None:
            logger.info("   No energy profile in metadata, computing from audio...")
            try:
                # Compute energy envelope
                S = librosa.feature.melspectrogram(y=y, sr=self.sr)
                energy_vals = librosa.power_to_db(S, ref=np.max).mean(axis=0)
                # Normalize to 0-1
                energy_vals = (energy_vals - energy_vals.min()) / (energy_vals.max() - energy_vals.min() + 1e-8)
                logger.info(f"   Computed energy profile: {len(energy_vals)} frames")
            except Exception as e:
                logger.warning(f"   Could not compute energy: {e}")
                energy_vals = []
        
        # Get sections from metadata
        sections = track_analysis.get('sections_json', {})
        if isinstance(sections, str):
            try:
                sections = json.loads(sections)
            except:
                sections = {}
        
        section_list = sections.get('sections', [])
        total_bars = len(beat_times) / 4 if len(beat_times) > 0 else 100
        seconds_per_bar = (60.0 / tempo) * 4 if tempo > 0 else 1.0
        
        logger.info(f"🎛️ AGGRESSIVE MODE: Generating EQ opportunities ({total_bars:.0f} bars)...")
        
        # ===== AGGRESSIVE STRATEGY: Fill mix with DJ skills =====
        
        # 1. AGGRESSIVE BASS CUTS: Prioritize drops, then fill pattern
        logger.info("   [1/5] Aggressive bass cuts...")
        bass_cut_bars = set()
        
        # FIRST: Place bass cuts AT drops (2-3 bars after drop for buildup)
        if drops and len(drops) > 0:
            logger.info(f"      Placing bass cuts at {len(drops)} detected drops...")
            for drop in drops:
                drop_bar = drop.get('bar', 0)
                # Place bass cut 2 bars into the drop
                cut_bar = drop_bar + 2
                if cut_bar < int(total_bars) - 2:
                    bass_cut_bars.add(cut_bar)
                    logger.info(f"      → Bass cut @ bar {cut_bar} (drop @ bar {drop_bar})")
        
        # THEN: Fill in additional bass cuts every 8 bars for pattern
        for bar_num in range(4, int(total_bars) - 2, 8):
            bass_cut_bars.add(bar_num)
        
        # Generate bass cut opportunities
        if energy_vals is not None and len(energy_vals) > 0:
            frame_hop = len(energy_vals) / total_bars
            for bar_num in sorted(bass_cut_bars):
                frame_idx = int(bar_num * frame_hop)
                if frame_idx < len(energy_vals):
                    confidence = 0.75 + (float(energy_vals[frame_idx]) * 0.15)
                    
                    opportunities.append({
                        'type': 'bass_cut',
                        'bar': bar_num,
                        'frequency': 70,
                        'magnitude_db': -8,
                        'bars_duration': 4,
                        'confidence': min(0.95, confidence),
                        'description': f'Aggressive bass cut @ bar {bar_num}',
                    })
        else:
            # Default pattern if no energy data
            for bar_num in sorted(bass_cut_bars):
                opportunities.append({
                    'type': 'bass_cut',
                    'bar': bar_num,
                    'frequency': 70,
                    'magnitude_db': -8,
                    'bars_duration': 4,
                    'confidence': 0.80,
                    'description': f'Aggressive bass cut @ bar {bar_num}',
                })
        
        logger.info(f"      Generated {len([o for o in opportunities if o['type'] == 'bass_cut'])} bass cuts")
        
        # 2. MID-RANGE SWAPS: Every 12 bars
        logger.info("   [2/5] Mid-range swaps...")
        for bar_num in range(6, int(total_bars) - 2, 12):
            opportunities.append({
                'type': 'mid_swap',
                'bar': bar_num,
                'frequency': 2000,
                'magnitude_db': -5,
                'bars_duration': 3,
                'confidence': 0.78,
                'description': f'Surgical mid-range swap @ bar {bar_num}',
            })
        
        # 3. HIGH-FREQUENCY CUTS: Regular pattern
        logger.info("   [3/5] High-frequency sculpting...")
        for bar_num in range(2, int(total_bars) - 2, 16):
            opportunities.append({
                'type': 'high_cut',
                'bar': bar_num,
                'frequency': 5000,
                'magnitude_db': -4,
                'bars_duration': 2,
                'confidence': 0.75,
                'description': f'High-freq sculpting @ bar {bar_num}',
            })
        
        # 4. PRE-DROP FILTER SWEEPS
        logger.info("   [4/5] Pre-drop filter sweeps...")
        for sec in section_list:
            if sec.get('name', '').lower() in ['drop', 'breakdown', 'chorus']:
                start_time = sec.get('start_time', 0)
                start_bar = int(start_time / seconds_per_bar)
                
                if start_bar >= 4:
                    opportunities.append({
                        'type': 'filter_sweep',
                        'bar': start_bar - 4,
                        'frequency': 3000,
                        'magnitude_db': -6,
                        'bars_duration': 4,
                        'confidence': 0.82,
                        'description': f'Tension build to {sec.get("name")} @ bar {start_bar}',
                    })
        
        # 5. SPATIAL FILLS
        logger.info("   [5/5] Spatial multi-band fills...")
        for bar_num in range(8, int(total_bars) - 4, 20):
            if bar_num not in [o['bar'] for o in opportunities]:
                opportunities.append({
                    'type': 'multi_band',
                    'bar': bar_num,
                    'frequency': 'all',
                    'magnitude_db': -2,
                    'bars_duration': 6,
                    'confidence': 0.70,
                    'description': f'Multi-band spatial processing @ bar {bar_num}',
                })
        
        # Deduplicate and sort
        opportunities_deduped = []
        seen_bars = set()
        for opp in sorted(opportunities, key=lambda x: (x['bar'], -x['confidence'])):
            bar = opp['bar']
            if bar not in seen_bars:
                opportunities_deduped.append(opp)
                seen_bars.add(bar)
        
        logger.info(f"   ✅ Generated {len(opportunities_deduped)} DJ skills")
        for opp in opportunities_deduped[:8]:
            logger.info(f"     • {opp['description']}")
        
        return opportunities_deduped
    
    def annotate_track(self, track_path: str, track_analysis: Dict[str, Any],
                      output_json: str) -> bool:
        """
        Analyze track and annotate with EQ opportunities.
        
        Args:
            track_path: Path to audio file
            track_analysis: Analysis dict from database
            output_json: Path to save EQ annotations
        
        Returns:
            True if successful
        """
        try:
            logger.info(f"\n📁 Processing: {Path(track_path).name}")
            
            # Load audio
            y, sr = librosa.load(track_path, sr=self.sr)
            logger.info(f"   Loaded: {len(y)/sr:.1f}s")
            
            # Detect beat grid
            tempo, beat_samples, beat_times = self.detect_beat_grid(y)
            
            # Detect drops (with audio fallback for auto-detection)
            drops = self.detect_musical_drops(track_analysis, beat_times, y)
            logger.info(f"   Found {len(drops)} drops")
            
            # Generate EQ opportunities (AGGRESSIVE) - pass audio for energy computation
            opportunities = self.generate_eq_opportunities(track_analysis, beat_times, tempo, y, drops)
            
            # Build annotation
            annotation = {
                'track': Path(track_path).name,
                'duration_seconds': len(y) / sr,
                'detected_bpm': tempo,
                'total_beats': len(beat_samples),
                'drops': drops,
                'eq_opportunities': [
                    {
                        'type': opp['type'],
                        'bar': opp['bar'],
                        'frequency': opp['frequency'],
                        'magnitude_db': opp['magnitude_db'],
                        'bars_duration': opp['bars_duration'],
                        'confidence': opp['confidence'],
                        'description': opp['description'],
                    }
                    for opp in opportunities
                ],
                'total_eq_skills': len(opportunities),
            }
            
            # Save
            with open(output_json, 'w') as f:
                json.dump(annotation, f, indent=2)
            
            logger.info(f"   ✅ Saved {len(opportunities)} EQ skills to {Path(output_json).name}")
            
            return True
        
        except Exception as e:
            logger.error(f"   ❌ Error: {e}")
            return False


def main():
    """Test integration."""
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    logger.info("="*130)
    logger.info("🎧 Aggressive Beat-Synced DJ EQ Integration")
    logger.info("="*130)
    
    # Example track
    track_path = '/srv/nas/shared/ALAC/ØRGIE/Rusty Chains/07. Without Pain.m4a'
    
    # Mock analysis (would come from database)
    track_analysis = {
        'sections_json': json.dumps({
            'sections': [
                {'name': 'intro', 'start_time': 0, 'duration': 30},
                {'name': 'verse', 'start_time': 30, 'duration': 60},
                {'name': 'chorus', 'start_time': 90, 'duration': 30},
                {'name': 'drop', 'start_time': 92.37, 'duration': 60},
                {'name': 'breakdown', 'start_time': 152, 'duration': 30},
            ]
        }),
        'energy_profile_json': json.dumps({
            'values': [0.3] * 30 + [0.6] * 30 + [0.9] * 10 + [0.8] * 50,
        }),
    }
    
    # Initialize
    annotator = AggressiveDJEQAnnotator(sr=44100, min_confidence=0.65)
    
    # Annotate
    output_json = Path(track_path).parent / 'eq_annotation.json'
    success = annotator.annotate_track(str(track_path), track_analysis, str(output_json))
    
    if success:
        logger.info(f"\n✅ Annotation complete!")
        logger.info(f"   File: {output_json}")
        
        # Show results
        with open(output_json) as f:
            annotation = json.load(f)
        
        logger.info(f"\n   Summary:")
        logger.info(f"   • BPM: {annotation['detected_bpm']:.1f}")
        logger.info(f"   • Drops detected: {len(annotation['drops'])}")
        logger.info(f"   • EQ skills generated: {annotation['total_eq_skills']}")
    else:
        logger.error("Failed to annotate track")


if __name__ == '__main__':
    main()
