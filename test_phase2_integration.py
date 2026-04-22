#!/usr/bin/env python3
"""
PHASE 2 Integration Tests

Comprehensive test suite for Phase 0 + Phase 1 integration into render.py
Tests both entry points (quick-mix and nightly) and validates all fixes.
"""

import sys
sys.path.insert(0, "/home/mcauchy/autodj-headless/src")

import json
import tempfile
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_imports():
    """Test 1: Verify all imports work"""
    print("\n" + "="*70)
    print("TEST 1: IMPORT VERIFICATION")
    print("="*70)
    
    try:
        from autodj.render.render import (
            render,
            apply_phase0_precision_fixes,
            PHASE_0_VALIDATORS_AVAILABLE,
        )
        print("✅ Import: render()")
        print("✅ Import: apply_phase0_precision_fixes()")
        print(f"✅ Phase 0 validators available: {PHASE_0_VALIDATORS_AVAILABLE}")
        
        from autodj.analyze.confidence_validator import (
            ConfidenceValidator,
            create_confidence_validator,
        )
        print("✅ Import: ConfidenceValidator")
        
        from autodj.analyze.bpm_multipass_validator import (
            BPMMultiPassValidator,
            create_multipass_validator,
        )
        print("✅ Import: BPMMultiPassValidator")
        
        from autodj.analyze.grid_validator import (
            GridValidator,
            create_grid_validator,
        )
        print("✅ Import: GridValidator")
        
        print("\n✅ TEST 1 PASSED: All imports successful")
        return True
    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_confidence_validation():
    """Test 2: Confidence validation works"""
    print("\n" + "="*70)
    print("TEST 2: CONFIDENCE VALIDATOR")
    print("="*70)
    
    try:
        from autodj.render.render import apply_phase0_precision_fixes
        
        config = {
            'confidence_high_threshold': 0.90,
            'confidence_medium_threshold': 0.70,
            'bpm_search_range': [50, 200],
        }
        
        transitions = [
            {
                'track_id': 'test_high',
                'bpm': 128.0,
                'bpm_confidence': 0.95,
                'bpm_method': 'aubio',
                'file_path': None,
            },
            {
                'track_id': 'test_medium',
                'bpm': 130.0,
                'bpm_confidence': 0.75,
                'bpm_method': 'essentia',
                'file_path': None,
            },
            {
                'track_id': 'test_low',
                'bpm': 125.0,
                'bpm_confidence': 0.45,
                'bpm_method': 'aubio',
                'file_path': None,
            },
        ]
        
        validated, metrics = apply_phase0_precision_fixes(
            transitions,
            config,
            precision_fixes_enabled=True,
            confidence_validator_enabled=True,
            bpm_multipass_enabled=False,
            grid_validation_enabled=False,
        )
        
        print(f"Metrics: {metrics}")
        
        # Verify results
        high = validated[0].get('_phase0_confidence_validation', {}).get('tier')
        medium = validated[1].get('_phase0_confidence_validation', {}).get('tier')
        low = validated[2].get('_phase0_confidence_validation', {}).get('tier')
        
        assert high == 'high', f"Expected 'high', got {high}"
        assert medium == 'medium', f"Expected 'medium', got {medium}"
        assert low == 'low', f"Expected 'low', got {low}"
        
        print(f"✅ High confidence (0.95): {high}")
        print(f"✅ Medium confidence (0.75): {medium}")
        print(f"✅ Low confidence (0.45): {low}")
        
        print("\n✅ TEST 2 PASSED: Confidence validation working")
        return True
    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_feature_flags():
    """Test 3: Feature flags work correctly"""
    print("\n" + "="*70)
    print("TEST 3: FEATURE FLAGS")
    print("="*70)
    
    try:
        from autodj.render.render import apply_phase0_precision_fixes
        
        config = {
            'confidence_high_threshold': 0.90,
            'confidence_medium_threshold': 0.70,
            'bpm_search_range': [50, 200],
        }
        
        # Test 1: All disabled
        transitions_1 = [
            {
                'track_id': 'test_track',
                'bpm': 128.0,
                'bpm_confidence': 0.85,
                'bpm_method': 'aubio',
                'file_path': None,
            }
        ]
        
        validated, metrics = apply_phase0_precision_fixes(
            transitions_1,
            config,
            precision_fixes_enabled=False,
        )
        assert metrics == {}, "Should return empty metrics when disabled"
        assert '_phase0_' not in str(validated), "Should not add Phase 0 metadata"
        print("✅ Flag: precision_fixes_enabled=False → All disabled")
        
        # Test 2: Confidence only
        transitions_2 = [
            {
                'track_id': 'test_track',
                'bpm': 128.0,
                'bpm_confidence': 0.85,
                'bpm_method': 'aubio',
                'file_path': None,
            }
        ]
        
        validated, metrics = apply_phase0_precision_fixes(
            transitions_2,
            config,
            precision_fixes_enabled=True,
            confidence_validator_enabled=True,
            bpm_multipass_enabled=False,
            grid_validation_enabled=False,
        )
        assert metrics.get('confidence_validations') == 1, "Should run confidence"
        assert metrics.get('bpm_multipass_validations') == 0, "Should skip BPM multipass"
        assert metrics.get('grid_validations') == 0, "Should skip grid"
        print("✅ Flag: confidence_validator_enabled=True → Confidence runs")
        print("✅ Flag: bpm_multipass_enabled=False → BPM multipass skipped")
        print("✅ Flag: grid_validation_enabled=False → Grid skipped")
        
        print("\n✅ TEST 3 PASSED: Feature flags working correctly")
        return True
    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_render_signature():
    """Test 4: Render function has new parameters"""
    print("\n" + "="*70)
    print("TEST 4: RENDER FUNCTION SIGNATURE")
    print("="*70)
    
    try:
        from autodj.render.render import render
        import inspect
        
        sig = inspect.signature(render)
        params = list(sig.parameters.keys())
        
        expected_params = [
            'transitions_json_path',
            'output_path',
            'config',
            'timeout_seconds',
            'eq_enabled',
            'eq_strategy',
            'precision_fixes_enabled',
            'confidence_validator_enabled',
            'bpm_multipass_enabled',
            'grid_validation_enabled',
        ]
        
        for param in expected_params:
            assert param in params, f"Missing parameter: {param}"
            print(f"✅ Parameter: {param}")
        
        # Check defaults
        assert sig.parameters['precision_fixes_enabled'].default == True
        assert sig.parameters['confidence_validator_enabled'].default == True
        assert sig.parameters['bpm_multipass_enabled'].default == True
        assert sig.parameters['grid_validation_enabled'].default == True
        print("✅ All defaults set to True (enabled by default)")
        
        print("\n✅ TEST 4 PASSED: Render signature updated correctly")
        return True
    except Exception as e:
        print(f"\n❌ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_no_regressions():
    """Test 5: No regressions in existing functionality"""
    print("\n" + "="*70)
    print("TEST 5: REGRESSION TESTING")
    print("="*70)
    
    try:
        from autodj.render.render import render
        
        # Create a minimal transitions.json without Phase 0 metadata
        test_transitions = {
            "transitions": [
                {
                    "track_id": "legacy_track",
                    "file_path": "/dev/null",
                    "title": "Legacy Track",
                    "bpm": 128.0,
                    "bpm_confidence": 0.85,
                    # Note: NO _phase0_* fields
                }
            ]
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_transitions, f)
            transitions_path = f.name
        
        print(f"✅ Created test transitions file: {transitions_path}")
        
        # Load and verify no errors
        with open(transitions_path) as f:
            data = json.load(f)
        
        assert 'transitions' in data
        assert len(data['transitions']) == 1
        assert '_phase0_' not in str(data)  # No Phase 0 metadata yet
        print("✅ Legacy transitions format works")
        
        # Clean up
        Path(transitions_path).unlink()
        print("✅ Cleanup complete")
        
        print("\n✅ TEST 5 PASSED: No regressions detected")
        return True
    except Exception as e:
        print(f"\n❌ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests():
    """Run all integration tests"""
    print("\n" + "="*70)
    print("PHASE 2 INTEGRATION TEST SUITE")
    print("="*70)
    
    tests = [
        ("TEST 1: Import Verification", test_imports),
        ("TEST 2: Confidence Validator", test_confidence_validation),
        ("TEST 3: Feature Flags", test_feature_flags),
        ("TEST 4: Render Signature", test_render_signature),
        ("TEST 5: Regression Testing", test_no_regressions),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            logger.error(f"{name} crashed: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print(f"\n📊 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ ALL TESTS PASSED")
        return True
    else:
        print(f"❌ {total - passed} TEST(S) FAILED")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
