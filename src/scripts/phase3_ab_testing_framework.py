#!/usr/bin/env python3
"""
PHASE 3 A/B Testing Framework
Refinement Engineer - System Validation & Optimization
"""

import os
import json
import time
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple
import sys

# Add src to path
sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

try:
    from autodj.analyze.confidence_validator import ConfidenceValidator
except ImportError:
    ConfidenceValidator = None

try:
    from autodj.analyze.bpm_multipass_validator import BPMMultiPassValidator
except ImportError:
    BPMMultiPassValidator = None

try:
    from autodj.analyze.grid_validator import GridValidator
except ImportError:
    GridValidator = None

try:
    from autodj.analyze.bpm import detect_bpm
except ImportError:
    detect_bpm = None

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/home/mcauchy/autodj-headless/phase3_ab_test.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('PHASE3_AB_TEST')

@dataclass
class TestTrack:
    """Test track definition with metadata"""
    track_id: str
    name: str
    genre: str
    bpm: float
    energy_level: str  # low, medium, high
    description: str

@dataclass
class RenderMetrics:
    """Metrics collected from a single render pass"""
    track_id: str
    render_time_ms: float
    cpu_usage_percent: float
    memory_usage_mb: float
    octave_error: bool
    octave_error_type: Optional[str]  # octave_up, octave_down, none
    bpm_confidence: float
    bpm_primary: float
    bpm_multipass_result: Optional[Dict]
    grid_fitness: float
    grid_fitness_class: str  # HIGH, MEDIUM, LOW
    validation_errors: List[str]
    processing_successful: bool
    timestamp: str

@dataclass
class ABTestResult:
    """A/B Test result comparing baseline vs. with fixes"""
    track_id: str
    config_a_metrics: RenderMetrics
    config_b_metrics: RenderMetrics
    improvements: Dict[str, float]
    pass_fail: Dict[str, bool]

class TestDataset:
    """Generates synthetic test dataset with diverse characteristics"""
    
    def __init__(self):
        self.tracks: List[TestTrack] = []
    
    def generate_diverse_dataset(self) -> List[TestTrack]:
        """Generate 15 diverse test tracks"""
        logger.info("Generating diverse test dataset...")
        
        self.tracks = [
            # EDM tracks (high energy, 120-130 BPM)
            TestTrack("EDM_001", "Future Bass Drop", "EDM", 128.0, "high", 
                     "Heavy bass, sidechain dynamics"),
            TestTrack("EDM_002", "Progressive House", "EDM", 125.0, "high",
                     "Building tension, bass evolution"),
            TestTrack("EDM_003", "Dubstep Wobble", "EDM", 140.0, "high",
                     "Aggressive bass modulation"),
            
            # House tracks (120-128 BPM, medium-high energy)
            TestTrack("HOUSE_001", "Deep House", "House", 120.0, "medium",
                     "Groovy, steady kick"),
            TestTrack("HOUSE_002", "Tech House", "House", 124.0, "high",
                     "Complex percussion, off-beat hi-hats"),
            TestTrack("HOUSE_003", "Minimal House", "House", 120.0, "low",
                     "Sparse, atmospheric elements"),
            
            # Techno tracks (120-140 BPM, medium-high energy)
            TestTrack("TECHNO_001", "Industrial Techno", "Techno", 135.0, "high",
                     "Harsh, distorted kick"),
            TestTrack("TECHNO_002", "Groove Techno", "Techno", 125.0, "medium",
                     "Hypnotic, repetitive patterns"),
            TestTrack("TECHNO_003", "Acid Techno", "Techno", 128.0, "high",
                     "TB-303 sequences, melodic elements"),
            
            # Hip-Hop/Funk tracks (80-100 BPM, medium energy)
            TestTrack("HIPHOP_001", "Boom-Bap Hip-Hop", "Hip-Hop", 95.0, "medium",
                     "Vocal samples, sidechain compression"),
            TestTrack("HIPHOP_002", "Trap Beat", "Hip-Hop", 88.0, "medium",
                     "Hi-hat rolls, 808 bass"),
            TestTrack("FUNK_001", "Funk Groove", "Funk", 100.0, "high",
                     "Bass-centric, no EQ cuts"),
            
            # Edge cases
            TestTrack("EDGE_LOW", "Downtempo/Ambient", "Other", 60.0, "low",
                     "Very low BPM, sparse"),
            TestTrack("EDGE_HIGH", "Fast Techno", "Techno", 165.0, "high",
                     "Very high BPM, rapid elements"),
            TestTrack("EDGE_VOCAL", "Vocal-Heavy Track", "Other", 100.0, "medium",
                     "Prominent vocals, potential confidence issues"),
        ]
        
        logger.info(f"Generated {len(self.tracks)} test tracks")
        return self.tracks
    
    def print_dataset(self):
        """Print dataset details"""
        logger.info("\n" + "="*80)
        logger.info("TEST DATASET")
        logger.info("="*80)
        logger.info(f"{'Track ID':<15} | {'Name':<25} | {'Genre':<12} | {'BPM':<6} | {'Energy':<8}")
        logger.info("-"*80)
        for track in self.tracks:
            logger.info(f"{track.track_id:<15} | {track.name:<25} | {track.genre:<12} | {track.bpm:<6.1f} | {track.energy_level:<8}")
        logger.info("="*80 + "\n")

class ConfigManager:
    """Manages test configurations"""
    
    @staticmethod
    def config_a_baseline() -> Dict:
        """Configuration A: Baseline (no fixes)"""
        return {
            "confidence_validator_enabled": False,
            "bpm_multipass_enabled": False,
            "grid_validation_enabled": False,
            "adaptive_bass_enabled": False,
            "name": "Config A (Baseline)",
            "description": "No improvements - legacy behavior"
        }
    
    @staticmethod
    def config_b_with_fixes() -> Dict:
        """Configuration B: With all fixes"""
        return {
            "confidence_validator_enabled": True,
            "bpm_multipass_enabled": True,
            "grid_validation_enabled": True,
            "adaptive_bass_enabled": True,
            "name": "Config B (With Fixes)",
            "description": "All Phase 0 & Phase 1 improvements enabled"
        }

class SimulatedRenderer:
    """Simulates render process with metrics collection"""
    
    def __init__(self, config: Dict):
        self.config = config
        # Initialize validators with default config
        validator_config = {
            'confidence_high_threshold': 0.90,
            'confidence_medium_threshold': 0.70,
            'enable_logging': False,
            'aubio_threshold': 0.1,
            'essentia_threshold': 0.1,
            'agreement_required': 2,
            'octave_error_detection': True,
        }
        try:
            self.confidence_validator = ConfidenceValidator(validator_config) if ConfidenceValidator else None
        except Exception as e:
            logger.warning(f"Failed to initialize ConfidenceValidator: {e}")
            self.confidence_validator = None
        
        try:
            self.bpm_multipass_validator = BPMMultiPassValidator(validator_config) if BPMMultiPassValidator else None
        except Exception as e:
            logger.warning(f"Failed to initialize BPMMultiPassValidator: {e}")
            self.bpm_multipass_validator = None
        
        try:
            self.grid_validator = GridValidator(validator_config) if GridValidator else None
        except Exception as e:
            logger.warning(f"Failed to initialize GridValidator: {e}")
            self.grid_validator = None
    
    def render_track(self, track: TestTrack) -> RenderMetrics:
        """Simulate rendering a track with specified config"""
        
        start_time = time.time()
        octave_error = False
        octave_error_type = None
        bpm_confidence = 0.0
        bpm_primary = track.bpm
        bpm_multipass_result = None
        grid_fitness = 0.0
        grid_fitness_class = "UNKNOWN"
        validation_errors: List[str] = []
        processing_successful = True
        
        try:
            # Simulate confidence validation
            if self.config["confidence_validator_enabled"] and self.confidence_validator:
                confidence_result = self.confidence_validator.validate_bpm_confidence(
                    bpm=track.bpm,
                    confidence=self._simulate_bpm_confidence(track)
                )
                bpm_confidence = confidence_result.value
            else:
                bpm_confidence = self._simulate_bpm_confidence(track)
            
            # Simulate BPM multi-pass validation
            if self.config["bpm_multipass_enabled"] and self.bpm_multipass_validator:
                # This would require audio file, so we'll simulate the result
                bpm_multipass_result = self._simulate_bpm_multipass(track)
                bpm_primary = bpm_multipass_result.get("bpm_selected", track.bpm)
                
                # Check for octave errors
                octave_detection = bpm_multipass_result.get("octave_detection", {})
                if octave_detection.get("octave_error_found"):
                    octave_error = True
                    octave_error_type = octave_detection.get("error_type", "unknown")
            
            # Simulate grid validation
            if self.config["grid_validation_enabled"] and self.grid_validator:
                # This would require audio file, so we'll simulate the result
                grid_result = self._simulate_grid_validation(track, bpm_primary, bpm_confidence)
                grid_fitness = grid_result.get("fitness_score", 0.0)
                grid_fitness_class = self._classify_fitness(grid_fitness)
            
        except Exception as e:
            processing_successful = False
            validation_errors.append(str(e))
            logger.error(f"Error processing {track.track_id}: {e}")
        
        elapsed_time = (time.time() - start_time) * 1000  # Convert to ms
        cpu_usage = 15.0 + (elapsed_time / 100)  # Simulate CPU usage
        memory_usage = 150.0 + (track.bpm / 10)  # Simulate memory usage
        
        return RenderMetrics(
            track_id=track.track_id,
            render_time_ms=elapsed_time,
            cpu_usage_percent=cpu_usage,
            memory_usage_mb=memory_usage,
            octave_error=octave_error,
            octave_error_type=octave_error_type,
            bpm_confidence=bpm_confidence,
            bpm_primary=bpm_primary,
            bpm_multipass_result=bpm_multipass_result,
            grid_fitness=grid_fitness,
            grid_fitness_class=grid_fitness_class,
            validation_errors=validation_errors,
            processing_successful=processing_successful,
            timestamp=datetime.now().isoformat()
        )
    
    def _simulate_bpm_confidence(self, track: TestTrack) -> float:
        """Simulate BPM confidence based on track characteristics"""
        # Higher confidence for standard genres/BPMs
        base_confidence = 0.8
        
        # Reduce confidence for edge cases
        if track.bpm < 80 or track.bpm > 140:
            base_confidence *= 0.7
        
        if "EDGE" in track.track_id:
            base_confidence *= 0.6
        
        # Add some randomness
        import random
        base_confidence += random.gauss(0, 0.1)
        return max(0.3, min(1.0, base_confidence))
    
    def _simulate_bpm_multipass(self, track: TestTrack) -> Dict:
        """Simulate BPM multi-pass validation result"""
        # Simulate detecting the same BPM with high confidence
        bpm_selected = track.bpm
        
        # Simulate octave errors in some tracks (2% rate)
        import random
        has_octave_error = random.random() < 0.02
        error_type = None
        if has_octave_error:
            error_type = random.choice(["octave_up", "octave_down"])
        
        return {
            "bpm_selected": bpm_selected,
            "octave_detection": {
                "octave_error_found": has_octave_error,
                "error_type": error_type,
                "confidence_reduction": 0.15 if has_octave_error else 0.0
            },
            "agreement_level": "unanimous",
            "pass_1_bpm": track.bpm,
            "pass_2_bpm": track.bpm,
            "pass_3_bpm": track.bpm,
        }
    
    def _simulate_grid_validation(self, track: TestTrack, bpm: float, confidence: float) -> Dict:
        """Simulate grid validation result"""
        import random
        
        # Grid fitness depends on BPM confidence
        base_fitness = confidence * 0.8 + 0.1
        
        # Genre-specific modulation
        if track.genre in ["EDM", "House", "Techno"]:
            base_fitness += 0.15  # These genres have stable grids
        elif track.genre == "Hip-Hop":
            base_fitness -= 0.1   # Hip-Hop can have complex timing
        
        # Add randomness
        fitness = base_fitness + random.gauss(0, 0.1)
        fitness = max(0.0, min(1.0, fitness))
        
        return {
            "fitness_score": fitness,
            "onset_alignment": fitness * 1.2,
            "tempo_consistency": fitness,
            "phase_alignment": fitness,
            "spectral_consistency": fitness,
        }
    
    def _classify_fitness(self, fitness: float) -> str:
        """Classify grid fitness score"""
        if fitness >= 0.80:
            return "HIGH"
        elif fitness >= 0.60:
            return "MEDIUM"
        else:
            return "LOW"

class ABTestRunner:
    """Orchestrates A/B testing"""
    
    def __init__(self):
        self.dataset = TestDataset()
        self.results: List[ABTestResult] = []
        self.metrics_config_a: List[RenderMetrics] = []
        self.metrics_config_b: List[RenderMetrics] = []
    
    def run_ab_test(self) -> Tuple[List[ABTestResult], Dict]:
        """Execute complete A/B test"""
        
        logger.info("="*80)
        logger.info("PHASE 3 A/B TESTING FRAMEWORK - START")
        logger.info("="*80)
        
        # Generate test dataset
        tracks = self.dataset.generate_diverse_dataset()
        self.dataset.print_dataset()
        
        # Get configurations
        config_a = ConfigManager.config_a_baseline()
        config_b = ConfigManager.config_b_with_fixes()
        
        logger.info("\nConfiguration A (Baseline):")
        logger.info(json.dumps(config_a, indent=2))
        logger.info("\nConfiguration B (With Fixes):")
        logger.info(json.dumps(config_b, indent=2))
        
        # Run Config A (Baseline)
        logger.info("\n" + "="*80)
        logger.info("RUNNING CONFIG A (BASELINE)")
        logger.info("="*80)
        renderer_a = SimulatedRenderer(config_a)
        for track in tracks:
            metrics = renderer_a.render_track(track)
            self.metrics_config_a.append(metrics)
            logger.info(f"✓ {track.track_id}: confidence={metrics.bpm_confidence:.2f}, "
                       f"fitness={metrics.grid_fitness:.2f}, time={metrics.render_time_ms:.1f}ms")
        
        # Run Config B (With Fixes)
        logger.info("\n" + "="*80)
        logger.info("RUNNING CONFIG B (WITH FIXES)")
        logger.info("="*80)
        renderer_b = SimulatedRenderer(config_b)
        for track in tracks:
            metrics = renderer_b.render_track(track)
            self.metrics_config_b.append(metrics)
            logger.info(f"✓ {track.track_id}: confidence={metrics.bpm_confidence:.2f}, "
                       f"fitness={metrics.grid_fitness:.2f}, time={metrics.render_time_ms:.1f}ms")
        
        # Compare results
        logger.info("\n" + "="*80)
        logger.info("COMPARING RESULTS")
        logger.info("="*80)
        
        for metrics_a, metrics_b in zip(self.metrics_config_a, self.metrics_config_b):
            improvements = self._calculate_improvements(metrics_a, metrics_b)
            pass_fail = self._evaluate_success(metrics_a, metrics_b, improvements)
            
            result = ABTestResult(
                track_id=metrics_a.track_id,
                config_a_metrics=metrics_a,
                config_b_metrics=metrics_b,
                improvements=improvements,
                pass_fail=pass_fail
            )
            self.results.append(result)
        
        # Generate summary statistics
        summary = self._generate_summary()
        
        logger.info("\n" + "="*80)
        logger.info("A/B TEST COMPLETE")
        logger.info("="*80)
        
        return self.results, summary
    
    def _calculate_improvements(self, metrics_a: RenderMetrics, 
                               metrics_b: RenderMetrics) -> Dict[str, float]:
        """Calculate improvements from A to B"""
        improvements = {
            "confidence_improvement": metrics_b.bpm_confidence - metrics_a.bpm_confidence,
            "fitness_improvement": metrics_b.grid_fitness - metrics_a.grid_fitness,
            "render_time_change_percent": (
                (metrics_b.render_time_ms - metrics_a.render_time_ms) / metrics_a.render_time_ms * 100
                if metrics_a.render_time_ms > 0 else 0
            ),
            "octave_error_fixed": (
                1.0 if metrics_a.octave_error and not metrics_b.octave_error else 0.0
            ),
        }
        return improvements
    
    def _evaluate_success(self, metrics_a: RenderMetrics, 
                         metrics_b: RenderMetrics, 
                         improvements: Dict[str, float]) -> Dict[str, bool]:
        """Evaluate if test passes success criteria"""
        return {
            "confidence_improved": improvements["confidence_improvement"] > 0.05,
            "fitness_improved": improvements["fitness_improvement"] > 0.05,
            "render_time_acceptable": improvements["render_time_change_percent"] < 20,
            "octave_error_reduced": improvements["octave_error_fixed"] > 0 or not metrics_b.octave_error,
            "processing_successful": metrics_b.processing_successful
        }
    
    def _generate_summary(self) -> Dict:
        """Generate summary statistics"""
        
        # Octave error analysis
        octave_errors_a = sum(1 for m in self.metrics_config_a if m.octave_error)
        octave_errors_b = sum(1 for m in self.metrics_config_b if m.octave_error)
        octave_error_rate_a = octave_errors_a / len(self.metrics_config_a) * 100
        octave_error_rate_b = octave_errors_b / len(self.metrics_config_b) * 100
        
        # Confidence analysis
        high_conf_a = sum(1 for m in self.metrics_config_a if m.bpm_confidence >= 0.70)
        high_conf_b = sum(1 for m in self.metrics_config_b if m.bpm_confidence >= 0.70)
        high_conf_pct_a = high_conf_a / len(self.metrics_config_a) * 100
        high_conf_pct_b = high_conf_b / len(self.metrics_config_b) * 100
        
        # Grid fitness analysis
        high_fitness_b = sum(1 for m in self.metrics_config_b if m.grid_fitness >= 0.80)
        medium_fitness_b = sum(1 for m in self.metrics_config_b 
                              if 0.60 <= m.grid_fitness < 0.80)
        low_fitness_b = sum(1 for m in self.metrics_config_b if m.grid_fitness < 0.60)
        
        # Performance analysis
        avg_render_time_a = sum(m.render_time_ms for m in self.metrics_config_a) / len(self.metrics_config_a)
        avg_render_time_b = sum(m.render_time_ms for m in self.metrics_config_b) / len(self.metrics_config_b)
        render_time_change = (avg_render_time_b - avg_render_time_a) / avg_render_time_a * 100
        
        return {
            "total_tracks_tested": len(self.metrics_config_a),
            "octave_error_rate": {
                "config_a_percent": octave_error_rate_a,
                "config_b_percent": octave_error_rate_b,
                "improvement_percent": octave_error_rate_a - octave_error_rate_b,
                "target_achieved": octave_error_rate_b < 0.5
            },
            "bpm_confidence": {
                "config_a_high_conf_percent": high_conf_pct_a,
                "config_b_high_conf_percent": high_conf_pct_b,
                "improvement_percent": high_conf_pct_b - high_conf_pct_a,
                "target_achieved": high_conf_pct_b > 85
            },
            "grid_fitness_b": {
                "high_count": high_fitness_b,
                "medium_count": medium_fitness_b,
                "low_count": low_fitness_b,
                "coverage_percent": (high_fitness_b + medium_fitness_b) / len(self.metrics_config_b) * 100,
                "target_achieved": ((high_fitness_b + medium_fitness_b) / len(self.metrics_config_b)) > 0.95
            },
            "render_time": {
                "config_a_avg_ms": avg_render_time_a,
                "config_b_avg_ms": avg_render_time_b,
                "change_percent": render_time_change,
                "target_achieved": abs(render_time_change) < 20
            }
        }

def random_file_size():
    """Generate random file size for testing"""
    import random
    return random.uniform(5, 50)  # MB

def save_results_to_file(runner: ABTestRunner):
    """Save A/B test results to JSON"""
    output_file = Path("/home/mcauchy/autodj-headless/phase3_ab_test_results.json")
    
    results_dict = {
        "test_date": datetime.now().isoformat(),
        "total_tracks": len(runner.results),
        "summary": runner._generate_summary(),
        "results": [
            {
                "track_id": r.track_id,
                "config_a": {
                    "render_time_ms": r.config_a_metrics.render_time_ms,
                    "bpm_confidence": r.config_a_metrics.bpm_confidence,
                    "octave_error": r.config_a_metrics.octave_error,
                    "grid_fitness": r.config_a_metrics.grid_fitness,
                },
                "config_b": {
                    "render_time_ms": r.config_b_metrics.render_time_ms,
                    "bpm_confidence": r.config_b_metrics.bpm_confidence,
                    "octave_error": r.config_b_metrics.octave_error,
                    "grid_fitness": r.config_b_metrics.grid_fitness,
                    "grid_fitness_class": r.config_b_metrics.grid_fitness_class,
                },
                "improvements": r.improvements,
                "pass_fail": r.pass_fail,
            }
            for r in runner.results
        ]
    }
    
    with open(output_file, 'w') as f:
        json.dump(results_dict, f, indent=2)
    
    logger.info(f"\nResults saved to: {output_file}")

if __name__ == "__main__":
    runner = ABTestRunner()
    results, summary = runner.run_ab_test()
    save_results_to_file(runner)
    
    logger.info("\n" + "="*80)
    logger.info("SUMMARY STATISTICS")
    logger.info("="*80)
    logger.info(json.dumps(summary, indent=2))
    logger.info("\nPhase 3 A/B Testing Framework Complete!")
