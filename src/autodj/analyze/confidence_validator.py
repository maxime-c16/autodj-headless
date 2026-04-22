"""
Confidence Validator: Graduated confidence threshold checking for audio detection results.

Provides three-tier confidence validation:
- HIGH (0.90+): Use directly, no validation needed
- MEDIUM (0.70-0.89): Use with validation checkpoints
- LOW (<0.70): Require manual verification or fallback

Usage:
    validator = ConfidenceValidator(config)
    result = validator.validate_bpm_confidence(bpm, confidence)
    
    if result['valid']:
        use_bpm(result['bpm'])
    elif result['requires_validation']:
        run_grid_validation_checkpoints(result)
    else:
        fallback_or_manual_review(result)
"""

import logging
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ConfidenceTier(Enum):
    """Confidence tier classification."""
    HIGH = "high"          # 0.90+: Use directly
    MEDIUM = "medium"      # 0.70-0.89: Use with checkpoints
    LOW = "low"            # <0.70: Manual review/fallback


@dataclass
class ConfidenceResult:
    """Result of confidence validation."""
    value: float                      # Confidence value (0-1)
    tier: ConfidenceTier             # Confidence tier
    valid: bool                      # Is this confidence acceptable?
    requires_validation: bool        # Should we run extra checks?
    recommendation: str              # What to do
    message: str                     # Human-readable message
    metadata: Dict[str, Any]         # Additional context


class ConfidenceValidator:
    """
    Graduated confidence threshold validator.
    
    Implements three-tier system:
    - HIGH (0.90+): High confidence, use directly
    - MEDIUM (0.70-0.89): Medium confidence, use with checkpoints
    - LOW (<0.70): Low confidence, flag for review
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize validator with config.
        
        Args:
            config: Configuration dict with:
                - confidence_high_threshold (default 0.90)
                - confidence_medium_threshold (default 0.70)
                - enable_logging (default True)
        """
        self.config = config
        self.high_threshold = config.get('confidence_high_threshold', 0.90)
        self.medium_threshold = config.get('confidence_medium_threshold', 0.70)
        self.enable_logging = config.get('enable_logging', True)
        
        # Validation: thresholds must be ordered
        if not (0 <= self.medium_threshold < self.high_threshold <= 1.0):
            raise ValueError(
                f"Invalid thresholds: medium={self.medium_threshold}, "
                f"high={self.high_threshold}"
            )
        
        # Metrics tracking
        self.metrics = {
            'total_validations': 0,
            'high_confidence_count': 0,
            'medium_confidence_count': 0,
            'low_confidence_count': 0,
        }
    
    def _get_confidence_tier(self, confidence: float) -> ConfidenceTier:
        """Classify confidence value into tier."""
        if confidence >= self.high_threshold:
            return ConfidenceTier.HIGH
        elif confidence >= self.medium_threshold:
            return ConfidenceTier.MEDIUM
        else:
            return ConfidenceTier.LOW
    
    def validate_bpm_confidence(
        self,
        bpm: float,
        confidence: float,
        detection_method: str = "unknown"
    ) -> ConfidenceResult:
        """
        Validate BPM confidence value.
        
        Args:
            bpm: Detected BPM (beats per minute)
            confidence: Confidence score (0-1)
            detection_method: Method used for detection (e.g., "aubio", "essentia")
            
        Returns:
            ConfidenceResult with validation decision
        """
        self.metrics['total_validations'] += 1
        
        # Input validation
        if not (0 <= confidence <= 1.0):
            logger.error(f"Invalid confidence value: {confidence}")
            return ConfidenceResult(
                value=confidence,
                tier=ConfidenceTier.LOW,
                valid=False,
                requires_validation=False,
                recommendation="reject",
                message="Invalid confidence value (must be 0-1)",
                metadata={'error': 'invalid_confidence_value'}
            )
        
        if not (50 <= bpm <= 200):
            logger.error(f"Invalid BPM value: {bpm}")
            return ConfidenceResult(
                value=confidence,
                tier=ConfidenceTier.LOW,
                valid=False,
                requires_validation=False,
                recommendation="reject",
                message=f"Invalid BPM value: {bpm} (must be 50-200)",
                metadata={'error': 'invalid_bpm_value'}
            )
        
        # Classify tier
        tier = self._get_confidence_tier(confidence)
        self.metrics[f'{tier.value}_confidence_count'] += 1
        
        # Generate result based on tier
        if tier == ConfidenceTier.HIGH:
            result = ConfidenceResult(
                value=confidence,
                tier=tier,
                valid=True,
                requires_validation=False,
                recommendation="use_directly",
                message=f"✅ HIGH CONFIDENCE: {bpm:.1f} BPM @ {confidence:.2f} - Use directly",
                metadata={
                    'action': 'use_directly',
                    'enable_aggressive_eq': True,
                    'detection_method': detection_method,
                    'margin_to_high': confidence - self.high_threshold,
                }
            )
            
        elif tier == ConfidenceTier.MEDIUM:
            result = ConfidenceResult(
                value=confidence,
                tier=tier,
                valid=True,
                requires_validation=True,
                recommendation="use_with_checkpoints",
                message=f"⚠️ MEDIUM CONFIDENCE: {bpm:.1f} BPM @ {confidence:.2f} - Requires grid validation",
                metadata={
                    'action': 'use_with_checkpoints',
                    'enable_aggressive_eq': False,
                    'detection_method': detection_method,
                    'margin_to_high': self.high_threshold - confidence,
                    'margin_to_medium': confidence - self.medium_threshold,
                    'required_checks': ['onset_alignment', 'tempo_consistency'],
                }
            )
            
        else:  # LOW
            result = ConfidenceResult(
                value=confidence,
                tier=tier,
                valid=False,
                requires_validation=False,
                recommendation="manual_review_or_fallback",
                message=f"❌ LOW CONFIDENCE: {bpm:.1f} BPM @ {confidence:.2f} - Flag for manual review",
                metadata={
                    'action': 'flag_for_review',
                    'enable_aggressive_eq': False,
                    'detection_method': detection_method,
                    'margin_to_medium': self.medium_threshold - confidence,
                    'suggested_actions': [
                        'Try different detection algorithm',
                        'Manual verification required',
                        'Use default fallback tempo (120 BPM)',
                        'Check for octave error (try BPM/2 or BPM*2)',
                    ]
                }
            )
        
        # Log result
        if self.enable_logging:
            self._log_confidence_decision(result)
        
        return result
    
    def _log_confidence_decision(self, result: ConfidenceResult) -> None:
        """Log confidence validation decision."""
        tier = result.tier.value.upper()
        
        if result.tier == ConfidenceTier.HIGH:
            logger.info(f"[CONFIDENCE] {tier}: {result.message}")
        elif result.tier == ConfidenceTier.MEDIUM:
            logger.warning(f"[CONFIDENCE] {tier}: {result.message}")
        else:
            logger.error(f"[CONFIDENCE] {tier}: {result.message}")
    
    def validate_grid_confidence(
        self,
        fitness_score: float,
        track_name: str = "unknown"
    ) -> ConfidenceResult:
        """
        Validate grid fitness score.
        
        Grid uses different thresholds than BPM:
        - HIGH: >= 0.80
        - MEDIUM: 0.60-0.79
        - LOW: < 0.60
        
        Args:
            fitness_score: Grid fitness score (0-1)
            track_name: Track identifier for logging
            
        Returns:
            ConfidenceResult with validation decision
        """
        self.metrics['total_validations'] += 1
        
        # Grid-specific thresholds
        grid_high_threshold = 0.80
        grid_medium_threshold = 0.60
        
        if fitness_score >= grid_high_threshold:
            tier = ConfidenceTier.HIGH
            valid = True
            requires_validation = False
            recommendation = "use_directly"
            message = f"✅ Grid HIGH confidence: {fitness_score:.2f}"
            
        elif fitness_score >= grid_medium_threshold:
            tier = ConfidenceTier.MEDIUM
            valid = True
            requires_validation = True
            recommendation = "use_with_checkpoints"
            message = f"⚠️ Grid MEDIUM confidence: {fitness_score:.2f} - Check onsets"
            
        else:
            tier = ConfidenceTier.LOW
            valid = False
            requires_validation = False
            recommendation = "manual_review"
            message = f"❌ Grid LOW confidence: {fitness_score:.2f} - Manual review needed"
        
        result = ConfidenceResult(
            value=fitness_score,
            tier=tier,
            valid=valid,
            requires_validation=requires_validation,
            recommendation=recommendation,
            message=message,
            metadata={
                'validation_type': 'grid',
                'track': track_name,
                'high_threshold': grid_high_threshold,
                'medium_threshold': grid_medium_threshold,
            }
        )
        
        if self.enable_logging:
            self._log_confidence_decision(result)
        
        return result
    
    def get_validation_metrics(self) -> Dict[str, Any]:
        """Get validation metrics."""
        total = self.metrics['total_validations']
        
        if total == 0:
            return self.metrics
        
        return {
            **self.metrics,
            'high_confidence_percent': (
                self.metrics['high_confidence_count'] / total * 100
            ),
            'medium_confidence_percent': (
                self.metrics['medium_confidence_count'] / total * 100
            ),
            'low_confidence_percent': (
                self.metrics['low_confidence_count'] / total * 100
            ),
        }
    
    def get_recommendation_action(self, result: ConfidenceResult) -> str:
        """
        Get specific action based on validation result.
        
        Returns string indicating what to do next.
        """
        return result.metadata.get('action', result.recommendation)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_confidence_validator(config: Optional[Dict] = None) -> ConfidenceValidator:
    """
    Factory function to create validator with sensible defaults.
    
    Args:
        config: Optional configuration override
        
    Returns:
        ConfidenceValidator instance
    """
    default_config = {
        'confidence_high_threshold': 0.90,
        'confidence_medium_threshold': 0.70,
        'enable_logging': True,
    }
    
    if config:
        default_config.update(config)
    
    return ConfidenceValidator(default_config)


def batch_validate_confidences(
    bpm_results: list,
    validator: ConfidenceValidator
) -> Tuple[list, Dict[str, Any]]:
    """
    Validate a batch of BPM detection results.
    
    Args:
        bpm_results: List of (bpm, confidence, method) tuples
        validator: ConfidenceValidator instance
        
    Returns:
        (validated_results, summary_metrics)
    """
    validated = []
    
    for bpm, confidence, method in bpm_results:
        result = validator.validate_bpm_confidence(bpm, confidence, method)
        validated.append({
            'bpm': bpm,
            'confidence': confidence,
            'method': method,
            'validation_result': result
        })
    
    metrics = validator.get_validation_metrics()
    
    return validated, metrics


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.DEBUG)
    
    validator = create_confidence_validator()
    
    # Test cases
    test_cases = [
        (128.0, 0.95, "essentia"),     # HIGH confidence
        (130.0, 0.75, "aubio"),         # MEDIUM confidence
        (125.0, 0.45, "aubio"),         # LOW confidence
        (132.0, 0.90, "tempogram"),     # HIGH confidence
        (127.0, 0.65, "essentia"),      # MEDIUM confidence
    ]
    
    print("Testing Confidence Validator")
    print("=" * 60)
    
    for bpm, confidence, method in test_cases:
        result = validator.validate_bpm_confidence(bpm, confidence, method)
        print(f"\n{result.message}")
        print(f"  Recommendation: {result.recommendation}")
        print(f"  Metadata: {result.metadata}")
    
    print("\n" + "=" * 60)
    print("Metrics:")
    print(validator.get_validation_metrics())
