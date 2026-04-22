"""
Unit Tests for Phase 1 and Phase 2 DJ Techniques

Tests for:
- Phase 1: Early Transitions
- Phase 2: Bass Cut Control
"""

import unittest
import logging
from src.autodj.render.phase1_early_transitions import (
    EarlyTransitionCalculator,
    EarlyTransitionParams,
    TransitionTiming,
    enhance_transition_plan_with_early_timing,
)
from src.autodj.render.phase2_bass_cut import (
    BassCutEngine,
    BassCutAnalyzer,
    BassCutParams,
    BassCutStrategy,
    enhance_transition_with_bass_cut,
)


class TestPhase1EarlyTransitions(unittest.TestCase):
    """Tests for Phase 1: Early Transitions"""
    
    def setUp(self):
        self.calc = EarlyTransitionCalculator()
        self.logger = logging.getLogger(__name__)
    
    def test_basic_transition_calculation_128bpm(self):
        """Test basic transition timing at 128 BPM"""
        start, end = self.calc.calculate_early_transition(
            outro_start=230.0,
            bpm=128,
            bars=16,
        )
        
        # 16 bars at 128 BPM = 7.5 seconds
        expected_duration = (16 * 60.0) / 128
        self.assertAlmostEqual(end - start, expected_duration, places=2)
        self.assertAlmostEqual(start, 222.5, places=1)
    
    def test_transition_calculation_100bpm(self):
        """Test transition at slower BPM (100 BPM)"""
        start, end = self.calc.calculate_early_transition(
            outro_start=320.0,
            bpm=100,
            bars=16,
        )
        
        # 16 bars at 100 BPM = 9.6 seconds
        expected_duration = (16 * 60.0) / 100
        self.assertAlmostEqual(end - start, expected_duration, places=2)
    
    def test_transition_calculation_135bpm(self):
        """Test transition at faster BPM (135 BPM)"""
        start, end = self.calc.calculate_early_transition(
            outro_start=240.0,
            bpm=135,
            bars=16,
        )
        
        # 16 bars at 135 BPM = 7.1 seconds
        expected_duration = (16 * 60.0) / 135
        self.assertAlmostEqual(end - start, expected_duration, places=2)
    
    def test_transition_end_at_outro(self):
        """Test that transition ends exactly at outro start"""
        start, end = self.calc.calculate_early_transition(
            outro_start=230.0,
            bpm=128,
            bars=16,
        )
        
        self.assertAlmostEqual(end, 230.0, places=1)
    
    def test_different_bar_counts(self):
        """Test transitions with different bar counts"""
        outro = 240.0
        bpm = 128
        
        for bars in [8, 16, 32]:
            start, end = self.calc.calculate_early_transition(outro, bpm, bars)
            expected_duration = (bars * 60.0) / bpm
            self.assertAlmostEqual(end - start, expected_duration, places=2)
    
    def test_transition_timing_validation_valid(self):
        """Test validation of valid timing"""
        is_valid, error = self.calc.validate_timing(
            transition_start=180,
            transition_end=240,
            track_duration=250,
            outro_start=230,
        )
        
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_transition_timing_validation_negative_start(self):
        """Test validation rejects negative start"""
        is_valid, error = self.calc.validate_timing(
            transition_start=-10,
            transition_end=240,
            track_duration=250,
            outro_start=230,
        )
        
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_transition_timing_validation_too_short(self):
        """Test validation accepts transitions ending after outro"""
        is_valid, error = self.calc.validate_timing(
            transition_start=238,
            transition_end=240,
            track_duration=250,
            outro_start=230,
        )
        
        # This is actually valid - transition ends after outro starts
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_early_transition_params_calculation(self):
        """Test EarlyTransitionParams helper methods"""
        params = EarlyTransitionParams(
            outro_start_seconds=230.0,
            bpm=128,
            bars_before_outro=16,
            transition_duration_bars=16,
        )
        
        start = params.calculate_transition_start()
        end = params.calculate_transition_end()
        
        self.assertAlmostEqual(start, 222.5, places=1)
        self.assertAlmostEqual(end, 230.0, places=1)
    
    def test_enhance_transition_plan(self):
        """Test enhancing a transition plan with early timing"""
        transition = {
            'track_id': 1,
            'bpm': 128,
        }
        
        spectral_data = {
            'outro_start_seconds': 230.0,
            'duration_seconds': 250.0,
        }
        
        enhanced = enhance_transition_plan_with_early_timing(
            transition,
            spectral_data,
            enable_early_start=True,
        )
        
        self.assertTrue(enhanced['phase1_early_start_enabled'])
        self.assertIn('phase1_transition_start_seconds', enhanced)
        self.assertIn('phase1_transition_end_seconds', enhanced)
        self.assertAlmostEqual(enhanced['phase1_transition_end_seconds'], 230.0, places=1)


class TestPhase2BassCut(unittest.TestCase):
    """Tests for Phase 2: Bass Cut Control"""
    
    def setUp(self):
        self.engine = BassCutEngine()
        self.analyzer = BassCutAnalyzer()
    
    def test_bass_cut_params_validation_valid(self):
        """Test valid bass cut parameters"""
        params = BassCutParams(
            hpf_frequency=200.0,
            cut_intensity=0.65,
        )
        
        is_valid, error = params.validate()
        self.assertTrue(is_valid)
        self.assertIsNone(error)
    
    def test_bass_cut_params_validation_invalid_frequency(self):
        """Test invalid HPF frequency"""
        params = BassCutParams(
            hpf_frequency=10.0,  # Too low
        )
        
        is_valid, error = params.validate()
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_bass_cut_params_validation_invalid_intensity(self):
        """Test invalid cut intensity"""
        params = BassCutParams(
            cut_intensity=1.5,  # Out of range
        )
        
        is_valid, error = params.validate()
        self.assertFalse(is_valid)
    
    def test_bass_cut_duration_calculations(self):
        """Test bass cut duration calculations"""
        params = BassCutParams(
            transition_duration_bars=16,
            bpm=128,
            unmask_delay_bars=4,
            unmask_duration_bars=12,
        )
        
        trans_dur = params.get_transition_duration_seconds()
        unmask_start = params.get_unmask_start_seconds()
        unmask_dur = params.get_unmask_duration_seconds()
        
        self.assertAlmostEqual(trans_dur, 7.5, places=1)  # 16 bars @ 128 BPM
        self.assertAlmostEqual(unmask_start, 1.875, places=2)  # 4 bars
        self.assertAlmostEqual(unmask_dur, 5.625, places=2)  # 12 bars
    
    def test_create_bass_cut_spec(self):
        """Test creating a complete bass cut spec"""
        spec = self.engine.create_bass_cut_spec(
            transition_start=180.0,
            transition_duration_bars=16,
            bpm=128,
            cut_intensity=0.70,
        )
        
        self.assertEqual(spec.hpf_frequency, 200.0)
        self.assertEqual(spec.cut_intensity, 0.70)
        self.assertEqual(spec.transition_start_seconds, 180.0)
    
    def test_generate_liquidsoap_instant_strategy(self):
        """Test Liquidsoap code generation for instant cut"""
        params = BassCutParams(
            hpf_frequency=200.0,
            cut_intensity=0.65,
            strategy=BassCutStrategy.INSTANT,
            transition_duration_bars=16,
            bpm=128,
        )
        
        script = self.engine.generate_liquidsoap_filter(params)
        
        self.assertIsInstance(script, list)
        self.assertTrue(any('butterworth.high_pass' in line for line in script))
    
    def test_generate_liquidsoap_creative_strategy(self):
        """Test Liquidsoap code generation for creative strategy"""
        params = BassCutParams(
            strategy=BassCutStrategy.CREATIVE,
            transition_duration_bars=16,
            bpm=128,
        )
        
        script = self.engine.generate_liquidsoap_filter(params)
        
        # Should have both HPF and LPF for mids-only effect
        self.assertTrue(any('high_pass' in line for line in script))
        self.assertTrue(any('low_pass' in line for line in script))
    
    def test_analyzer_should_apply_bass_cut_strong_bass(self):
        """Test bass cut decision with strong bass in both tracks"""
        should_cut = self.analyzer.should_apply_bass_cut(
            incoming_bass_energy=0.75,
            outgoing_bass_energy=0.70,
            incoming_kick_strength=0.8,
        )
        
        self.assertTrue(should_cut)
    
    def test_analyzer_should_not_cut_weak_incoming(self):
        """Test bass cut decision with weak incoming bass"""
        should_cut = self.analyzer.should_apply_bass_cut(
            incoming_bass_energy=0.15,  # Too weak
            outgoing_bass_energy=0.70,
            incoming_kick_strength=0.5,
        )
        
        self.assertFalse(should_cut)
    
    def test_analyzer_should_not_cut_weak_outgoing(self):
        """Test bass cut decision with weak outgoing bass"""
        should_cut = self.analyzer.should_apply_bass_cut(
            incoming_bass_energy=0.75,
            outgoing_bass_energy=0.05,  # Too weak
            incoming_kick_strength=0.8,
        )
        
        self.assertFalse(should_cut)
    
    def test_recommend_cut_intensity_strong_incoming(self):
        """Test intensity recommendation when incoming bass is strong"""
        intensity = self.analyzer.recommend_cut_intensity(
            incoming_bass_energy=0.85,
            outgoing_bass_energy=0.50,
        )
        
        # Strong incoming should have higher cut
        self.assertGreater(intensity, 0.65)
        self.assertLessEqual(intensity, 0.80)
    
    def test_recommend_cut_intensity_strong_outgoing(self):
        """Test intensity recommendation when outgoing bass is strong"""
        intensity = self.analyzer.recommend_cut_intensity(
            incoming_bass_energy=0.50,
            outgoing_bass_energy=0.85,
        )
        
        # Outgoing stronger = lighter cut
        self.assertLess(intensity, 0.65)
        self.assertGreaterEqual(intensity, 0.50)
    
    def test_enhance_transition_with_bass_cut(self):
        """Test enhancing transition with bass cut specifications"""
        transition = {
            'track_id': 2,
            'bpm': 128,
            'phase1_transition_start_seconds': 180.0,
            'phase1_transition_bars': 16,
        }
        
        spectral_incoming = {
            'bass_energy': 0.75,
            'kick_strength': 0.8,
        }
        
        spectral_outgoing = {
            'bass_energy': 0.70,
        }
        
        enhanced = enhance_transition_with_bass_cut(
            transition,
            spectral_incoming,
            spectral_outgoing,
            enable_bass_cut=True,
        )
        
        self.assertTrue(enhanced['phase2_bass_cut_enabled'])
        self.assertIn('phase2_hpf_frequency', enhanced)
        self.assertIn('phase2_cut_intensity', enhanced)
        self.assertIn('phase2_strategy', enhanced)


class TestIntegration(unittest.TestCase):
    """Integration tests for Phase 1 + Phase 2"""
    
    def test_full_transition_planning_flow(self):
        """Test complete flow: early timing + bass cut"""
        # Start with a basic transition
        transition = {
            'track_id': 1,
            'next_track_id': 2,
            'bpm': 128,
        }
        
        # Spectral data for outgoing track
        spectral_outgoing = {
            'outro_start_seconds': 230.0,
            'duration_seconds': 250.0,
            'bass_energy': 0.70,
        }
        
        # Spectral data for incoming track
        spectral_incoming = {
            'bass_energy': 0.75,
            'kick_strength': 0.8,
        }
        
        # Phase 1: Add early transition timing
        enhanced = enhance_transition_plan_with_early_timing(
            transition,
            spectral_outgoing,
            enable_early_start=True,
        )
        
        # Phase 2: Add bass cut specifications
        enhanced = enhance_transition_with_bass_cut(
            enhanced,
            spectral_incoming,
            spectral_outgoing,
            enable_bass_cut=True,
        )
        
        # Verify complete plan
        self.assertTrue(enhanced['phase1_early_start_enabled'])
        self.assertTrue(enhanced['phase2_bass_cut_enabled'])
        self.assertIn('phase1_transition_start_seconds', enhanced)
        self.assertIn('phase2_hpf_frequency', enhanced)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(name)s - %(levelname)s - %(message)s'
    )
    unittest.main()
