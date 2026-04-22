#!/usr/bin/env python3
"""
Test script for DJ EQ Automation Engine

Verifies:
1. EQ opportunity detection
2. Envelope generation
3. Timeline export
4. Confidence thresholding
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from autodj.render.eq_automation import (
    EQAutomationEngine,
    EQAutomationDetector,
    EQCutType,
    FrequencyBand,
    EQEnvelope,
)


def test_eq_engine_initialization():
    """Test EQ engine initialization."""
    print("\n=== Test 1: Engine Initialization ===")
    
    engine = EQAutomationEngine(bpm=128.0, sample_rate=44100)
    
    assert engine.bpm == 128.0
    assert engine.sample_rate == 44100
    assert abs(engine.seconds_per_bar - 1.875) < 0.01  # 4 beats at 128 BPM
    
    print("✓ Engine initialized correctly")
    print(f"  BPM: {engine.bpm}")
    print(f"  Seconds per bar: {engine.seconds_per_bar:.2f}")
    print(f"  Samples per bar: {engine.samples_per_bar}")


def test_opportunity_detection():
    """Test EQ opportunity detection with realistic features."""
    print("\n=== Test 2: Opportunity Detection ===")
    
    engine = EQAutomationEngine(bpm=128.0, sample_rate=44100)
    
    # Audio features with high-confidence intro and vocals
    audio_features = {
        'intro_confidence': 0.92,      # HIGH confidence intro
        'vocal_confidence': 0.88,       # HIGH confidence vocals
        'breakdown_confidence': 0.75,   # MEDIUM confidence breakdown
        'percussiveness': 0.65,         # Medium percussiveness
        'spectral_centroid': 3500.0,
        'loudness_db': -10.0,
        'energy': 0.75,
        'num_bars': 32,
    }
    
    metadata = {'artist': 'Test Artist', 'title': 'Test Track'}
    
    opportunities = engine.detect_opportunities(audio_features, metadata)
    
    print(f"✓ Detected {len(opportunities)} opportunities:")
    for opp in opportunities:
        print(f"  - {opp.cut_type.value}: bar {opp.bar}, "
              f"confidence {opp.confidence:.2f}, {opp.reason}")
    
    # Verify we got expected opportunities
    assert len(opportunities) > 0, "Should detect at least one opportunity"
    
    # Check that all opportunities have confidence >= MIN_CONFIDENCE
    for opp in opportunities:
        assert opp.confidence >= engine.MIN_CONFIDENCE, \
            f"Opportunity has low confidence: {opp.confidence}"
    
    # Verify no overlaps
    opportunities_sorted = sorted(opportunities, key=lambda x: x.bar)
    for i, opp1 in enumerate(opportunities_sorted[:-1]):
        opp2 = opportunities_sorted[i + 1]
        opp1_end = opp1.bar + opp1.phrase_length_bars
        assert opp2.bar >= opp1_end - 2, \
            f"Overlap detected: {opp1.cut_type.value} ends at {opp1_end}, " \
            f"{opp2.cut_type.value} starts at {opp2.bar}"
    
    print("✓ All opportunities valid (no overlaps, sufficient confidence)")


def test_low_confidence_rejection():
    """Test that low-confidence features are rejected."""
    print("\n=== Test 3: Low-Confidence Rejection ===")
    
    engine = EQAutomationEngine(bpm=128.0, sample_rate=44100)
    
    # Low-confidence features
    audio_features = {
        'intro_confidence': 0.50,       # LOW confidence
        'vocal_confidence': 0.60,       # LOW confidence
        'breakdown_confidence': 0.40,   # LOW confidence
        'percussiveness': 0.35,         # LOW percussiveness
        'num_bars': 32,
    }
    
    opportunities = engine.detect_opportunities(audio_features)
    
    print(f"✓ Detected {len(opportunities)} opportunities (expected: 0)")
    assert len(opportunities) == 0, \
        "Should detect 0 opportunities with low confidence features"
    print("✓ Low-confidence features correctly rejected")


def test_timeline_generation():
    """Test EQ timeline generation."""
    print("\n=== Test 4: Timeline Generation ===")
    
    engine = EQAutomationEngine(bpm=128.0, sample_rate=44100)
    
    audio_features = {
        'intro_confidence': 0.92,
        'vocal_confidence': 0.88,
        'breakdown_confidence': 0.75,
        'percussiveness': 0.65,
        'num_bars': 32,
    }
    
    opportunities = engine.detect_opportunities(audio_features)
    
    # Generate timeline
    timeline = engine.generate_eq_timeline(opportunities, total_bars=32)
    
    print("✓ Timeline generated:")
    print(f"  Total bars: {timeline['total_bars']}")
    print(f"  BPM: {timeline['bpm']}")
    print(f"  Opportunities: {len(timeline['opportunities'])}")
    print(f"  Timeline events: {len(timeline['timeline'])}")
    
    # Verify timeline structure
    assert timeline['total_bars'] == 32
    assert timeline['bpm'] == 128.0
    assert len(timeline['timeline']) == len(timeline['opportunities'])
    
    # Check timeline entries have required fields
    for entry in timeline['timeline']:
        assert 'bar' in entry
        assert 'type' in entry
        assert 'sample_start' in entry
        assert 'attack_samples' in entry
        assert 'hold_samples' in entry
        assert 'release_samples' in entry
    
    print("✓ Timeline structure valid")


def test_sample_conversion():
    """Test bar/ms to sample conversion."""
    print("\n=== Test 5: Sample Conversion ===")
    
    engine = EQAutomationEngine(bpm=120.0, sample_rate=44100)
    
    # At 120 BPM: 4 bars = 8 seconds = 352,800 samples
    bars_4_samples = engine.bars_to_samples(4.0)
    expected = int(8.0 * 44100)
    assert bars_4_samples == expected, \
        f"4 bars should be {expected} samples, got {bars_4_samples}"
    
    # 100ms = 4410 samples
    ms_100_samples = engine.ms_to_samples(100.0)
    expected = int(0.1 * 44100)
    assert ms_100_samples == expected, \
        f"100ms should be {expected} samples, got {ms_100_samples}"
    
    print("✓ Sample conversion correct")
    print(f"  4 bars @ 120 BPM: {bars_4_samples} samples")
    print(f"  100ms: {ms_100_samples} samples")


def test_detector_facade():
    """Test EQAutomationDetector facade."""
    print("\n=== Test 6: Detector Facade ===")
    
    # Test enabled detector
    detector_on = EQAutomationDetector(enabled=True)
    assert detector_on.enabled == True
    print("✓ Detector initialized (enabled=True)")
    
    # Test disabled detector
    detector_off = EQAutomationDetector(enabled=False)
    assert detector_off.enabled == False
    
    opportunities = detector_off.detect_for_track(
        track_path="/fake/path.mp3",
        bpm=128.0,
        audio_features={'intro_confidence': 0.95, 'num_bars': 32},
    )
    
    assert len(opportunities) == 0, "Disabled detector should return empty list"
    print("✓ Detector correctly returns empty list when disabled")


def test_envelope_definitions():
    """Test that envelope definitions are correct."""
    print("\n=== Test 7: Envelope Definitions ===")
    
    engine = EQAutomationEngine(bpm=128.0)
    
    # Bass cut should be quick (instant attack/release)
    bass_cut_env = engine.DEFAULT_ENVELOPES[EQCutType.BASS_CUT]
    assert bass_cut_env.attack_ms == 0, "Bass cut should have instant attack"
    assert bass_cut_env.release_ms == 0, "Bass cut should have instant release"
    print("✓ Bass cut envelope: instant (percussive)")
    
    # High swap should be gradual
    high_swap_env = engine.DEFAULT_ENVELOPES[EQCutType.HIGH_SWAP]
    assert high_swap_env.attack_ms > 0, "High swap should have gradual attack"
    assert high_swap_env.release_ms > 0, "High swap should have gradual release"
    print("✓ High swap envelope: gradual (smooth)")
    
    # Filter sweep should be long
    filter_sweep_env = engine.DEFAULT_ENVELOPES[EQCutType.FILTER_SWEEP]
    assert filter_sweep_env.hold_bars >= 8, "Filter sweep should hold for 8+ bars"
    print("✓ Filter sweep envelope: long hold (dramatic effect)")
    
    # Three-band blend should be very gradual
    blend_env = engine.DEFAULT_ENVELOPES[EQCutType.THREE_BAND_BLEND]
    assert blend_env.attack_ms >= 500, "Blend should have very gradual attack"
    print("✓ Three-band blend envelope: very gradual")


def main():
    """Run all tests."""
    print("=" * 60)
    print("DJ EQ AUTOMATION ENGINE TEST SUITE")
    print("=" * 60)
    
    try:
        test_eq_engine_initialization()
        test_opportunity_detection()
        test_low_confidence_rejection()
        test_timeline_generation()
        test_sample_conversion()
        test_detector_facade()
        test_envelope_definitions()
        
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
