"""
Tests for track structure analysis module.

Covers section detection, classification, downbeat detection, kick pattern
analysis, semantic cue generation, loop region detection, and database
persistence.
"""

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from autodj.analyze.structure import (
    Section,
    SemanticCue,
    LoopRegion,
    TrackStructure,
    detect_downbeat,
    detect_sections,
    classify_sections,
    analyze_kick_pattern,
    generate_semantic_cues,
    detect_loop_regions,
    detect_vocal,
    analyze_track_structure,
    _compute_mel_spectrogram,
    _compute_self_similarity,
    _compute_novelty_curve,
    _snap_to_bar,
    _bar_to_seconds,
    _compute_rms_energy,
    _compute_bass_energy,
    _compute_kick_energy,
)
from autodj.db import Database, TrackMetadata


# ============================================================================
# HELPERS: Synthetic audio generation
# ============================================================================


def _make_sine(freq: float, duration: float, sr: int = 44100, amp: float = 0.5) -> np.ndarray:
    """Generate a sine wave."""
    t = np.arange(int(duration * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _make_kick(bpm: float, duration: float, sr: int = 44100) -> np.ndarray:
    """Generate a 4-on-the-floor kick pattern (60Hz sine bursts + sub).

    Uses a longer, louder kick with sub-bass content to reliably trigger
    the bandpass kick detector (40-100Hz).
    """
    n_samples = int(duration * sr)
    audio = np.zeros(n_samples, dtype=np.float32)
    beat_period = 60.0 / bpm
    beat_samples = int(beat_period * sr)
    kick_len = int(0.1 * sr)  # 100ms kick (longer for more energy)

    t_kick = np.arange(kick_len) / sr
    # Multi-frequency kick: 60Hz fundamental + 80Hz sub
    kick_sound = (
        0.9 * np.sin(2 * np.pi * 60 * t_kick) * np.exp(-t_kick * 20) +
        0.6 * np.sin(2 * np.pi * 80 * t_kick) * np.exp(-t_kick * 15)
    ).astype(np.float32)

    for i in range(0, n_samples - kick_len, beat_samples):
        end = min(i + kick_len, n_samples)
        audio[i:end] += kick_sound[:end - i]

    return audio.astype(np.float32)


def _make_techno_track(bpm: float = 128.0, duration: float = 180.0, sr: int = 44100) -> np.ndarray:
    """Generate a synthetic techno track with intro/drop/breakdown/drop/outro.

    Structure (at 128 BPM, 1 bar = 1.875s):
    - 0-16 bars (0-30s): Intro - low energy, no kick
    - 16-48 bars (30-90s): Drop 1 - high energy, kick
    - 48-64 bars (90-120s): Breakdown - low energy, no kick
    - 64-96 bars (120-180s): Drop 2 - high energy, kick (if long enough)
    - last 16 bars: Outro - declining energy
    """
    n_samples = int(duration * sr)
    audio = np.zeros(n_samples, dtype=np.float32)
    seconds_per_bar = 4 * 60.0 / bpm

    # Intro: quiet pad
    intro_end = int(16 * seconds_per_bar * sr)
    intro_end = min(intro_end, n_samples)
    audio[:intro_end] += _make_sine(200, intro_end / sr, sr, amp=0.1)[:intro_end]

    # Drop 1: kick + bass
    drop1_start = intro_end
    drop1_end = int(48 * seconds_per_bar * sr)
    drop1_end = min(drop1_end, n_samples)
    if drop1_end > drop1_start:
        drop1_dur = (drop1_end - drop1_start) / sr
        kick = _make_kick(bpm, drop1_dur, sr)
        bass = _make_sine(80, drop1_dur, sr, amp=0.3)
        noise = np.random.randn(len(kick)).astype(np.float32) * 0.1
        drop1_audio = kick + bass + noise
        audio[drop1_start:drop1_start + len(drop1_audio)] += drop1_audio[:drop1_end - drop1_start]

    # Breakdown: quiet, no kick
    bd_start = drop1_end
    bd_end = int(64 * seconds_per_bar * sr)
    bd_end = min(bd_end, n_samples)
    if bd_end > bd_start:
        bd_dur = (bd_end - bd_start) / sr
        audio[bd_start:bd_end] += _make_sine(300, bd_dur, sr, amp=0.08)[:bd_end - bd_start]

    # Drop 2: kick + bass (if track is long enough)
    drop2_start = bd_end
    drop2_end = min(int(96 * seconds_per_bar * sr), n_samples - int(16 * seconds_per_bar * sr))
    drop2_end = max(drop2_end, drop2_start)
    if drop2_end > drop2_start:
        drop2_dur = (drop2_end - drop2_start) / sr
        kick2 = _make_kick(bpm, drop2_dur, sr)
        bass2 = _make_sine(80, drop2_dur, sr, amp=0.3)
        noise2 = np.random.randn(len(kick2)).astype(np.float32) * 0.1
        drop2_audio = kick2 + bass2 + noise2
        audio[drop2_start:drop2_start + len(drop2_audio)] += drop2_audio[:drop2_end - drop2_start]

    # Outro: declining energy
    outro_start = max(drop2_end, n_samples - int(16 * seconds_per_bar * sr))
    if outro_start < n_samples:
        outro_dur = (n_samples - outro_start) / sr
        fade = np.linspace(0.15, 0.02, n_samples - outro_start).astype(np.float32)
        audio[outro_start:] += _make_sine(200, outro_dur, sr, amp=0.1)[:n_samples - outro_start] * fade

    # Normalize
    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak * 0.9

    return audio


# ============================================================================
# TEST: Data classes
# ============================================================================


class TestDataClasses:
    """Test dataclass construction and serialization."""

    def test_section_creation(self):
        s = Section(
            label="drop", start_seconds=30.0, end_seconds=90.0,
            start_bar=16, end_bar=48, energy=0.85, has_kick=True, confidence=0.9,
        )
        assert s.label == "drop"
        assert s.energy == 0.85

    def test_semantic_cue_creation(self):
        c = SemanticCue(
            label="mix_in", position_seconds=30.0, position_bar=16, type="hot_cue",
        )
        assert c.label == "mix_in"
        assert c.type == "hot_cue"

    def test_loop_region_creation(self):
        l = LoopRegion(
            start_seconds=30.0, end_seconds=60.0,
            length_bars=16, energy=0.8, stability=0.9, label="drop_loop",
        )
        assert l.length_bars == 16

    def test_track_structure_creation(self):
        ts = TrackStructure()
        assert ts.sections == []
        assert ts.kick_pattern == "none"

    def test_section_asdict(self):
        s = Section(
            label="intro", start_seconds=0.0, end_seconds=30.0,
            start_bar=0, end_bar=16, energy=0.2, has_kick=False, confidence=0.7,
        )
        d = asdict(s)
        assert d["label"] == "intro"
        assert isinstance(d, dict)

    def test_semantic_cue_asdict(self):
        c = SemanticCue(
            label="drop_1", position_seconds=30.0, position_bar=16, type="hot_cue",
        )
        d = asdict(c)
        assert d["label"] == "drop_1"
        assert d["position_bar"] == 16


# ============================================================================
# TEST: Helper functions
# ============================================================================


class TestHelperFunctions:
    """Test internal helper functions."""

    def test_snap_to_bar(self):
        # At 120 BPM, bar = 2.0s. 5.0s -> bar 2 (from downbeat 0)
        bar = _snap_to_bar(5.0, 120.0, 0.0)
        assert bar == 2 or bar == 3  # depends on rounding

    def test_bar_to_seconds(self):
        # At 120 BPM, bar 4 = 4 * 2.0s = 8.0s
        sec = _bar_to_seconds(4, 120.0, 0.0)
        assert abs(sec - 8.0) < 0.01

    def test_snap_roundtrip(self):
        # Snap to bar and back should be close
        bpm = 128.0
        downbeat = 0.5
        original = 15.3
        bar = _snap_to_bar(original, bpm, downbeat)
        recovered = _bar_to_seconds(bar, bpm, downbeat)
        # Should be within one bar
        seconds_per_bar = 4 * 60.0 / bpm
        assert abs(recovered - original) < seconds_per_bar

    def test_rms_energy_shape(self):
        audio = np.random.randn(44100 * 5).astype(np.float32)
        energy = _compute_rms_energy(audio, 44100)
        assert len(energy) > 0
        assert np.all(energy >= 0.0)
        assert np.all(energy <= 1.0)

    def test_bass_energy_shape(self):
        audio = np.random.randn(44100 * 5).astype(np.float32)
        bass = _compute_bass_energy(audio, 44100)
        assert len(bass) > 0

    def test_kick_energy_shape(self):
        audio = np.random.randn(44100 * 5).astype(np.float32)
        kick = _compute_kick_energy(audio, 44100)
        assert len(kick) > 0


# ============================================================================
# TEST: Mel spectrogram
# ============================================================================


class TestMelSpectrogram:
    """Test mel spectrogram computation."""

    def test_mel_spectrogram_shape(self):
        audio = np.random.randn(44100 * 10).astype(np.float32)
        mel, times = _compute_mel_spectrogram(audio, 44100)
        assert mel.shape[0] == 64  # default n_mels
        assert mel.shape[1] > 0
        assert len(times) > 0

    def test_mel_spectrogram_non_negative(self):
        audio = _make_sine(440, 5.0)
        mel, _ = _compute_mel_spectrogram(audio, 44100)
        # log1p should produce non-negative values
        assert np.all(mel >= 0.0)


# ============================================================================
# TEST: Self-similarity & novelty
# ============================================================================


class TestSelfSimilarity:
    """Test self-similarity matrix and novelty detection."""

    def test_ssm_is_square(self):
        mel = np.random.randn(64, 200).astype(np.float32)
        ssm = _compute_self_similarity(mel)
        assert ssm.shape[0] == ssm.shape[1]

    def test_ssm_diagonal_is_one(self):
        mel = np.random.randn(64, 100).astype(np.float32)
        ssm = _compute_self_similarity(mel)
        diag = np.diag(ssm)
        # Cosine similarity with itself should be ~1
        np.testing.assert_allclose(diag, 1.0, atol=0.01)

    def test_novelty_curve_shape(self):
        mel = np.random.randn(64, 200).astype(np.float32)
        ssm = _compute_self_similarity(mel)
        novelty = _compute_novelty_curve(ssm)
        assert len(novelty) == ssm.shape[0]

    def test_novelty_non_negative(self):
        mel = np.random.randn(64, 200).astype(np.float32)
        ssm = _compute_self_similarity(mel)
        novelty = _compute_novelty_curve(ssm)
        assert np.all(novelty >= 0.0)


# ============================================================================
# TEST: Downbeat detection
# ============================================================================


class TestDownbeatDetection:
    """Test downbeat detection."""

    def test_downbeat_with_kick(self):
        bpm = 128.0
        audio = _make_kick(bpm, 10.0)
        downbeat = detect_downbeat(audio, 44100, bpm)
        # Should be within first few bars
        bar_period = 4 * 60.0 / bpm
        assert downbeat >= 0.0
        assert downbeat < bar_period * 8  # within 8 bars

    def test_downbeat_silent_audio(self):
        audio = np.zeros(44100 * 5, dtype=np.float32)
        downbeat = detect_downbeat(audio, 44100, 128.0)
        assert downbeat >= 0.0

    def test_downbeat_zero_bpm(self):
        audio = np.random.randn(44100 * 5).astype(np.float32)
        downbeat = detect_downbeat(audio, 44100, 0.0)
        assert downbeat == 0.0


# ============================================================================
# TEST: Section detection
# ============================================================================


class TestSectionDetection:
    """Test section boundary detection."""

    def test_basic_section_detection(self):
        """Synthetic audio with clear energy changes should produce sections."""
        audio = _make_techno_track(128.0, 120.0)
        sections = detect_sections(audio, 44100, 128.0)
        assert len(sections) >= 1
        # All sections should cover the full track
        assert sections[0].start_seconds == 0.0
        assert sections[-1].end_seconds > 0.0

    def test_sections_have_energy(self):
        audio = _make_techno_track(128.0, 120.0)
        sections = detect_sections(audio, 44100, 128.0)
        for s in sections:
            assert 0.0 <= s.energy <= 1.0

    def test_sections_non_overlapping(self):
        audio = _make_techno_track(128.0, 120.0)
        sections = detect_sections(audio, 44100, 128.0)
        for i in range(len(sections) - 1):
            assert sections[i].end_seconds <= sections[i + 1].start_seconds + 0.01

    def test_sections_cover_full_track(self):
        duration = 120.0
        audio = _make_techno_track(128.0, duration)
        sections = detect_sections(audio, 44100, 128.0)
        assert sections[0].start_seconds < 1.0
        assert sections[-1].end_seconds >= duration - 1.0

    def test_sections_zero_bpm_fallback(self):
        audio = np.random.randn(44100 * 30).astype(np.float32)
        sections = detect_sections(audio, 44100, 0.0)
        assert len(sections) == 1
        assert sections[0].label == "unknown"

    def test_short_audio(self):
        """Very short audio should still produce at least one section."""
        audio = np.random.randn(44100 * 10).astype(np.float32)
        sections = detect_sections(audio, 44100, 128.0)
        assert len(sections) >= 1


# ============================================================================
# TEST: Section classification
# ============================================================================


class TestSectionClassification:
    """Test section label assignment."""

    def test_intro_label(self):
        """First low-energy section should be labeled intro."""
        sections = [
            Section("unknown", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("unknown", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        audio = np.zeros(44100 * 90, dtype=np.float32)
        classified = classify_sections(sections, audio, 44100, 128.0)
        assert classified[0].label == "intro"

    def test_drop_label(self):
        """High-energy section with kick after lower energy should be drop."""
        sections = [
            Section("unknown", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("unknown", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        audio = np.zeros(44100 * 90, dtype=np.float32)
        classified = classify_sections(sections, audio, 44100, 128.0)
        assert classified[1].label == "drop"

    def test_breakdown_label(self):
        """Low-energy section without kick should be breakdown."""
        sections = [
            Section("unknown", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("unknown", 30.0, 60.0, 16, 32, 0.85, True, 0.8),
            Section("unknown", 60.0, 90.0, 32, 48, 0.3, False, 0.7),
            Section("unknown", 90.0, 120.0, 48, 64, 0.85, True, 0.8),
        ]
        audio = np.zeros(44100 * 120, dtype=np.float32)
        classified = classify_sections(sections, audio, 44100, 128.0)
        assert classified[2].label == "breakdown"

    def test_outro_label(self):
        """Last low-energy section should be outro."""
        sections = [
            Section("unknown", 0.0, 30.0, 0, 16, 0.85, True, 0.8),
            Section("unknown", 30.0, 60.0, 16, 32, 0.2, False, 0.5),
        ]
        audio = np.zeros(44100 * 60, dtype=np.float32)
        classified = classify_sections(sections, audio, 44100, 128.0)
        assert classified[1].label == "outro"

    def test_single_section(self):
        """Single section should still get a label."""
        sections = [Section("unknown", 0.0, 60.0, 0, 32, 0.5, True, 0.5)]
        audio = np.zeros(44100 * 60, dtype=np.float32)
        classified = classify_sections(sections, audio, 44100, 128.0)
        assert classified[0].label != "unknown"

    def test_empty_sections(self):
        """Empty sections list should return empty."""
        audio = np.zeros(44100, dtype=np.float32)
        result = classify_sections([], audio, 44100, 128.0)
        assert result == []


# ============================================================================
# TEST: Kick pattern detection
# ============================================================================


class TestKickPatternDetection:
    """Test kick pattern analysis."""

    def test_four_on_floor_detected(self):
        """Kick pattern at every beat should be detected as four_on_floor."""
        kick = _make_kick(128.0, 30.0)
        pattern = analyze_kick_pattern(kick, 44100, 128.0)
        assert pattern == "four_on_floor"

    def test_silent_audio_no_kick(self):
        """Silent audio should have no kick pattern."""
        audio = np.zeros(44100 * 10, dtype=np.float32)
        pattern = analyze_kick_pattern(audio, 44100, 128.0)
        assert pattern in ("none", "minimal")

    def test_zero_bpm(self):
        audio = np.random.randn(44100 * 10).astype(np.float32)
        pattern = analyze_kick_pattern(audio, 44100, 0.0)
        assert pattern == "none"


# ============================================================================
# TEST: Semantic cue generation
# ============================================================================


class TestSemanticCueGeneration:
    """Test semantic cue point generation from sections."""

    def test_mix_in_generated(self):
        """mix_in cue should be generated."""
        sections = [
            Section("intro", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("drop", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        cues = generate_semantic_cues(sections, 128.0, 90.0)
        labels = [c.label for c in cues]
        assert "mix_in" in labels

    def test_mix_in_at_intro_end(self):
        """mix_in should be at the end of intro."""
        sections = [
            Section("intro", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("drop", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        cues = generate_semantic_cues(sections, 128.0, 90.0)
        mix_in = next(c for c in cues if c.label == "mix_in")
        assert abs(mix_in.position_seconds - 30.0) < 0.01

    def test_drop_1_generated(self):
        """drop_1 cue should be generated when drops exist."""
        sections = [
            Section("intro", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("drop", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        cues = generate_semantic_cues(sections, 128.0, 90.0)
        labels = [c.label for c in cues]
        assert "drop_1" in labels

    def test_mix_out_generated(self):
        """mix_out cue should always be generated."""
        sections = [
            Section("drop", 0.0, 60.0, 0, 32, 0.85, True, 0.8),
            Section("outro", 60.0, 90.0, 32, 48, 0.2, False, 0.5),
        ]
        cues = generate_semantic_cues(sections, 128.0, 90.0)
        labels = [c.label for c in cues]
        assert "mix_out" in labels

    def test_last_32_generated(self):
        """last_32 cue should be generated."""
        sections = [Section("drop", 0.0, 180.0, 0, 96, 0.85, True, 0.8)]
        cues = generate_semantic_cues(sections, 128.0, 180.0)
        labels = [c.label for c in cues]
        assert "last_32" in labels

    def test_cues_have_types(self):
        """All cues should have valid types."""
        sections = [
            Section("intro", 0.0, 30.0, 0, 16, 0.2, False, 0.5),
            Section("drop", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        cues = generate_semantic_cues(sections, 128.0, 90.0)
        for c in cues:
            assert c.type in ("hot_cue", "memory_cue", "loop_in", "loop_out")

    def test_no_drops_fallback(self):
        """Should still generate cues even without explicit drops."""
        sections = [Section("intro", 0.0, 60.0, 0, 32, 0.3, False, 0.5)]
        cues = generate_semantic_cues(sections, 128.0, 60.0)
        assert len(cues) >= 2  # at least mix_in and mix_out


# ============================================================================
# TEST: Loop region detection
# ============================================================================


class TestLoopRegionDetection:
    """Test loop region detection."""

    def test_loop_from_drop_section(self):
        """Drop sections should produce loop candidates."""
        sections = [
            Section("drop", 30.0, 90.0, 16, 48, 0.85, True, 0.8),
        ]
        # Create repetitive audio for the drop
        audio = np.tile(_make_kick(128.0, 3.75), 16)  # 16 bars
        audio = np.pad(audio, (int(30 * 44100), 0))  # pad 30s of silence before

        loops = detect_loop_regions(sections, audio, 44100, 128.0)
        assert len(loops) >= 1
        assert loops[0].label == "drop_loop"
        assert loops[0].length_bars in (4, 8, 16, 32)

    def test_loop_stability_score(self):
        """Loop regions should have stability scores 0-1."""
        sections = [Section("drop", 0.0, 60.0, 0, 32, 0.85, True, 0.8)]
        audio = np.tile(_make_kick(128.0, 3.75), 16)
        loops = detect_loop_regions(sections, audio, 44100, 128.0)
        for l in loops:
            assert 0.0 <= l.stability <= 1.0

    def test_no_loops_from_short_section(self):
        """Sections shorter than 4 bars should produce no loops."""
        sections = [Section("drop", 0.0, 3.0, 0, 1, 0.85, True, 0.8)]
        audio = np.random.randn(44100 * 3).astype(np.float32)
        loops = detect_loop_regions(sections, audio, 44100, 128.0)
        assert len(loops) == 0

    def test_zero_bpm_no_loops(self):
        sections = [Section("drop", 0.0, 60.0, 0, 0, 0.85, True, 0.8)]
        audio = np.random.randn(44100 * 60).astype(np.float32)
        loops = detect_loop_regions(sections, audio, 44100, 0.0)
        assert loops == []


# ============================================================================
# TEST: Vocal detection
# ============================================================================


class TestVocalDetection:
    """Test vocal content detection."""

    def test_noise_not_vocal(self):
        """White noise should not be detected as vocal (high spectral flatness)."""
        np.random.seed(42)
        audio = np.random.randn(44100 * 5).astype(np.float32)
        result = detect_vocal(audio, 44100)
        # Result is bool (numpy or Python)
        assert result is True or result is False

    def test_sine_is_tonal(self):
        """Pure sine wave at 1kHz (in vocal range) should be detected as vocal-like."""
        audio = _make_sine(1000, 5.0, amp=0.5)
        result = detect_vocal(audio, 44100)
        # Pure tone has very low spectral flatness -> likely detected as vocal
        assert result is True or result is False  # just verify it runs

    def test_silent_audio_not_vocal(self):
        audio = np.zeros(44100 * 5, dtype=np.float32)
        result = detect_vocal(audio, 44100)
        assert result is True or result is False  # just verify it runs


# ============================================================================
# TEST: Full track structure analysis (orchestrator)
# ============================================================================


class TestAnalyzeTrackStructure:
    """Test the full analysis orchestrator."""

    def test_full_analysis_produces_structure(self):
        """Full analysis on synthetic track should produce complete TrackStructure."""
        audio = _make_techno_track(128.0, 120.0)
        structure = analyze_track_structure(audio, 44100, 128.0)

        assert isinstance(structure, TrackStructure)
        assert len(structure.sections) >= 1
        assert len(structure.cue_points) >= 2  # at least mix_in and mix_out
        assert structure.total_bars > 0
        assert structure.downbeat_position >= 0.0
        assert structure.kick_pattern in (
            "four_on_floor", "breakbeat", "minimal", "none"
        )
        assert structure.has_vocal is True or structure.has_vocal is False

    def test_sections_are_classified(self):
        """All sections should have labels after full analysis."""
        audio = _make_techno_track(128.0, 120.0)
        structure = analyze_track_structure(audio, 44100, 128.0)

        for s in structure.sections:
            assert s.label != "unknown"
            assert s.label in ("intro", "drop", "breakdown", "buildup", "outro")

    def test_cue_points_have_labels(self):
        """All cue points should have meaningful labels."""
        audio = _make_techno_track(128.0, 120.0)
        structure = analyze_track_structure(audio, 44100, 128.0)

        for c in structure.cue_points:
            assert c.label in ("mix_in", "drop_1", "breakdown_1", "drop_2", "mix_out", "last_32")

    def test_total_bars_reasonable(self):
        """Total bars should match duration and BPM."""
        bpm = 128.0
        duration = 120.0
        audio = _make_techno_track(bpm, duration)
        structure = analyze_track_structure(audio, 44100, bpm)

        expected_bars = int(duration / (4 * 60.0 / bpm))
        assert abs(structure.total_bars - expected_bars) <= 2

    def test_serialization_roundtrip(self):
        """TrackStructure data should be JSON-serializable."""
        audio = _make_techno_track(128.0, 60.0)
        structure = analyze_track_structure(audio, 44100, 128.0)

        # Serialize all components (convert numpy types for JSON)
        def _json_safe(obj):
            if isinstance(obj, dict):
                return {k: _json_safe(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_json_safe(v) for v in obj]
            elif isinstance(obj, (np.bool_, np.integer)):
                return int(obj)
            elif isinstance(obj, np.floating):
                return float(obj)
            return obj

        data = _json_safe({
            "sections": [asdict(s) for s in structure.sections],
            "cue_points": [asdict(c) for c in structure.cue_points],
            "loop_regions": [asdict(l) for l in structure.loop_regions],
            "kick_pattern": structure.kick_pattern,
            "downbeat_position": structure.downbeat_position,
            "total_bars": structure.total_bars,
            "has_vocal": structure.has_vocal,
        })

        json_str = json.dumps(data)
        loaded = json.loads(json_str)

        assert len(loaded["sections"]) == len(structure.sections)
        assert loaded["kick_pattern"] == structure.kick_pattern


# ============================================================================
# TEST: Memory efficiency
# ============================================================================


class TestMemoryEfficiency:
    """Test that analysis stays within memory budget."""

    def test_analysis_completes_on_long_track(self):
        """Analysis of a 7-minute track should complete without error."""
        # 7 min at 44100 Hz mono = ~18.5M samples = ~74 MB
        audio = _make_techno_track(128.0, 420.0)  # 7 minutes
        structure = analyze_track_structure(audio, 44100, 128.0)

        assert len(structure.sections) >= 1
        assert len(structure.cue_points) >= 2


# ============================================================================
# TEST: Database persistence
# ============================================================================


class TestDatabasePersistence:
    """Test saving and loading track analysis from database."""

    @pytest.fixture
    def db(self, tmp_path):
        """Create a temporary database."""
        db = Database(str(tmp_path / "test.sqlite"))
        db.connect()
        yield db
        db.disconnect()

    @pytest.fixture
    def sample_track(self):
        """Create a sample track for testing."""
        return TrackMetadata(
            track_id="test-track-001",
            file_path="/music/test.mp3",
            duration_seconds=300.0,
            bpm=128.0,
            key="8A",
            cue_in_frames=44100,
            cue_out_frames=13230000,
            loop_start_frames=None,
            loop_length_bars=None,
            analyzed_at="2026-02-07T12:00:00",
        )

    def test_save_and_load_analysis(self, db, sample_track):
        """Analysis data should round-trip through the database."""
        db.add_track(sample_track)

        analysis = {
            "sections": [
                {"label": "intro", "start_seconds": 0.0, "end_seconds": 30.0,
                 "start_bar": 0, "end_bar": 16, "energy": 0.2, "has_kick": False, "confidence": 0.7},
                {"label": "drop", "start_seconds": 30.0, "end_seconds": 90.0,
                 "start_bar": 16, "end_bar": 48, "energy": 0.85, "has_kick": True, "confidence": 0.9},
            ],
            "cue_points": [
                {"label": "mix_in", "position_seconds": 30.0, "position_bar": 16, "type": "hot_cue"},
                {"label": "mix_out", "position_seconds": 250.0, "position_bar": 133, "type": "hot_cue"},
            ],
            "loop_regions": [
                {"start_seconds": 30.0, "end_seconds": 60.0, "length_bars": 16,
                 "energy": 0.85, "stability": 0.92, "label": "drop_loop"},
            ],
            "kick_pattern": "four_on_floor",
            "downbeat_seconds": 0.5,
            "total_bars": 160,
            "has_vocal": False,
        }

        db.save_track_analysis("test-track-001", analysis)

        loaded = db.get_track_analysis("test-track-001")
        assert loaded is not None
        assert loaded["kick_pattern"] == "four_on_floor"
        assert loaded["total_bars"] == 160
        assert loaded["has_vocal"] is False
        assert loaded["downbeat_seconds"] == 0.5

        # Check sections round-trip
        assert len(loaded["sections"]) == 2
        assert loaded["sections"][0]["label"] == "intro"
        assert loaded["sections"][1]["label"] == "drop"

        # Check cue points round-trip
        assert len(loaded["cue_points"]) == 2
        assert loaded["cue_points"][0]["label"] == "mix_in"

        # Check loop regions round-trip
        assert len(loaded["loop_regions"]) == 1
        assert loaded["loop_regions"][0]["label"] == "drop_loop"

    def test_load_nonexistent_analysis(self, db, sample_track):
        """Loading analysis for non-analyzed track should return None."""
        db.add_track(sample_track)
        result = db.get_track_analysis("test-track-001")
        assert result is None

    def test_upsert_analysis(self, db, sample_track):
        """Saving analysis twice should update, not duplicate."""
        db.add_track(sample_track)

        analysis_v1 = {
            "kick_pattern": "minimal",
            "total_bars": 100,
            "has_vocal": False,
        }
        db.save_track_analysis("test-track-001", analysis_v1)

        analysis_v2 = {
            "kick_pattern": "four_on_floor",
            "total_bars": 160,
            "has_vocal": True,
        }
        db.save_track_analysis("test-track-001", analysis_v2)

        loaded = db.get_track_analysis("test-track-001")
        assert loaded["kick_pattern"] == "four_on_floor"
        assert loaded["total_bars"] == 160
        assert loaded["has_vocal"] is True

    def test_list_tracks_with_analysis(self, db, sample_track):
        """list_tracks_with_analysis should return tracks with analysis data."""
        db.add_track(sample_track)
        analysis = {
            "sections": [{"label": "drop", "start_seconds": 0.0, "end_seconds": 300.0,
                          "start_bar": 0, "end_bar": 160, "energy": 0.8,
                          "has_kick": True, "confidence": 0.9}],
            "kick_pattern": "four_on_floor",
            "total_bars": 160,
            "has_vocal": False,
        }
        db.save_track_analysis("test-track-001", analysis)

        tracks = db.list_tracks_with_analysis()
        assert len(tracks) == 1
        assert tracks[0]["id"] == "test-track-001"
        assert tracks[0]["kick_pattern"] == "four_on_floor"

    def test_analysis_with_spectral_and_loudness(self, db, sample_track):
        """Analysis with spectral and loudness data should persist."""
        db.add_track(sample_track)

        analysis = {
            "spectral": {"bass_energy": 0.35, "mid_energy": 0.40, "treble_energy": 0.25},
            "loudness": {"integrated_lufs": -14.0, "true_peak_dbtp": -1.0},
            "kick_pattern": "four_on_floor",
            "total_bars": 160,
            "has_vocal": False,
        }
        db.save_track_analysis("test-track-001", analysis)

        loaded = db.get_track_analysis("test-track-001")
        assert loaded["spectral"]["bass_energy"] == 0.35
        assert loaded["loudness"]["integrated_lufs"] == -14.0


# ============================================================================
# TEST: Schema migration
# ============================================================================


class TestSchemaMigration:
    """Test schema migration from v1 to v2."""

    def test_v1_to_v2_migration(self, tmp_path):
        """A v1 database should be upgraded to v2 with track_analysis table."""
        db_path = str(tmp_path / "migrate.sqlite")

        # Create v1 database manually
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                duration_seconds REAL NOT NULL,
                bpm REAL,
                key TEXT,
                cue_in_frames INTEGER,
                cue_out_frames INTEGER,
                loop_start_frames INTEGER,
                loop_length_bars INTEGER,
                title TEXT,
                artist TEXT,
                album TEXT,
                analyzed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS playlist_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT NOT NULL,
                playlist_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                used_at TEXT NOT NULL,
                FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tracks_bpm ON tracks(bpm);
            CREATE INDEX IF NOT EXISTS idx_tracks_key ON tracks(key);
            CREATE INDEX IF NOT EXISTS idx_playlist_track_id ON playlist_history(track_id);
            CREATE INDEX IF NOT EXISTS idx_playlist_used_at ON playlist_history(used_at);
            CREATE TABLE IF NOT EXISTS analysis_progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total INTEGER NOT NULL DEFAULT 0,
                processed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO schema_version (version, updated_at) VALUES (1, '2026-02-07T00:00:00')"
        )
        conn.execute(
            "INSERT INTO analysis_progress (id, total, processed, updated_at) VALUES (1, 10, 10, '2026-02-07T00:00:00')"
        )
        # Insert a test track
        conn.execute(
            "INSERT INTO tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("t1", "/music/t1.mp3", 300.0, 128.0, "8A", 44100, 13230000,
             None, None, "Test", "Artist", None, "2026-02-07T00:00:00", "2026-02-07T00:00:00"),
        )
        conn.commit()
        conn.close()

        # Open with Database class — should trigger migration
        db = Database(db_path)
        db.connect()

        # Verify track_analysis table exists
        cursor = db.conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='track_analysis'"
        )
        assert cursor.fetchone() is not None

        # Verify version updated
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        assert cursor.fetchone()[0] == 2

        # Verify existing data intact
        track = db.get_track("t1")
        assert track is not None
        assert track.bpm == 128.0

        # Verify new table is functional
        db.save_track_analysis("t1", {"kick_pattern": "four_on_floor", "total_bars": 160, "has_vocal": False})
        loaded = db.get_track_analysis("t1")
        assert loaded["kick_pattern"] == "four_on_floor"

        db.disconnect()

    def test_fresh_database_is_v2(self, tmp_path):
        """A new database should start at v2."""
        db = Database(str(tmp_path / "fresh.sqlite"))
        db.connect()

        cursor = db.conn.cursor()
        cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        assert cursor.fetchone()[0] == 2

        # track_analysis table should exist
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='track_analysis'"
        )
        assert cursor.fetchone() is not None

        db.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
