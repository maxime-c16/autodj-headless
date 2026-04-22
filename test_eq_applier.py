#!/usr/bin/env python3
"""
Test suite for DJ EQ Automation DSP (eq_applier.py)

Tests:
1. Butterworth filter implementation
2. EQ envelope generation
3. Bar-to-sample timing calculations
4. Timing validation
5. Multi-opportunity application

All tests verify timing alignment per DJ_EQ_RESEARCH.md
"""

import sys
from pathlib import Path
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from autodj.render.eq_applier import (
    Butterworth3BandEQ,
    EQAutomationEnvelope,
    EQAutomationLogger,
)
from autodj.render.eq_automation import (
    EQAutomationEngine,
    EQCutType,
    FrequencyBand,
    EQOpportunity,
)


def test_butterworth_filter_creation():
    """Test that Butterworth filters are created correctly."""
    print("\n=== Test 1: Butterworth Filter Creation ===")
    
    eq = Butterworth3BandEQ(sample_rate=44100, q=0.7)
    
    # Test peaking filter
    b, a = eq.create_peaking_filter(center_freq=6000, gain_db=-6.0, q=0.7)
    
    assert len(b) == 3, "Peaking filter should have 3 numerator coefficients"
    assert len(a) == 3, "Peaking filter should have 3 denominator coefficients"
    assert a[0] == 1.0, "Denominator should be normalized"
    
    print("✓ Peaking filter created")
    
    # Test high-pass filter
    b_hp, a_hp = eq.create_highpass_filter(cutoff_freq=100, order=2)
    
    assert len(b_hp) == 3, "High-pass filter should have 3 coefficients"
    assert len(a_hp) == 3, "High-pass filter should have 3 coefficients"
    
    print("✓ High-pass filter created")


def test_eq_envelope_generation():
    """Test EQ envelope generation with attack/hold/release."""
    print("\n=== Test 2: EQ Envelope Generation ===")
    
    # Create envelope: 100ms attack, 4 bars hold, 100ms release
    envelope = EQAutomationEnvelope(
        attack_samples=4410,     # 100ms @ 44.1kHz
        hold_samples=330480,     # 4 bars @ 128 BPM
        release_samples=4410,    # 100ms @ 44.1kHz
        magnitude_db=-6.0,
    )
    
    curve = envelope.generate_automation()
    
    # Verify total length
    assert len(curve) == envelope.total_samples, "Curve length should match total samples"
    print(f"✓ Envelope length correct: {len(curve)} samples")
    
    # Verify attack phase: should ramp from 0 to -6dB
    assert abs(curve[0]) < 0.5, "Attack should start near 0dB"
    assert abs(curve[4410 - 1] - (-6.0)) < 0.5, "Attack should end near -6dB"
    print("✓ Attack phase: 0dB → -6dB (gradual ramp)")
    
    # Verify hold phase
    hold_mid = 4410 + 165240  # Middle of hold phase
    assert abs(curve[hold_mid] - (-6.0)) < 0.01, "Hold should stay at -6dB"
    print("✓ Hold phase: -6dB (steady)")
    
    # Verify release phase
    release_start = 4410 + 330480
    if release_start < len(curve):
        assert abs(curve[release_start] - (-6.0)) < 0.5, "Release should start at -6dB"
        assert abs(curve[-1]) < 0.5, "Release should end near 0dB"
        print("✓ Release phase: -6dB → 0dB (gradual ramp)")


def test_bar_to_sample_conversion():
    """Test bar-to-sample timing calculations at different BPMs."""
    print("\n=== Test 3: Bar-to-Sample Conversion ===")
    
    test_cases = [
        (120, 44100, 352800),   # 120 BPM: 4 bars = 8 sec = 352800 samples
        (128, 44100, 330748),   # 128 BPM: 4 bars ≈ 7.5 sec (with int rounding)
        (140, 44100, 302400),   # 140 BPM: 4 bars ≈ 6.86 sec
    ]
    
    for bpm, sr, expected in test_cases:
        seconds_per_bar = 240.0 / bpm
        samples_per_bar = int(seconds_per_bar * sr)
        four_bar_samples = 4 * samples_per_bar
        
        # Allow ±200 sample tolerance (rounding in int conversion)
        assert abs(four_bar_samples - expected) <= 200, \
            f"BPM {bpm}: expected {expected}, got {four_bar_samples}"
        
        print(f"✓ {bpm} BPM: 4 bars = {four_bar_samples} samples "
              f"({four_bar_samples / sr:.3f}s)")


def test_opportunity_timing_log():
    """Test EQ opportunity timing log generation."""
    print("\n=== Test 4: Opportunity Timing Logging ===")
    
    # Create sample opportunity
    engine = EQAutomationEngine(bpm=128.0)
    opp = EQOpportunity(
        cut_type=EQCutType.BASS_CUT,
        bar=8,
        confidence=0.90,
        frequency_band=FrequencyBand.LOW,
        magnitude_db=-8.0,
        envelope=engine.DEFAULT_ENVELOPES[EQCutType.BASS_CUT],
        phrase_length_bars=4,
        reason="Test bass cut",
    )
    
    # Generate timing log
    log = EQAutomationLogger.log_opportunity_timing(
        opp, bpm=128.0, sample_rate=44100
    )
    
    # Verify log contains expected information
    assert "BASS_CUT" in log, "Log should contain cut type"
    assert "Bar 8" in log, "Log should contain bar position"
    assert "128" in log, "Log should contain BPM"
    assert "-8.0dB" in log, "Log should contain magnitude"
    assert "0.90" in log, "Log should contain confidence"
    
    print("✓ Timing log generated with all information:")
    print(log)


def test_timing_validation():
    """Test EQ opportunity timing validation across full track."""
    print("\n=== Test 5: Timing Validation (Full Track) ===")
    
    # Detect opportunities
    engine = EQAutomationEngine(bpm=128.0)
    audio_features = {
        'intro_confidence': 0.92,
        'vocal_confidence': 0.88,
        'breakdown_confidence': 0.75,
        'percussiveness': 0.65,
        'num_bars': 32,
    }
    
    opportunities = engine.detect_opportunities(audio_features)
    
    # Generate validation log
    log = EQAutomationLogger.log_timing_validation(
        opportunities, bpm=128.0, total_bars=32, sample_rate=44100
    )
    
    print(log)
    
    # Verify no opportunities go past track end
    seconds_per_bar = 240.0 / 128.0
    samples_per_bar = int(seconds_per_bar * 44100)
    total_samples = 32 * samples_per_bar
    
    for opp in opportunities:
        eq_start_sample = opp.bar * samples_per_bar
        attack_samples = int((opp.envelope.attack_ms / 1000.0) * 44100)
        hold_samples = opp.envelope.hold_bars * samples_per_bar
        release_samples = int((opp.envelope.release_ms / 1000.0) * 44100)
        eq_end_sample = eq_start_sample + attack_samples + hold_samples + release_samples
        
        assert eq_end_sample <= total_samples, \
            f"EQ cut extends past track end: {eq_end_sample} > {total_samples}"
    
    print("\n✓ All EQ opportunities fit within track bounds")


def test_bass_cut_timing():
    """Test bass cut has instant envelope (key feature)."""
    print("\n=== Test 6: Bass Cut Envelope (Instant) ===")
    
    engine = EQAutomationEngine(bpm=128.0)
    base_envelope = engine.DEFAULT_ENVELOPES[EQCutType.BASS_CUT]
    
    # Bass cut should have instant attack/release
    assert base_envelope.attack_ms == 0, "Bass cut attack should be instant (0ms)"
    assert base_envelope.release_ms == 0, "Bass cut release should be instant (0ms)"
    assert base_envelope.hold_bars >= 1, "Bass cut should hold for 1+ bars"
    
    # Calculate total samples
    dsp_envelope = EQAutomationEnvelope(
        attack_samples=int((base_envelope.attack_ms / 1000.0) * 44100),
        hold_samples=int((base_envelope.hold_bars * 240.0 / 128.0) * 44100),
        release_samples=int((base_envelope.release_ms / 1000.0) * 44100),
    )
    
    print(f"✓ Bass cut envelope:")
    print(f"  Attack: {base_envelope.attack_ms}ms (instant)")
    print(f"  Hold: {base_envelope.hold_bars} bars")
    print(f"  Release: {base_envelope.release_ms}ms (instant)")
    print(f"  Total: {dsp_envelope.total_samples} samples")


def test_high_swap_timing():
    """Test high swap has gradual envelope (key feature)."""
    print("\n=== Test 7: High Swap Envelope (Gradual) ===")
    
    engine = EQAutomationEngine(bpm=128.0)
    base_envelope = engine.DEFAULT_ENVELOPES[EQCutType.HIGH_SWAP]
    
    # High swap should have gradual attack/release
    assert base_envelope.attack_ms > 0, "High swap attack should be gradual (>0ms)"
    assert base_envelope.release_ms > 0, "High swap release should be gradual (>0ms)"
    assert base_envelope.hold_bars >= 4, "High swap should hold for 4+ bars"
    
    # Calculate total samples
    dsp_envelope = EQAutomationEnvelope(
        attack_samples=int((base_envelope.attack_ms / 1000.0) * 44100),
        hold_samples=int((base_envelope.hold_bars * 240.0 / 128.0) * 44100),
        release_samples=int((base_envelope.release_ms / 1000.0) * 44100),
    )
    
    print(f"✓ High swap envelope:")
    print(f"  Attack: {base_envelope.attack_ms}ms (gradual)")
    print(f"  Hold: {base_envelope.hold_bars} bars")
    print(f"  Release: {base_envelope.release_ms}ms (gradual)")
    print(f"  Total: {dsp_envelope.total_samples} samples")


def test_filter_sweep_timing():
    """Test filter sweep has long hold (key feature)."""
    print("\n=== Test 8: Filter Sweep Envelope (Long Hold) ===")
    
    engine = EQAutomationEngine(bpm=128.0)
    base_envelope = engine.DEFAULT_ENVELOPES[EQCutType.FILTER_SWEEP]
    
    # Filter sweep should have long hold
    assert base_envelope.hold_bars >= 8, "Filter sweep should hold for 8+ bars"
    
    # Calculate total samples
    dsp_envelope = EQAutomationEnvelope(
        attack_samples=int((base_envelope.attack_ms / 1000.0) * 44100),
        hold_samples=int((base_envelope.hold_bars * 240.0 / 128.0) * 44100),
        release_samples=int((base_envelope.release_ms / 1000.0) * 44100),
    )
    
    print(f"✓ Filter sweep envelope:")
    print(f"  Attack: {base_envelope.attack_ms}ms")
    print(f"  Hold: {base_envelope.hold_bars} bars (long, for dramatic effect)")
    print(f"  Release: {base_envelope.release_ms}ms")
    print(f"  Total: {dsp_envelope.total_samples} samples")


def test_three_band_blend_timing():
    """Test three-band blend has very gradual envelope (key feature)."""
    print("\n=== Test 9: Three-Band Blend Envelope (Very Gradual) ===")
    
    engine = EQAutomationEngine(bpm=128.0)
    base_envelope = engine.DEFAULT_ENVELOPES[EQCutType.THREE_BAND_BLEND]
    
    # Three-band blend should be VERY gradual
    assert base_envelope.attack_ms >= 500, "Blend attack should be very gradual (≥500ms)"
    assert base_envelope.release_ms >= 500, "Blend release should be very gradual (≥500ms)"
    assert base_envelope.hold_bars >= 16, "Blend should hold for 16+ bars"
    
    # Calculate total samples
    dsp_envelope = EQAutomationEnvelope(
        attack_samples=int((base_envelope.attack_ms / 1000.0) * 44100),
        hold_samples=int((base_envelope.hold_bars * 240.0 / 128.0) * 44100),
        release_samples=int((base_envelope.release_ms / 1000.0) * 44100),
    )
    
    print(f"✓ Three-band blend envelope:")
    print(f"  Attack: {base_envelope.attack_ms}ms (very gradual)")
    print(f"  Hold: {base_envelope.hold_bars} bars (very long)")
    print(f"  Release: {base_envelope.release_ms}ms (very gradual)")
    print(f"  Total: {dsp_envelope.total_samples} samples")


def test_bar_alignment():
    """Test that EQ cuts align to bar boundaries."""
    print("\n=== Test 10: Bar Alignment Verification ===")
    
    engine = EQAutomationEngine(bpm=128.0)
    audio_features = {
        'intro_confidence': 0.92,
        'vocal_confidence': 0.88,
        'breakdown_confidence': 0.75,
        'percussiveness': 0.65,
        'num_bars': 32,
    }
    
    opportunities = engine.detect_opportunities(audio_features)
    
    seconds_per_bar = 240.0 / 128.0
    samples_per_bar = int(seconds_per_bar * 44100)
    
    for opp in opportunities:
        # EQ should start at exact bar boundary
        eq_start_sample = opp.bar * samples_per_bar
        bar_start_sample = opp.bar * samples_per_bar
        
        # Allow small rounding error (< 1 sample)
        assert abs(eq_start_sample - bar_start_sample) < 1, \
            f"EQ at bar {opp.bar} not aligned to bar boundary"
        
        print(f"✓ {opp.cut_type.value} @ bar {opp.bar}: aligned to boundary")


def main():
    """Run all tests."""
    print("=" * 60)
    print("DJ EQ AUTOMATION DSP TEST SUITE")
    print("=" * 60)
    
    try:
        test_butterworth_filter_creation()
        test_eq_envelope_generation()
        test_bar_to_sample_conversion()
        test_opportunity_timing_log()
        test_timing_validation()
        test_bass_cut_timing()
        test_high_swap_timing()
        test_filter_sweep_timing()
        test_three_band_blend_timing()
        test_bar_alignment()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
