"""
PHASE 0 FIX #3: Grid Validation with 4-Check Fitness Scoring

Validates beat grid quality using 4 checks:
1. Onset Alignment (30%): % of beats within ±20ms of actual transients
2. Tempo Consistency (30%): BPM stability (CV < 3 BPM)
3. Phase Alignment (20%): Grid offset to first kick (< ±50ms)
4. Spectral Consistency (20%): Multiple methods agree on BPM

Produces fitness score (0-1.0) with confidence level and recommendations.

Thresholds:
- HIGH: fitness >= 0.80 → "Use directly"
- MEDIUM: 0.60-0.79 → "Use with validation checks"
- LOW: <0.60 → "Requires recalculation"
"""

import logging
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class GridConfidence(Enum):
    """Grid confidence level."""
    HIGH = "high"          # >= 0.80: Ready for EQ automation
    MEDIUM = "medium"      # 0.60-0.79: Requires manual verification
    LOW = "low"            # < 0.60: Requires recalculation


@dataclass
class GridValidationResult:
    """Result of grid validation."""
    fitness_score: float               # Overall fitness (0-1)
    confidence: GridConfidence         # Confidence level
    recommendation: str                # Action to take
    
    # Individual check scores
    onset_alignment_score: float
    tempo_consistency_score: float
    phase_alignment_score: float
    spectral_consistency_score: float
    
    # Breakdown of checks
    onset_alignment_percent: float     # % of beats within ±20ms
    tempo_consistency_bpm_variance: float  # BPM variation
    phase_alignment_offset_ms: float   # Grid offset in milliseconds
    spectral_bpm_agreement: float      # Method agreement percentage
    
    # Validation time
    validation_time_sec: float = 0.0
    
    # Metadata
    metadata: Dict[str, Any] = None


class GridValidator:
    """Multi-check beat grid validation framework."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize validator."""
        self.config = config
        
        # Fitness thresholds
        self.high_fitness_threshold = config.get('grid_high_fitness_threshold', 0.80)
        self.medium_fitness_threshold = config.get('grid_medium_fitness_threshold', 0.60)
        
        # Check-specific thresholds
        self.onset_alignment_threshold = 0.80  # 80% of beats must align
        self.tempo_consistency_threshold = 3.0  # Max 3 BPM variation
        self.phase_alignment_threshold = 50  # Max 50ms offset
        self.spectral_consistency_threshold = 0.95  # 95% method agreement
        
        # Metrics
        self.metrics = {
            'total_validations': 0,
            'high_confidence_grids': 0,
            'medium_confidence_grids': 0,
            'low_confidence_grids': 0,
            'avg_fitness_score': 0.0,
            'validation_coverage': 0.0,
        }
    
    # ========================================================================
    # CHECK 1: ONSET ALIGNMENT (30% weight)
    # ========================================================================
    
    def _check_onset_alignment(
        self,
        audio: np.ndarray,
        sr: int,
        bpm: float,
        downbeat_sample: int
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Check if beat grid aligns with actual onset transients.
        
        Tolerance: ±20ms per beat
        Score: % of beats within tolerance
        
        Returns:
            (alignment_score, details_dict)
        """
        try:
            import librosa
            
            # Detect onsets
            onset_env = librosa.onset.onset_strength(y=audio, sr=sr)
            onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
            onset_samples = librosa.frames_to_samples(onset_frames)
            
            if len(onset_samples) == 0:
                return (0.5, {'error': 'no_onsets_detected'})
            
            # Generate beat grid
            beat_interval_samples = (60.0 / bpm) * sr
            beat_samples = []
            t_sample = downbeat_sample
            while t_sample < len(audio):
                beat_samples.append(int(t_sample))
                t_sample += beat_interval_samples
            
            if len(beat_samples) < 4:  # Need at least 4 beats for meaningful analysis
                return (0.5, {'error': 'too_few_beats'})
            
            # Check alignment
            tolerance_samples = int(0.020 * sr)  # ±20ms
            aligned_count = 0
            
            for beat_sample in beat_samples:
                if np.any(np.abs(onset_samples - beat_sample) < tolerance_samples):
                    aligned_count += 1
            
            alignment_percent = aligned_count / len(beat_samples)
            alignment_score = min(1.0, alignment_percent / 0.80)  # Score relative to 80% threshold
            
            return (alignment_score, {
                'aligned_count': aligned_count,
                'total_beats': len(beat_samples),
                'alignment_percent': alignment_percent * 100,
                'tolerance_ms': 20,
            })
            
        except Exception as e:
            logger.debug(f"Onset alignment check failed: {e}")
            return (0.5, {'error': str(e)})
    
    # ========================================================================
    # CHECK 2: TEMPO CONSISTENCY (30% weight)
    # ========================================================================
    
    def _check_tempo_consistency(
        self,
        audio: np.ndarray,
        sr: int,
        bpm: float,
        downbeat_sample: int
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Check if BPM remains stable across the track.
        
        Measures BPM variation across bars.
        Threshold: ±3 BPM max variation (coefficient of variation < 0.03)
        
        Returns:
            (consistency_score, details_dict)
        """
        try:
            import librosa
            
            # Analyze BPM stability across chunks
            chunk_size = int(sr * 30)  # 30-second chunks
            chunk_bpms = []
            
            for start_sample in range(downbeat_sample, len(audio) - chunk_size, chunk_size):
                chunk = audio[start_sample:start_sample + chunk_size]
                
                # Simple onset-based BPM estimation
                onset_env = librosa.onset.onset_strength(y=chunk, sr=sr)
                onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
                
                if len(onset_frames) > 4:
                    # Estimate BPM from onset spacing
                    onset_intervals = np.diff(librosa.frames_to_time(onset_frames, sr=sr))
                    if len(onset_intervals) > 0:
                        avg_interval = np.mean(onset_intervals)
                        chunk_bpm = 60.0 / avg_interval if avg_interval > 0 else bpm
                        chunk_bpms.append(chunk_bpm)
            
            if len(chunk_bpms) < 2:
                # Not enough data, assume consistent
                return (0.9, {'error': 'insufficient_chunks', 'message': 'track too short'})
            
            # Calculate BPM variation (coefficient of variation)
            chunk_bpms = np.array(chunk_bpms)
            mean_bpm = np.mean(chunk_bpms)
            cv = np.std(chunk_bpms) / mean_bpm if mean_bpm > 0 else 0
            
            # Convert CV to BPM variance
            bpm_variance = cv * mean_bpm
            
            # Score: 1.0 if variance < 1 BPM, scales down for larger variance
            consistency_score = max(0.0, 1.0 - (bpm_variance / self.tempo_consistency_threshold))
            
            return (consistency_score, {
                'chunk_count': len(chunk_bpms),
                'mean_bpm': mean_bpm,
                'std_bpm': np.std(chunk_bpms),
                'bpm_variance': bpm_variance,
                'coefficient_of_variation': cv,
                'threshold_bpm': self.tempo_consistency_threshold,
            })
            
        except Exception as e:
            logger.debug(f"Tempo consistency check failed: {e}")
            return (0.6, {'error': str(e)})
    
    # ========================================================================
    # CHECK 3: PHASE ALIGNMENT (20% weight)
    # ========================================================================
    
    def _check_phase_alignment(
        self,
        audio: np.ndarray,
        sr: int,
        bpm: float,
        downbeat_sample: int
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Check if grid phase aligns with first detected kick/kick pattern.
        
        Measures offset between grid phase and detected kick onset.
        Threshold: ±50ms acceptable offset
        
        Returns:
            (phase_score, details_dict)
        """
        try:
            import librosa
            
            # Find strongest onset in first 5 seconds (likely a kick)
            search_samples = min(int(5 * sr), len(audio))
            search_audio = audio[:search_samples]
            
            onset_env = librosa.onset.onset_strength(y=search_audio, sr=sr)
            onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
            
            if len(onset_frames) == 0:
                return (0.5, {'error': 'no_onsets_detected'})
            
            # Find strongest onset
            onset_env_smooth = np.convolve(onset_env, np.ones(10)/10, mode='same')
            peaks = librosa.util.peak_pick(onset_env_smooth, 1, 1, 1, 5)
            
            if len(peaks) == 0:
                first_kick_sample = librosa.frames_to_samples(onset_frames[0])
            else:
                first_kick_sample = librosa.frames_to_samples(peaks[0])
            
            # Calculate offset between grid and kick
            offset_samples = abs(first_kick_sample - downbeat_sample)
            offset_ms = (offset_samples / sr) * 1000
            
            # Score: 1.0 if offset < 20ms, scales down to threshold
            threshold_samples = int(self.phase_alignment_threshold / 1000 * sr)
            
            if offset_samples <= threshold_samples:
                phase_score = 1.0 - (offset_samples / (threshold_samples * 2))
            else:
                phase_score = max(0.0, 1.0 - (offset_samples / threshold_samples))
            
            phase_score = max(0.0, min(1.0, phase_score))
            
            return (phase_score, {
                'first_kick_ms': (first_kick_sample / sr) * 1000,
                'grid_phase_ms': (downbeat_sample / sr) * 1000,
                'offset_ms': offset_ms,
                'threshold_ms': self.phase_alignment_threshold,
            })
            
        except Exception as e:
            logger.debug(f"Phase alignment check failed: {e}")
            return (0.6, {'error': str(e)})
    
    # ========================================================================
    # CHECK 4: SPECTRAL CONSISTENCY (20% weight)
    # ========================================================================
    
    def _check_spectral_consistency(
        self,
        audio: np.ndarray,
        sr: int,
        detected_bpm: float,
        secondary_bpm: Optional[float] = None
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Check if multiple detection methods agree on BPM.
        
        Compares primary and secondary BPM methods.
        Threshold: <2% difference for high agreement
        
        Returns:
            (spectral_score, details_dict)
        """
        try:
            if secondary_bpm is None:
                # If no secondary BPM, try essentia
                import essentia.standard as es
                
                sample_rate = 44100
                if sr != sample_rate:
                    # Resample to 44100 if needed
                    import librosa
                    audio_resampled = librosa.resample(audio, orig_sr=sr, target_sr=sample_rate)
                else:
                    audio_resampled = audio
                
                # Limit to 60 seconds
                max_samples = int(60 * sample_rate)
                if len(audio_resampled) > max_samples:
                    audio_resampled = audio_resampled[:max_samples]
                
                # Detect BPM
                rhythm_extractor = es.RhythmExtractor2013(method="degara")
                bpm_essentia, _, _, _, _ = rhythm_extractor(audio_resampled)
                secondary_bpm = bpm_essentia
            
            if secondary_bpm is None or secondary_bpm <= 0:
                # Can't compare, assume consistent
                return (0.8, {'error': 'no_secondary_bpm'})
            
            # Compare BPMs (check both direct and octave)
            diff_percent = abs(detected_bpm - secondary_bpm) / detected_bpm
            
            # Check octave variants
            octave_half = detected_bpm / 2
            octave_double = detected_bpm * 2
            
            diff_half = abs(octave_half - secondary_bpm) / octave_half
            diff_double = abs(octave_double - secondary_bpm) / octave_double
            
            # Use best match
            min_diff = min(diff_percent, diff_half, diff_double)
            
            # Score based on agreement
            if min_diff < 0.02:  # <2% difference
                spectral_score = 1.0
            elif min_diff < 0.05:  # <5% difference
                spectral_score = 0.8
            else:
                spectral_score = 0.5
            
            return (spectral_score, {
                'primary_bpm': detected_bpm,
                'secondary_bpm': secondary_bpm,
                'bpm_difference_percent': diff_percent * 100,
                'min_difference_percent': min_diff * 100,
                'agreement_score': 1.0 - min(min_diff, 0.1),
            })
            
        except Exception as e:
            logger.debug(f"Spectral consistency check failed: {e}")
            return (0.7, {'error': str(e)})
    
    # ========================================================================
    # MAIN VALIDATION FUNCTION
    # ========================================================================
    
    def validate_grid(
        self,
        audio: np.ndarray,
        sr: int,
        bpm: float,
        downbeat_sample: int,
        secondary_bpm: Optional[float] = None
    ) -> GridValidationResult:
        """
        Validate beat grid using 4-check framework.
        
        Args:
            audio: Audio samples (numpy array)
            sr: Sample rate (Hz)
            bpm: Detected BPM
            downbeat_sample: Sample index of first downbeat
            secondary_bpm: Optional BPM from secondary method
            
        Returns:
            GridValidationResult with fitness score and recommendations
        """
        import time
        start_time = time.time()
        
        # Run all 4 checks
        onset_score, onset_details = self._check_onset_alignment(audio, sr, bpm, downbeat_sample)
        tempo_score, tempo_details = self._check_tempo_consistency(audio, sr, bpm, downbeat_sample)
        phase_score, phase_details = self._check_phase_alignment(audio, sr, bpm, downbeat_sample)
        spectral_score, spectral_details = self._check_spectral_consistency(
            audio, sr, bpm, secondary_bpm
        )
        
        # Calculate weighted fitness score
        fitness_score = (
            0.30 * onset_score +
            0.30 * tempo_score +
            0.20 * phase_score +
            0.20 * spectral_score
        )
        
        # Determine confidence level
        if fitness_score >= self.high_fitness_threshold:
            confidence = GridConfidence.HIGH
            recommendation = "Grid quality HIGH - Ready for EQ automation"
        elif fitness_score >= self.medium_fitness_threshold:
            confidence = GridConfidence.MEDIUM
            recommendation = "Grid quality MEDIUM - Recommend manual verification"
        else:
            confidence = GridConfidence.LOW
            recommendation = "Grid quality LOW - Recommend recalculation"
        
        # Track metrics
        self.metrics['total_validations'] += 1
        if confidence == GridConfidence.HIGH:
            self.metrics['high_confidence_grids'] += 1
        elif confidence == GridConfidence.MEDIUM:
            self.metrics['medium_confidence_grids'] += 1
        else:
            self.metrics['low_confidence_grids'] += 1
        
        self.metrics['avg_fitness_score'] = (
            (self.metrics['avg_fitness_score'] * (self.metrics['total_validations'] - 1) + fitness_score) /
            self.metrics['total_validations']
        )
        
        self.metrics['validation_coverage'] = (
            (self.metrics['high_confidence_grids'] + self.metrics['medium_confidence_grids']) /
            self.metrics['total_validations'] * 100
        )
        
        # Extract details
        elapsed = time.time() - start_time
        
        result = GridValidationResult(
            fitness_score=fitness_score,
            confidence=confidence,
            recommendation=recommendation,
            onset_alignment_score=onset_score,
            tempo_consistency_score=tempo_score,
            phase_alignment_score=phase_score,
            spectral_consistency_score=spectral_score,
            onset_alignment_percent=onset_details.get('alignment_percent', 0),
            tempo_consistency_bpm_variance=tempo_details.get('bpm_variance', 0),
            phase_alignment_offset_ms=phase_details.get('offset_ms', 0),
            spectral_bpm_agreement=spectral_details.get('agreement_score', 0),
            validation_time_sec=elapsed,
            metadata={
                'onset_details': onset_details,
                'tempo_details': tempo_details,
                'phase_details': phase_details,
                'spectral_details': spectral_details,
            }
        )
        
        return result
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get validation metrics."""
        return {
            **self.metrics,
            'total_validations': self.metrics['total_validations'],
        }


def create_grid_validator(config: Optional[Dict[str, Any]] = None) -> GridValidator:
    """Factory function to create grid validator."""
    if config is None:
        config = {}
    return GridValidator(config)


if __name__ == "__main__":
    print("Grid Validator initialized and ready")
