#!/usr/bin/env python3
"""
Unit Tests for Phase 1: Early Transitions

Comprehensive test suite covering:
- Timing calculation accuracy
- Outro detection (explicit, sections, fallback)
- Bar-aligned timing validation
- Full playlist application
- Liquidsoap code generation
"""

import pytest
import json
from typing import Dict, Any

import sys
sys.path.insert(0, "/home/mcauchy/autodj-headless/src")

from autodj.render.phases import (
    Phase1EarlyTransitions,
    Phase1Config,
    Phase1Metadata,
    EarlyTransitionModel,
    create_phase1_early_transitions,
    generate_liquidsoap_phase1,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def base_transition() -> Dict[str, Any]:
    """Base transition dict (120 BPM, 8 bar overlap)."""
    return {
        'track_id': 'track_001',
        'next_track_id': 'track_002',
        'target_bpm': 120.0,
        'overlap_bars': 8,
        'transition_type': 'bass_swap',
    }


@pytest.fixture
def outgoing_track_with_outro() -> Dict[str, Any]:
    """Outgoing track with explicit outro detection."""
    return {
        'id': 'track_001',
        'title': 'Track A',
        'duration_seconds': 300.0,
        'outro_start_seconds': 260.0,
    }


@pytest.fixture
def outgoing_track_with_sections() -> Dict[str, Any]:
    """Outgoing track with section analysis."""
    sections = [
        {'label': 'intro', 'start': 0.0, 'duration': 16.0},
        {'label': 'verse', 'start': 16.0, 'duration': 32.0},
        {'label': 'chorus', 'start': 48.0, 'duration': 32.0},
        {'label': 'outro', 'start': 240.0, 'duration': 60.0},
    ]
    return {
        'id': 'track_001',
        'title': 'Track A',
        'duration_seconds': 300.0,
        'sections': sections,
    }


@pytest.fixture
def outgoing_track_no_outro() -> Dict[str, Any]:
    """Outgoing track with no explicit outro info."""
    return {
        'id': 'track_001',
        'title': 'Track A',
        'duration_seconds': 180.0,
    }


@pytest.fixture
def phase1_engine() -> Phase1EarlyTransitions:
    """Phase 1 engine with defaults."""
    config = Phase1Config(enabled=True, model=EarlyTransitionModel.FIXED_16_BARS)
    return Phase1EarlyTransitions(config)


@pytest.fixture
def phase1_disabled() -> Phase1EarlyTransitions:
    """Phase 1 engine disabled."""
    config = Phase1Config(enabled=False)
    return Phase1EarlyTransitions(config)


# ============================================================================
# TEST: TIMING CALCULATION
# ============================================================================

def test_timing_calculation_basic(phase1_engine, base_transition, outgoing_track_with_outro):
    """Verify basic early transition timing calculation."""
    trans, meta = phase1_engine.apply_to_transition(
        base_transition,
        outgoing_track_with_outro,
        {},
    )
    
    # Verify metadata
    assert meta.enabled is True
    assert meta.early_transition_bars == 16
    assert meta.outro_start_seconds == 260.0
    assert meta.outro_detected is True
    assert meta.bpm == 120.0
    
    # At 120 BPM, each bar = 2 seconds
    # 16 bars = 32 seconds
    expected_crossfade_start = 260.0 - 32.0
    assert meta.crossfade_start_seconds == pytest.approx(expected_crossfade_start, abs=0.01)
    
    # Verify transition updated
    assert 'phase_1_early_transitions' in trans
    p1_data = trans['phase_1_early_transitions']
    assert p1_data['enabled'] is True
    assert p1_data['early_transition_bars'] == 16


def test_timing_calculation_different_bpms():
    """Verify timing accuracy at different BPM values."""
    config = Phase1Config(enabled=True)
    engine = Phase1EarlyTransitions(config)
    
    test_cases = [
        (90.0, 16, 217.33),   # 90 BPM: bar = 2.67s, 16 bars = 42.67s, 260-42.67=217.33
        (120.0, 16, 228.0),   # 120 BPM: bar = 2s, 16 bars = 32s, 260-32=228
        (140.0, 16, 232.57),  # 140 BPM: bar = 1.71s, 16 bars = 27.43s, 260-27.43=232.57
    ]
    
    for bpm, early_bars, expected_crossfade_start in test_cases:
        transition = {
            'target_bpm': bpm,
            'overlap_bars': 8,
        }
        outgoing = {
            'outro_start_seconds': 260.0,
            'duration_seconds': 300.0,
        }
        
        trans, meta = engine.apply_to_transition(transition, outgoing, {})
        
        assert meta.crossfade_start_seconds == pytest.approx(
            expected_crossfade_start, abs=0.1
        ), f"BPM {bpm}: expected {expected_crossfade_start}, got {meta.crossfade_start_seconds}"


def test_early_bars_options():
    """Verify early bar count options (16, 24, 32)."""
    test_cases = [
        (EarlyTransitionModel.FIXED_16_BARS, 16),
        (EarlyTransitionModel.FIXED_24_BARS, 24),
        (EarlyTransitionModel.FIXED_32_BARS, 32),
    ]
    
    for model, expected_bars in test_cases:
        config = Phase1Config(enabled=True, model=model)
        engine = Phase1EarlyTransitions(config)
        
        transition = {
            'target_bpm': 120.0,
            'overlap_bars': 8,
        }
        outgoing = {'outro_start_seconds': 300.0}
        
        trans, meta = engine.apply_to_transition(transition, outgoing, {})
        assert meta.early_transition_bars == expected_bars


# ============================================================================
# TEST: OUTRO DETECTION
# ============================================================================

def test_outro_detection_explicit(phase1_engine, base_transition, outgoing_track_with_outro):
    """Verify explicit outro detection."""
    trans, meta = phase1_engine.apply_to_transition(
        base_transition,
        outgoing_track_with_outro,
        {},
    )
    
    assert meta.outro_detected is True
    assert meta.outro_start_seconds == 260.0


def test_outro_detection_from_sections(phase1_engine, base_transition, outgoing_track_with_sections):
    """Verify outro detection from sections."""
    trans, meta = phase1_engine.apply_to_transition(
        base_transition,
        outgoing_track_with_sections,
        {},
    )
    
    assert meta.outro_detected is True
    assert meta.outro_start_seconds == 240.0


def test_outro_detection_from_sections_json(phase1_engine, base_transition):
    """Verify outro detection from JSON-encoded sections."""
    sections = [
        {'label': 'verse', 'start': 0.0, 'duration': 32.0},
        {'label': 'outro', 'start': 200.0, 'duration': 60.0},
    ]
    outgoing = {
        'id': 'track_001',
        'duration_seconds': 260.0,
        'sections_json': json.dumps(sections),
    }
    
    trans, meta = phase1_engine.apply_to_transition(
        base_transition,
        outgoing,
        {},
    )
    
    assert meta.outro_detected is True
    assert meta.outro_start_seconds == 200.0


def test_outro_detection_fallback(phase1_engine, base_transition):
    """Verify fallback outro estimation when not detected."""
    outgoing_track_no_outro = {
        'id': 'track_001',
        'title': 'Track A',
        'duration_seconds': 180.0,
    }
    trans, meta = phase1_engine.apply_to_transition(
        base_transition,
        outgoing_track_no_outro,
        {},
    )
    
    # Should estimate from duration (duration - 20 = 180 - 20 = 160)
    assert meta.outro_start_seconds == pytest.approx(160.0, abs=0.1)
    # Crossfade starts 16 bars (32 sec) before: 160 - 32 = 128
    assert meta.crossfade_start_seconds == pytest.approx(128.0, abs=0.1)


# ============================================================================
# TEST: EDGE CASES
# ============================================================================

def test_crossfade_negative_guard(phase1_engine):
    """Verify crossfade start cannot be before track begins."""
    transition = {
        'target_bpm': 120.0,
        'overlap_bars': 8,
    }
    outgoing = {
        'duration_seconds': 20.0,  # Very short track
        'outro_start_seconds': 15.0,
    }
    
    trans, meta = phase1_engine.apply_to_transition(
        transition,
        outgoing,
        {},
    )
    
    # Should be clamped to 0
    assert meta.crossfade_start_seconds >= 0


def test_disabled_engine(phase1_disabled, base_transition):
    """Verify disabled engine returns unmodified transition."""
    outgoing = {'outro_start_seconds': 260.0}
    
    trans, meta = phase1_disabled.apply_to_transition(
        base_transition.copy(),
        outgoing,
        {},
    )
    
    assert meta.enabled is False
    assert 'phase_1_early_transitions' not in trans


def test_missing_bpm_raises_error(phase1_engine):
    """Verify error when BPM is missing."""
    transition = {
        'overlap_bars': 8,
        # Missing target_bpm
    }
    outgoing = {'outro_start_seconds': 260.0}
    
    with pytest.raises(ValueError):
        phase1_engine.apply_to_transition(transition, outgoing, {})


# ============================================================================
# TEST: FULL PLAYLIST APPLICATION
# ============================================================================

def test_apply_to_playlist(phase1_engine):
    """Verify applying Phase 1 to entire playlist."""
    transitions = [
        {'track_id': 'track_001', 'next_track_id': 'track_002', 'target_bpm': 120.0, 'overlap_bars': 8},
        {'track_id': 'track_002', 'next_track_id': 'track_003', 'target_bpm': 120.0, 'overlap_bars': 8},
        {'track_id': 'track_003', 'next_track_id': 'track_004', 'target_bpm': 128.0, 'overlap_bars': 16},
    ]
    
    tracks = {
        'track_001': {'id': 'track_001', 'outro_start_seconds': 260.0},
        'track_002': {'id': 'track_002', 'outro_start_seconds': 280.0},
        'track_003': {'id': 'track_003', 'outro_start_seconds': 250.0},
        'track_004': {'id': 'track_004', 'outro_start_seconds': 270.0},
    }
    
    modified, stats = phase1_engine.apply_to_playlist(transitions, tracks)
    
    # Verify all applied
    assert stats['applied'] == 3
    assert stats['total_transitions'] == 3
    assert stats['errors'] == 0
    
    # Verify each transition has Phase 1 data
    for trans in modified:
        assert 'phase_1_early_transitions' in trans


def test_playlist_error_handling(phase1_engine):
    """Verify graceful error handling in playlist application."""
    transitions = [
        {'track_id': 'track_001', 'target_bpm': 120.0, 'overlap_bars': 8},
        {'track_id': 'track_002', 'overlap_bars': 8},  # Missing target_bpm
    ]
    
    tracks = {
        'track_001': {'outro_start_seconds': 260.0},
        'track_002': {'outro_start_seconds': 280.0},
    }
    
    modified, stats = phase1_engine.apply_to_playlist(transitions, tracks)
    
    # First succeeds, second fails gracefully
    assert stats['applied'] == 1
    assert stats['errors'] == 1
    assert len(modified) == 2


# ============================================================================
# TEST: ADAPTIVE MODEL
# ============================================================================

def test_adaptive_model_short_track():
    """Verify adaptive model uses 16 bars for short tracks."""
    config = Phase1Config(enabled=True, model=EarlyTransitionModel.ADAPTIVE)
    engine = Phase1EarlyTransitions(config)
    
    transition = {'target_bpm': 120.0, 'overlap_bars': 8}
    outgoing = {'duration_seconds': 100.0, 'outro_start_seconds': 90.0}
    
    trans, meta = engine.apply_to_transition(transition, outgoing, {})
    assert meta.early_transition_bars == 16


def test_adaptive_model_medium_track():
    """Verify adaptive model uses 24 bars for medium tracks."""
    config = Phase1Config(enabled=True, model=EarlyTransitionModel.ADAPTIVE)
    engine = Phase1EarlyTransitions(config)
    
    transition = {'target_bpm': 120.0, 'overlap_bars': 8}
    outgoing = {'duration_seconds': 200.0, 'outro_start_seconds': 190.0}
    
    trans, meta = engine.apply_to_transition(transition, outgoing, {})
    assert meta.early_transition_bars == 24


def test_adaptive_model_long_track():
    """Verify adaptive model uses 32 bars for long tracks."""
    config = Phase1Config(enabled=True, model=EarlyTransitionModel.ADAPTIVE)
    engine = Phase1EarlyTransitions(config)
    
    transition = {'target_bpm': 120.0, 'overlap_bars': 8}
    outgoing = {'duration_seconds': 350.0, 'outro_start_seconds': 340.0}
    
    trans, meta = engine.apply_to_transition(transition, outgoing, {})
    assert meta.early_transition_bars == 32


# ============================================================================
# TEST: LIQUIDSOAP CODE GENERATION
# ============================================================================

def test_liquidsoap_generation():
    """Verify Liquidsoap code generation."""
    meta = Phase1Metadata(
        enabled=True,
        early_transition_bars=16,
        outro_start_seconds=260.0,
        outro_detected=True,
        crossfade_start_seconds=228.0,
        crossfade_duration_bars=8,
        seconds_per_bar=2.0,
        bpm=120.0,
    )
    
    code = generate_liquidsoap_phase1(meta)
    
    # Verify code structure
    assert 'PHASE 1' in code
    assert 'phase1_early_transition_enabled = true' in code
    assert 'phase1_crossfade_start_seconds = 228.000' in code
    assert 'phase1_early_bars = 16' in code


def test_liquidsoap_generation_disabled():
    """Verify Liquidsoap generation when disabled."""
    meta = Phase1Metadata(
        enabled=False,
        early_transition_bars=0,
        outro_start_seconds=None,
        outro_detected=False,
        crossfade_start_seconds=None,
        crossfade_duration_bars=8,
        seconds_per_bar=2.0,
        bpm=120.0,
    )
    
    code = generate_liquidsoap_phase1(meta)
    assert 'disabled' in code.lower()


# ============================================================================
# TEST: FACTORY FUNCTION
# ============================================================================

def test_create_from_config_dict():
    """Verify factory function creates engine from config dict."""
    config = {
        'enabled': True,
        'model': 'fixed_24_bars',
        'fallback_bars': 24,
    }
    
    engine = create_phase1_early_transitions(config)
    
    assert engine.config.enabled is True
    assert engine.config.model == EarlyTransitionModel.FIXED_24_BARS
    assert engine.config.fallback_bars == 24


def test_create_with_invalid_model():
    """Verify factory handles invalid model gracefully."""
    config = {
        'enabled': True,
        'model': 'invalid_model',
    }
    
    engine = create_phase1_early_transitions(config)
    
    # Should default to fixed_16_bars
    assert engine.config.model == EarlyTransitionModel.FIXED_16_BARS


def test_create_with_none():
    """Verify factory works with None config."""
    engine = create_phase1_early_transitions(None)
    
    assert engine.config.enabled is True
    assert engine.config.model == EarlyTransitionModel.FIXED_16_BARS


# ============================================================================
# TEST: VALIDATION
# ============================================================================

def test_metadata_to_dict():
    """Verify Phase1Metadata serializes correctly."""
    meta = Phase1Metadata(
        enabled=True,
        early_transition_bars=16,
        outro_start_seconds=260.0,
        outro_detected=True,
        crossfade_start_seconds=228.0,
        crossfade_duration_bars=8,
        seconds_per_bar=2.0,
        bpm=120.0,
    )
    
    d = meta.to_dict()
    
    assert d['enabled'] is True
    assert d['early_transition_bars'] == 16
    assert d['outro_start_seconds'] == 260.0
    assert d['bpm'] == 120.0


def test_config_to_dict():
    """Verify Phase1Config serializes correctly."""
    config = Phase1Config(
        enabled=True,
        model=EarlyTransitionModel.FIXED_16_BARS,
        fallback_bars=16,
    )
    
    d = config.to_dict()
    
    assert d['enabled'] is True
    assert d['model'] == 'fixed_16_bars'
    assert d['fallback_bars'] == 16


# ============================================================================
# TEST: INTEGRATION WITH TRANSITIONS.JSON
# ============================================================================

def test_full_transition_json_structure(phase1_engine, base_transition, outgoing_track_with_outro):
    """Verify full transitions.json structure after Phase 1 application."""
    trans, meta = phase1_engine.apply_to_transition(
        base_transition,
        outgoing_track_with_outro,
        {},
    )
    
    # Should have all original fields plus Phase 1 data
    assert 'track_id' in trans
    assert 'target_bpm' in trans
    assert 'phase_1_early_transitions' in trans
    
    p1 = trans['phase_1_early_transitions']
    assert 'enabled' in p1
    assert 'early_transition_bars' in p1
    assert 'crossfade_start_seconds' in p1


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
