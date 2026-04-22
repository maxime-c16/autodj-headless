#!/usr/bin/env python3
"""
UNIT TEST: Phases 2-4 Implementation

Tests all components without requiring audio files.
"""

import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from autodj.analyze.structure import (
    LoopRegion,
    compute_loop_vocal_prominence,
    detect_key_compatibility,
)
from autodj.render.vocal_preview import VocalPreviewMixer


def test_phase2():
    """Test Phase 2: Vocal Loop Tagging."""
    print("\n" + "=" * 80)
    print("PHASE 2 TEST: Vocal Loop Prominence Tagging")
    print("=" * 80)

    # Create test loop
    loop = LoopRegion(
        start_seconds=50.0,
        end_seconds=75.0,  # 25 second loop
        length_bars=16,
        energy=0.75,
        stability=0.92,
        label="drop_loop",
    )

    # Vocal regions: 52-60s and 65-73s
    vocal_regions = [(52.0, 60.0), (65.0, 73.0)]

    # Calculate prominence
    prominence = compute_loop_vocal_prominence(loop, vocal_regions)

    # Expected: (8 + 8) / 25 = 0.64
    expected = (8.0 + 8.0) / 25.0

    print(f"\nLoop: {loop.start_seconds:.1f}s - {loop.end_seconds:.1f}s")
    print(f"Vocal regions: {vocal_regions}")
    print(f"Expected prominence: {expected:.2f}")
    print(f"Calculated prominence: {prominence:.2f}")

    assert abs(prominence - expected) < 0.01, "Vocal prominence calculation error"
    print(f"✅ PHASE 2 TEST PASSED")
    return True


def test_phase3():
    """Test Phase 3: Key Compatibility."""
    print("\n" + "=" * 80)
    print("PHASE 3 TEST: Key Compatibility Matrix")
    print("=" * 80)

    test_cases = [
        ("C", "C", True, "Same key"),
        ("C", "G", True, "Perfect 5th"),
        ("C", "Am", True, "Relative minor"),
        ("C", "F", True, "Perfect 4th"),
        ("C", "D", True, "Major 2nd"),
        ("C", "F#", False, "Tritone (avoid)"),
    ]

    print("\nTesting key combinations:")
    all_pass = True

    for key1, key2, expected, reason in test_cases:
        result = detect_key_compatibility(key1, key2)
        status = "✅" if result == expected else "❌"
        print(f"  {status} {key1} + {key2} = {result} (expected {expected}) - {reason}")
        if result != expected:
            all_pass = False

    assert all_pass, "Key compatibility tests failed"
    print(f"\n✅ PHASE 3 TEST PASSED")
    return True


def test_phase4():
    """Test Phase 4: Vocal Preview Mixer."""
    print("\n" + "=" * 80)
    print("PHASE 4 TEST: Vocal Preview Mixer")
    print("=" * 80)

    mixer = VocalPreviewMixer(sr=44100)

    # Test 1: Create amplitude envelope
    print("\n1️⃣ Testing amplitude envelope...")
    total_samples = 44100 * 10  # 10 seconds
    fade_in = 44100 * 3  # 3 seconds
    fade_out = 44100 * 2  # 2 seconds

    envelope = mixer.create_amplitude_envelope(
        total_samples, fade_in, fade_out, peak_level_db=-18.0
    )

    assert len(envelope) == total_samples, "Envelope length mismatch"
    assert envelope[0] == 0.0, "Envelope should start at 0"
    assert envelope[-1] == 0.0, "Envelope should end at 0"
    assert np.max(envelope) > 0, "Envelope should have positive values"
    print(f"   ✓ Envelope created: {len(envelope)} samples")
    print(f"   ✓ Min: {np.min(envelope):.3f}, Max: {np.max(envelope):.3f}")

    # Test 2: HPF filter
    print("\n2️⃣ Testing high-pass filter...")
    audio = np.random.randn(44100).astype(np.float32)
    filtered = mixer.apply_highpass_filter(audio, cutoff_hz=300.0)
    assert len(filtered) == len(audio), "Filtered audio length mismatch"
    assert filtered.dtype == np.float32, "Output should be float32"
    print(f"   ✓ HPF filter applied successfully")

    # Test 3: Time stretching
    print("\n3️⃣ Testing time stretching...")
    audio_short = np.sin(2 * np.pi * 1000 * np.arange(44100) / 44100).astype(
        np.float32
    )
    stretched = mixer.time_stretch_audio(audio_short, source_bpm=120.0, target_bpm=140.0)
    # 120→140 = 1.167x stretch (should be longer)
    expected_ratio = 1.167
    actual_ratio = len(stretched) / len(audio_short)
    assert abs(actual_ratio - expected_ratio) < 0.1, "Time stretch ratio incorrect"
    print(f"   ✓ Time stretch: {len(audio_short)} → {len(stretched)} samples")
    print(f"   ✓ Ratio: {actual_ratio:.2f}x (expected {expected_ratio:.2f}x)")

    print(f"\n✅ PHASE 4 TEST PASSED")
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("COMPREHENSIVE TEST SUITE: Phases 2-4")
    print("=" * 80)

    results = []

    try:
        results.append(("Phase 2: Vocal Loop Tagging", test_phase2()))
    except Exception as e:
        print(f"❌ Phase 2 failed: {e}")
        results.append(("Phase 2: Vocal Loop Tagging", False))

    try:
        results.append(("Phase 3: Key Compatibility", test_phase3()))
    except Exception as e:
        print(f"❌ Phase 3 failed: {e}")
        results.append(("Phase 3: Key Compatibility", False))

    try:
        results.append(("Phase 4: Vocal Preview Mixer", test_phase4()))
    except Exception as e:
        print(f"❌ Phase 4 failed: {e}")
        results.append(("Phase 4: Vocal Preview Mixer", False))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    all_passed = all(passed for _, passed in results)

    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL TESTS PASSED - PHASES 2-4 READY FOR PRODUCTION")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 80)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
