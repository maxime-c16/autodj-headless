#!/usr/bin/env python3
"""
Performance & Edge Case Testing for Fixes

Validates:
1. No memory bloat from fixes
2. Edge cases are handled
3. Performance metrics are acceptable
4. Real-world scenarios work
"""

import logging
import numpy as np
import sys
import time
from unittest.mock import patch

sys.path.insert(0, '/home/mcauchy/autodj-headless/src')

from autodj.analyze.bpm import detect_bpm, _normalize_bpm
from autodj.analyze.structure import _compute_loop_stability

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """Track performance metrics"""
    
    def __init__(self):
        self.measurements = {}
    
    def record(self, name, value, unit="ms"):
        if name not in self.measurements:
            self.measurements[name] = []
        self.measurements[name].append(value)
        logger.info(f"  {name}: {value:.3f} {unit}")
    
    def summary(self):
        print("\nPerformance Summary:")
        for name, values in self.measurements.items():
            avg = np.mean(values)
            min_val = np.min(values)
            max_val = np.max(values)
            print(f"  {name}:")
            print(f"    Average: {avg:.3f} ms")
            print(f"    Min: {min_val:.3f} ms, Max: {max_val:.3f} ms")


def test_bpm_normalization_edge_cases():
    """Test BPM normalization with extreme values"""
    print("\n" + "="*60)
    print("TEST: BPM Normalization Edge Cases")
    print("="*60)
    
    test_cases = [
        (30, "Very low BPM (half-tempo)"),
        (60, "Half-tempo (120 BPM track)"),
        (85, "Low boundary"),
        (120, "Standard electronic"),
        (150, "Fast electronic"),
        (175, "High boundary"),
        (240, "Double-tempo (120 BPM track)"),
        (300, "Very high BPM (double-tempo of 150)"),
    ]
    
    metrics = PerformanceMetrics()
    
    for bpm, description in test_cases:
        start = time.time()
        result = _normalize_bpm(bpm)
        elapsed = (time.time() - start) * 1000
        
        assert 85 <= result <= 175, f"BPM {result} out of range for {description}"
        logger.info(f"✅ {description}: {bpm} → {result:.1f} BPM")
        metrics.record(f"normalize({bpm})", elapsed)
    
    metrics.summary()


def test_stability_performance():
    """Test stability calculation performance with various sizes"""
    print("\n" + "="*60)
    print("TEST: Stability Calculation Performance")
    print("="*60)
    
    test_sizes = [
        (1000, "Very short (23ms)"),
        (22050, "Short (0.5s)"),
        (44100, "Medium (1s)"),
        (220500, "Long (5s)"),
        (441000, "Very long (10s)"),
    ]
    
    metrics = PerformanceMetrics()
    
    for size, description in test_sizes:
        # Create test audio
        audio1 = np.sin(2*np.pi*np.arange(size)*440/44100).astype(np.float32)
        audio2 = np.sin(2*np.pi*np.arange(size)*440/44100).astype(np.float32)
        
        start = time.time()
        stability = _compute_loop_stability(audio1, audio2)
        elapsed = (time.time() - start) * 1000
        
        assert 0 <= stability <= 1, f"Stability {stability} out of range"
        logger.info(f"✅ {description}: stability={stability:.4f}")
        metrics.record(f"stability({description})", elapsed)
    
    metrics.summary()


def test_edge_case_scenarios():
    """Test real-world edge cases"""
    print("\n" + "="*60)
    print("TEST: Real-World Edge Cases")
    print("="*60)
    
    # Case 1: Silent track
    logger.info("\n1️⃣  Silent Track (should detect BPM as None or fallback)")
    config = {"confidence_threshold": 0.01}
    with patch('autodj.analyze.bpm._detect_bpm_aubio', return_value=None):
        with patch('autodj.analyze.bpm._detect_bpm_essentia', return_value=None):
            result = detect_bpm('/fake/path.mp3', config)
            assert result is None, "Silent track should fail BPM detection"
            logger.info("✅ Silent track correctly returns None BPM")
    
    # Case 2: Very low BPM (techno subgenre)
    logger.info("\n2️⃣  Low BPM Track (80 BPM)")
    with patch('autodj.analyze.bpm._detect_bpm_aubio', return_value=(80.0, 0.7)):
        with patch('autodj.analyze.bpm._detect_bpm_essentia', return_value=None):
            result = detect_bpm('/fake/path.mp3', config)
            # 80 might get normalized to 160 then back to 80, or stay at 80
            assert result is not None, "80 BPM is valid DJ BPM"
            assert 80 <= result <= 160, f"Expected 80-160 BPM, got {result}"
            logger.info(f"✅ Low BPM track: {result:.1f} BPM")
    
    # Case 3: Very high BPM (120 BPM detected as 240)
    logger.info("\n3️⃣  Double-Tempo Detection (240 BPM detected for 120 BPM track)")
    with patch('autodj.analyze.bpm._detect_bpm_aubio', return_value=(240.0, 0.6)):
        with patch('autodj.analyze.bpm._detect_bpm_essentia', return_value=None):
            result = detect_bpm('/fake/path.mp3', config)
            assert result is not None, "Should normalize double-tempo"
            assert 115 <= result <= 125, f"Expected ~120 BPM (half of 240), got {result}"
            logger.info(f"✅ Double-tempo normalized: 240 → {result:.1f} BPM")
    
    # Case 4: Constant signal (0 variance - causes NaN in corrcoef)
    logger.info("\n4️⃣  Constant Signal (zero variance - np.corrcoef returns NaN)")
    audio_const = np.ones(22050, dtype=np.float32)
    stability = _compute_loop_stability(audio_const, audio_const)
    assert not np.isnan(stability), "Should not return NaN for constant signal"
    assert 0 <= stability <= 1, f"Stability out of range: {stability}"
    logger.info(f"✅ Constant signal stability: {stability:.4f} (no NaN)")
    
    # Case 5: Mixed signal (high energy with noise)
    logger.info("\n5️⃣  High-Energy Mixed Signal")
    high_energy = np.sin(2*np.pi*np.arange(22050)*440/44100)
    high_energy += 0.5*np.sin(2*np.pi*np.arange(22050)*880/44100)
    high_energy += 0.1*np.random.randn(22050)
    high_energy = high_energy.astype(np.float32)
    
    stability = _compute_loop_stability(high_energy[:22050], high_energy[22050:44100] if len(high_energy) > 22050 else high_energy[:22050])
    assert not np.isnan(stability), "Should not return NaN for high-energy signal"
    logger.info(f"✅ High-energy mixed signal stability: {stability:.4f} (no NaN)")
    
    # Case 6: Very short segments
    logger.info("\n6️⃣  Very Short Segments (< 1ms)")
    short1 = np.array([0.1], dtype=np.float32)
    short2 = np.array([0.1], dtype=np.float32)
    stability = _compute_loop_stability(short1, short2)
    assert not np.isnan(stability), "Short segments should work"
    logger.info(f"✅ Short segments stability: {stability:.4f}")


def test_memory_constraints():
    """Verify memory usage stays within 512MB container limit"""
    print("\n" + "="*60)
    print("TEST: Memory Constraints (512MB Container)")
    print("="*60)
    
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    
    # Baseline
    baseline = process.memory_info().rss / 1024 / 1024
    logger.info(f"Baseline memory: {baseline:.1f} MB")
    
    # Process large stability calculations
    logger.info("Processing 100 stability calculations...")
    for i in range(100):
        audio1 = np.random.randn(44100).astype(np.float32)
        audio2 = np.random.randn(44100).astype(np.float32)
        _compute_loop_stability(audio1, audio2)
    
    peak = process.memory_info().rss / 1024 / 1024
    increase = peak - baseline
    
    logger.info(f"Peak memory: {peak:.1f} MB")
    logger.info(f"Memory increase: {increase:.1f} MB")
    
    # Should use less than 50MB additional
    assert increase < 50, f"Memory usage exceeds limit: {increase:.1f} MB > 50 MB"
    logger.info(f"✅ Memory usage acceptable: {increase:.1f} MB < 50 MB")


def test_bpm_analysis_scenarios():
    """Test various BPM analysis scenarios"""
    print("\n" + "="*60)
    print("TEST: BPM Analysis Scenarios")
    print("="*60)
    
    scenarios = [
        {
            "name": "Reliable detection (high confidence)",
            "aubio": (120.0, 0.8),
            "essentia": None,
            "expected": (115, 125),
        },
        {
            "name": "Low confidence fallback to essentia",
            "aubio": (60.0, 0.1),
            "essentia": (120.0, 0.7),
            "expected": (115, 125),
        },
        {
            "name": "Both methods available, essentia better",
            "aubio": (120.0, 0.4),
            "essentia": (120.0, 0.8),
            "expected": (115, 125),
        },
        {
            "name": "Very low confidence (with fix) still accepted",
            "aubio": (120.0, 0.01),
            "essentia": None,
            "expected": (115, 125),
        },
    ]
    
    config = {"confidence_threshold": 0.01}
    
    for scenario in scenarios:
        logger.info(f"\n📍 {scenario['name']}")
        
        with patch('autodj.analyze.bpm._detect_bpm_aubio', return_value=scenario['aubio']):
            with patch('autodj.analyze.bpm._detect_bpm_essentia', return_value=scenario['essentia']):
                with patch('os.path.getsize', return_value=10*1024*1024):
                    result = detect_bpm('/fake/path.mp3', config)
        
        if scenario['expected']:
            min_bpm, max_bpm = scenario['expected']
            assert result is not None, f"Should detect BPM for {scenario['name']}"
            assert min_bpm <= result <= max_bpm, f"BPM {result} not in {scenario['expected']}"
            logger.info(f"  ✅ BPM: {result:.1f}")
        else:
            assert result is None, f"Should not detect BPM for {scenario['name']}"
            logger.info(f"  ✅ Correctly returned None")


def run_all_tests():
    """Run all performance and edge case tests"""
    print("\n" + "="*70)
    print("PERFORMANCE & EDGE CASE TEST SUITE")
    print("="*70)
    
    test_functions = [
        test_bpm_normalization_edge_cases,
        test_stability_performance,
        test_edge_case_scenarios,
        test_bpm_analysis_scenarios,
        test_memory_constraints,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in test_functions:
        try:
            test_func()
            passed += 1
        except Exception as e:
            logger.error(f"❌ {test_func.__name__}: {e}")
            failed += 1
    
    print("\n" + "="*70)
    print(f"RESULTS: {passed}/{len(test_functions)} test suites passed")
    print("="*70 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
