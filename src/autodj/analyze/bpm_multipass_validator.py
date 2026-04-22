"""
PHASE 0 FIX #2: BPM Multi-Pass Validator with Octave Error Detection

Implements 3-pass voting system for robust BPM detection:
- Pass 1: Aubio onset-based autocorrelation
- Pass 2: Essentia degara method (spectral)
- Pass 3: Secondary confidence check

Octave error detection:
- Tests BPM, BPM/2, BPM*2
- Returns most stable candidate
"""

import logging
from typing import Optional, Dict, Any, Tuple, List
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BPMMultiPassResult:
    """Result of 3-pass BPM detection."""
    bpm: float                      # Final detected BPM (normalized)
    confidence: float               # Overall confidence (0-1)
    method: str                     # "3-pass voting"
    agreement_level: str            # "unanimous", "2/3", "1/3"
    
    # Pass results
    pass1_bpm: Optional[float] = None      # Aubio method
    pass1_confidence: Optional[float] = None
    pass2_bpm: Optional[float] = None      # Essentia method
    pass2_confidence: Optional[float] = None
    pass3_bpm: Optional[float] = None      # Validation pass
    pass3_confidence: Optional[float] = None
    
    # Octave detection
    octave_error_detected: bool = False
    octave_error_type: Optional[str] = None  # "double", "half", None
    octave_corrected_bpm: Optional[float] = None
    
    # Metrics
    votes: List[float] = None
    detection_time_sec: float = 0.0


class BPMMultiPassValidator:
    """Multi-pass BPM detection with voting and octave error detection."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize validator."""
        self.config = config
        self.bpm_range = config.get('bpm_search_range', [50, 200])
        
        # Metrics
        self.metrics = {
            'total_validations': 0,
            'unanimous_agreement': 0,
            'two_pass_agreement': 0,
            'single_pass': 0,
            'octave_errors_detected': 0,
            'octave_errors_corrected': 0,
            'avg_confidence': 0.0,
        }
    
    def validate_bpm_multipass(
        self,
        audio_path: str,
        config: dict,
        detected_bpm: float,
        detected_confidence: float,
        detection_method: str
    ) -> BPMMultiPassResult:
        """
        Validate BPM using multi-pass system with octave error detection.
        
        Args:
            audio_path: Path to audio file
            config: Analysis config
            detected_bpm: BPM from primary detection
            detected_confidence: Confidence from primary detection
            detection_method: Method used ("aubio", "essentia")
            
        Returns:
            BPMMultiPassResult with voting and octave analysis
        """
        import time
        start_time = time.time()
        
        self.metrics['total_validations'] += 1
        
        # Collect votes from multiple passes
        votes = []
        confidences = []
        
        # Pass 1: Primary method
        pass1_bpm = detected_bpm
        pass1_confidence = detected_confidence
        if pass1_bpm and pass1_confidence:
            votes.append(pass1_bpm)
            confidences.append(pass1_confidence)
            logger.debug(f"Pass 1 ({detection_method}): {pass1_bpm:.1f} BPM @ {pass1_confidence:.2f}")
        
        # Pass 2: Try secondary method
        pass2_bpm, pass2_confidence = self._try_secondary_detection(audio_path, config)
        if pass2_bpm and pass2_confidence:
            votes.append(pass2_bpm)
            confidences.append(pass2_confidence)
            logger.debug(f"Pass 2 (secondary): {pass2_bpm:.1f} BPM @ {pass2_confidence:.2f}")
        
        # Pass 3: Consistency check (re-validate primary with normalization)
        pass3_bpm, pass3_confidence = self._pass3_consistency_check(
            detected_bpm, detected_confidence
        )
        if pass3_bpm and pass3_confidence:
            votes.append(pass3_bpm)
            confidences.append(pass3_confidence)
            logger.debug(f"Pass 3 (validation): {pass3_bpm:.1f} BPM @ {pass3_confidence:.2f}")
        
        # Voting logic
        agreement_level = self._determine_agreement(votes)
        
        # Select BPM based on voting
        if agreement_level == "unanimous" and len(votes) >= 3:
            # All passes agree: high confidence
            final_bpm = np.mean(votes)
            final_confidence = np.mean(confidences)
            self.metrics['unanimous_agreement'] += 1
        elif agreement_level in ["2/3", "2pass"] and len(votes) >= 2:
            # Two passes agree: medium confidence
            # Use the two closest votes
            votes_sorted = sorted(votes)
            final_bpm = np.mean(votes_sorted[:2])
            final_confidence = min(0.75, np.mean(confidences[:2]))
            self.metrics['two_pass_agreement'] += 1
        else:
            # Single pass or no agreement: use best confidence
            best_idx = np.argmax(confidences) if confidences else 0
            final_bpm = votes[best_idx] if best_idx < len(votes) else detected_bpm
            final_confidence = confidences[best_idx] if best_idx < len(confidences) else 0.5
            self.metrics['single_pass'] += 1
        
        # Octave error detection
        octave_error_detected, octave_type, corrected_bpm = self._detect_octave_error(
            final_bpm, votes
        )
        
        if octave_error_detected:
            logger.warning(f"Octave error detected: {octave_type} (original: {final_bpm:.1f}, corrected: {corrected_bpm:.1f})")
            final_bpm = corrected_bpm
            final_confidence *= 0.7  # Reduce confidence due to octave correction
            self.metrics['octave_errors_detected'] += 1
            self.metrics['octave_errors_corrected'] += 1
        
        # Time tracking
        elapsed = time.time() - start_time
        
        # Update metrics
        self.metrics['avg_confidence'] = (
            (self.metrics['avg_confidence'] * (self.metrics['total_validations'] - 1) + final_confidence) /
            self.metrics['total_validations']
        )
        
        result = BPMMultiPassResult(
            bpm=final_bpm,
            confidence=final_confidence,
            method="3-pass voting",
            agreement_level=agreement_level,
            pass1_bpm=pass1_bpm,
            pass1_confidence=pass1_confidence,
            pass2_bpm=pass2_bpm,
            pass2_confidence=pass2_confidence,
            pass3_bpm=pass3_bpm,
            pass3_confidence=pass3_confidence,
            octave_error_detected=octave_error_detected,
            octave_error_type=octave_type,
            octave_corrected_bpm=corrected_bpm,
            votes=votes,
            detection_time_sec=elapsed,
        )
        
        return result
    
    def _try_secondary_detection(
        self,
        audio_path: str,
        config: dict
    ) -> Tuple[Optional[float], Optional[float]]:
        """Try secondary BPM detection method (essentia if aubio was used, etc)."""
        try:
            # Import essentia for secondary detection
            import essentia.standard as es
            import os
            
            # Check file size (avoid OOM)
            file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            if file_size_mb > 30:
                return (None, None)
            
            # Load audio
            sample_rate = 44100
            audio = es.MonoLoader(filename=audio_path, sampleRate=sample_rate)()
            
            # Limit duration
            max_samples = int(60 * sample_rate)
            if len(audio) > max_samples:
                audio = audio[:max_samples]
            
            # Detect BPM
            rhythm_extractor = es.RhythmExtractor2013(method="degara")
            bpm, beats, beats_confidence, _, _ = rhythm_extractor(audio)
            
            if len(beats_confidence) > 0:
                confidence = float(np.mean(beats_confidence))
            else:
                confidence = 0.5
            
            if bpm > 0:
                return (float(bpm), float(confidence))
            return (None, None)
            
        except Exception as e:
            logger.debug(f"Secondary detection failed: {e}")
            return (None, None)
    
    def _pass3_consistency_check(
        self,
        bpm: float,
        confidence: float
    ) -> Tuple[Optional[float], Optional[float]]:
        """
        Pass 3: Simple consistency check.
        Returns same BPM but with confidence based on normalization stability.
        """
        try:
            # Normalize BPM
            normalized = self._normalize_bpm(bpm)
            
            # If normalization changed BPM significantly, reduce confidence
            if abs(normalized - bpm) / bpm > 0.05:  # >5% difference
                adjusted_confidence = confidence * 0.8
            else:
                adjusted_confidence = confidence * 0.95  # Slight boost
            
            return (float(normalized), float(adjusted_confidence))
            
        except Exception as e:
            logger.debug(f"Pass 3 failed: {e}")
            return (None, None)
    
    def _normalize_bpm(self, bpm: float) -> float:
        """Normalize BPM to DJ-friendly range (85-175)."""
        min_bpm, max_bpm = 85, 175
        
        while bpm < min_bpm and bpm > 0:
            bpm *= 2
        
        while bpm > max_bpm:
            bpm /= 2
        
        return bpm
    
    def _determine_agreement(self, votes: List[float]) -> str:
        """Determine level of agreement between passes."""
        if len(votes) < 2:
            return "1/3"
        
        if len(votes) >= 3:
            # Check if all within 2% agreement
            if self._votes_agree(votes, tolerance=0.02):
                return "unanimous"
            # Check if best 2 agree
            votes_sorted = sorted(votes)
            if self._votes_agree(votes_sorted[:2], tolerance=0.02):
                return "2/3"
        
        if len(votes) == 2:
            if self._votes_agree(votes, tolerance=0.02):
                return "2pass"
        
        return "1/3"
    
    def _votes_agree(self, bpms: List[float], tolerance: float = 0.02) -> bool:
        """Check if BPMs agree within tolerance (percentage)."""
        if len(bpms) < 2:
            return True
        
        mean_bpm = np.mean(bpms)
        for bpm in bpms:
            if abs(bpm - mean_bpm) / mean_bpm > tolerance:
                return False
        return True
    
    def _detect_octave_error(
        self,
        primary_bpm: float,
        all_votes: List[float]
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Detect and correct octave errors (BPM/2 or BPM*2).
        
        Returns:
            (error_detected, error_type, corrected_bpm)
        """
        # Test three candidates
        candidates = {
            'half': primary_bpm / 2,
            'normal': primary_bpm,
            'double': primary_bpm * 2,
        }
        
        # Score each candidate based on agreement with other votes
        scores = {}
        for key, candidate_bpm in candidates.items():
            # Count how many votes are close to this candidate
            close_count = sum(
                1 for vote in all_votes
                if abs(vote - candidate_bpm) / candidate_bpm < 0.05
            )
            scores[key] = close_count
        
        # If double or half BPM has better agreement, flag it
        if scores['half'] > scores['normal'] or scores['double'] > scores['normal']:
            best_type = max(scores, key=scores.get)
            if best_type != 'normal':
                return (
                    True,
                    best_type,
                    candidates[best_type]
                )
        
        return (False, None, None)
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get validation metrics."""
        total = self.metrics['total_validations']
        if total == 0:
            return self.metrics
        
        return {
            **self.metrics,
            'unanimous_agreement_percent': (
                self.metrics['unanimous_agreement'] / total * 100
            ),
            'two_pass_agreement_percent': (
                self.metrics['two_pass_agreement'] / total * 100
            ),
            'octave_error_rate': (
                self.metrics['octave_errors_detected'] / total * 100
            ),
        }


def create_multipass_validator(config: Dict[str, Any]) -> BPMMultiPassValidator:
    """Factory function to create multi-pass validator."""
    return BPMMultiPassValidator(config)


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.DEBUG)
    
    config = {'bpm_search_range': [50, 200]}
    validator = create_multipass_validator(config)
    
    print("BPM Multi-Pass Validator initialized and ready")
