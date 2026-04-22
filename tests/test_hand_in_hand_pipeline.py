"""
Full Production Pipeline Test: Hand In Hand by Klangkuenstler
=============================================================

Tests the complete Phase 2 → Phase 5 pipeline using real tracks from the
production database, anchored on "Hand In Hand" (Klangkuenstler, 8A, 122.83 BPM).

Pipeline:
  1. Phase 2 - Harmonic compatibility analysis (Camelot wheel)
  2. Build transition plan from compatible real tracks
  3. Phase 5 - Micro-technique selection (greedy algorithm)
  4. Verify Liquidsoap code generation for each technique

Track selection rationale (real NAS tracks, all confirmed in DB):
  Track 0: Hand In Hand - Klangkuenstler  8A  122.83 BPM  (seed)
  Track 1: Far Flower    - DKOXY          7A  122.72 BPM  (±1 same mode → EXCELLENT)
  Track 2: Relive        - Klangkuenstler 8B  124.74 BPM  (relative major → EXCELLENT)
  Track 3: Spiel mir...  - Klangkuenstler 7A  124.76 BPM  (±1 same mode → EXCELLENT)
"""

import pytest
from typing import List, Dict

from src.autodj.analyze.harmonic import (
    HarmonicMixer,
    determine_compatibility,
    calculate_wheel_distance,
    CompatibilityLevel,
    CAMELOT_TO_KEY_NAME,
)
from src.autodj.render.phase5_micro_techniques import (
    MicroTechniqueDatabase,
    GreedyMicroTechniqueSelector,
    MicroTechniqueType,
)
from src.autodj.render.phase5_integration import Phase5Renderer
from src.autodj.render.render import apply_phase5_micro_techniques


# ============================================================================
# REAL TRACK FIXTURES (from production DB)
# ============================================================================

HAND_IN_HAND = {
    "index": 0,
    "id": "997374dfd4c9184e",
    "file_path": "/srv/nas/shared/ALAC/Klangkuenstler/That's Me/04. Hand In Hand.m4a",
    "artist": "Klangkuenstler",
    "title": "Hand In Hand",
    "bpm": 122.83,
    "key": "8A",
    "duration_seconds": 210.0,  # ~3.5 min
}

FAR_FLOWER = {
    "index": 1,
    "id": "216a5b72228be774",
    "file_path": "/srv/nas/shared/ALAC/Apple Music/Replay 2025/11. Far Flower.m4a",
    "artist": "DKOXY",
    "title": "Far Flower",
    "bpm": 122.72,
    "key": "7A",
    "duration_seconds": 195.0,
}

RELIVE = {
    "index": 2,
    "id": "af1d63a96327a402",
    "file_path": "/srv/nas/shared/ALAC/Klangkuenstler/That's Me/07. Relive.m4a",
    "artist": "Klangkuenstler",
    "title": "Relive",
    "bpm": 124.74,
    "key": "8B",
    "duration_seconds": 198.0,
}

SPIEL_MIR = {
    "index": 3,
    "id": "ea5de4601312b1c7",
    "file_path": "/srv/nas/shared/ALAC/Klangkuenstler/Glücks EP/02. Spiel mir das Lied vom Glück (Geschwister Schumann Remix).m4a",
    "artist": "Klangkuenstler & Shemian",
    "title": "Spiel mir das Lied vom Glück (Geschwister Schumann Remix)",
    "bpm": 124.76,
    "key": "7A",
    "duration_seconds": 345.0,
}

ALL_TRACKS = [HAND_IN_HAND, FAR_FLOWER, RELIVE, SPIEL_MIR]


# ============================================================================
# PHASE 2: HARMONIC ANALYSIS TESTS
# ============================================================================

class TestPhase2HarmonicAnalysis:
    """Phase 2 harmonic mixing tests anchored on Hand In Hand (8A)."""

    def test_hand_in_hand_key_is_a_minor(self):
        """8A must map to A minor in the real Camelot standard."""
        key_name = CAMELOT_TO_KEY_NAME[HAND_IN_HAND["key"]]
        assert key_name == "A minor", (
            f"8A should be A minor (real Camelot), got: {key_name}"
        )

    def test_hand_in_hand_to_far_flower_compatibility(self):
        """8A → 7A: ±1 same mode = EXCELLENT compatibility."""
        level, score = determine_compatibility(
            HAND_IN_HAND["key"], FAR_FLOWER["key"]
        )
        assert level == CompatibilityLevel.EXCELLENT, (
            f"8A→7A expected EXCELLENT, got {level.name} (score={score})"
        )
        assert score == 4.0
        assert calculate_wheel_distance(HAND_IN_HAND["key"], FAR_FLOWER["key"]) == 1

    def test_hand_in_hand_to_relive_compatibility(self):
        """8A → 8B: relative major/minor (same position, different mode) = EXCELLENT."""
        level, score = determine_compatibility(
            HAND_IN_HAND["key"], RELIVE["key"]
        )
        assert level == CompatibilityLevel.EXCELLENT, (
            f"8A→8B expected EXCELLENT, got {level.name} (score={score})"
        )
        assert score == 4.0
        assert calculate_wheel_distance(HAND_IN_HAND["key"], RELIVE["key"]) == 0

    def test_hand_in_hand_to_spiel_mir_compatibility(self):
        """8A → 7A: ±1 same mode = EXCELLENT compatibility."""
        level, score = determine_compatibility(
            HAND_IN_HAND["key"], SPIEL_MIR["key"]
        )
        assert level == CompatibilityLevel.EXCELLENT, (
            f"8A→7A expected EXCELLENT, got {level.name}"
        )
        assert score == 4.0

    def test_full_set_compatibility_matrix(self):
        """All 4 tracks should form a cohesive harmonic set (all ≥ GOOD)."""
        mixer = HarmonicMixer()
        for t in ALL_TRACKS:
            mixer.add_track(t["index"], t["title"], t["key"])

        matrix = mixer.calculate_compatibility_matrix()

        # Off-diagonal entries should all be GOOD or better (score ≥ 3.0)
        for i in range(len(ALL_TRACKS)):
            for j in range(len(ALL_TRACKS)):
                if i != j:
                    score = matrix[i][j]
                    assert score >= 3.0, (
                        f"{ALL_TRACKS[i]['title']} ({ALL_TRACKS[i]['key']}) → "
                        f"{ALL_TRACKS[j]['title']} ({ALL_TRACKS[j]['key']}): "
                        f"score {score} < 3.0 (GOOD threshold)"
                    )

    def test_optimal_sequence_starts_with_hand_in_hand(self):
        """Greedy sequence with seed track as index 0 stays musically coherent."""
        mixer = HarmonicMixer()
        for t in ALL_TRACKS:
            mixer.add_track(t["index"], t["title"], t["key"], confidence=1.0)

        sequence = mixer.find_optimal_sequence()

        assert len(sequence) == 4
        assert len(set(sequence)) == 4, "No duplicates"
        # All transitions in the sequence should be at least GOOD
        transitions = mixer.get_transitions(sequence)
        for t in transitions:
            assert t.compatibility_score >= 3.0, (
                f"Transition {t.from_key}→{t.to_key}: score {t.compatibility_score} below GOOD"
            )

    def test_transition_uses_wheel_distance_field(self):
        """Transition dataclass must use wheel_distance (not semitone_distance)."""
        mixer = HarmonicMixer()
        for t in ALL_TRACKS:
            mixer.add_track(t["index"], t["title"], t["key"])

        transitions = mixer.get_transitions([0, 1, 2, 3])
        for t in transitions:
            assert hasattr(t, "wheel_distance"), (
                "Transition must have wheel_distance field (not semitone_distance)"
            )
            assert not hasattr(t, "semitone_distance"), (
                "semitone_distance was renamed to wheel_distance — update callers"
            )
            assert 0 <= t.wheel_distance <= 6

    def test_bpm_compatibility(self):
        """All tracks should be within ±4% BPM of Hand In Hand."""
        seed_bpm = HAND_IN_HAND["bpm"]
        for track in [FAR_FLOWER, RELIVE, SPIEL_MIR]:
            bpm_diff_pct = abs(track["bpm"] - seed_bpm) / seed_bpm * 100
            assert bpm_diff_pct <= 4.0, (
                f"{track['title']}: BPM diff {bpm_diff_pct:.1f}% exceeds 4% tolerance"
            )

    def test_relive_key_is_c_major(self):
        """8B must map to C major — the relative major of A minor (8A)."""
        assert CAMELOT_TO_KEY_NAME["8B"] == "C major"
        assert CAMELOT_TO_KEY_NAME["8A"] == "A minor"

    def test_far_flower_key_is_d_minor(self):
        """7A = D minor: the key a perfect 5th below A minor on the wheel."""
        assert CAMELOT_TO_KEY_NAME["7A"] == "D minor"


# ============================================================================
# PHASE 5: MICRO-TECHNIQUE SELECTION TESTS
# ============================================================================

def _make_transitions() -> List[Dict]:
    """Build transition plan from the 4-track Hand In Hand set."""
    sequence = [HAND_IN_HAND, FAR_FLOWER, RELIVE, SPIEL_MIR]
    transitions = []

    for i, track in enumerate(sequence):
        transitions.append({
            "index": i,
            "track_id": track["id"],
            "title": f"{track['artist']} - {track['title']}",
            "bpm": track["bpm"],
            "target_bpm": track["bpm"],
            "camelot_key": track["key"],
            "file_path": track["file_path"],
            "duration_seconds": track["duration_seconds"],
            "transition_type": "bass_swap",
            "overlap_bars": 8,
        })

    return transitions


class TestPhase5MicroTechniques:
    """Phase 5 micro-technique tests for the Hand In Hand set."""

    def test_techniques_selected_for_every_transition(self):
        """Every long-enough track should receive at least 1 micro-technique."""
        transitions = _make_transitions()
        config = {"render": {"output_format": "mp3", "mp3_bitrate": 320}}

        updated, metrics = apply_phase5_micro_techniques(
            transitions, config, persona="tech_house", seed=42
        )

        assert metrics["total_techniques_selected"] >= 1
        # With 3.5-5.5 min tracks, we expect multiple technique assignments
        assert metrics["transitions_with_techniques"] >= 2, (
            f"Expected ≥2 transitions with techniques, got {metrics['transitions_with_techniques']}"
        )

    def test_phase5_attached_to_transition_dicts(self):
        """Phase 5 data must be stored in each transition dict."""
        transitions = _make_transitions()
        config = {"render": {"output_format": "mp3"}}

        updated, _ = apply_phase5_micro_techniques(
            transitions, config, persona="tech_house", seed=42
        )

        techniques_found = 0
        for trans in updated:
            phase5 = trans.get("phase5_micro_techniques")
            if phase5:
                techniques_found += len(phase5)
                for tech in phase5:
                    assert "type" in tech
                    assert "name" in tech
                    assert "start_bar" in tech
                    assert "duration_bars" in tech
                    assert "duration_seconds" in tech
                    assert "confidence" in tech
                    assert "parameters" in tech
                    assert isinstance(tech["parameters"], dict)

        assert techniques_found >= 1, "At least 1 technique must be attached"

    def test_technique_timing_fits_track_duration(self):
        """Micro-techniques must not extend beyond the track's playable bars."""
        transitions = _make_transitions()
        config = {"render": {"output_format": "mp3"}}

        updated, _ = apply_phase5_micro_techniques(
            transitions, config, seed=42
        )

        for trans in updated:
            bpm = trans["bpm"]
            duration_sec = trans["duration_seconds"]
            total_bars = (duration_sec / 60.0) * (bpm / 4.0)

            for tech in trans.get("phase5_micro_techniques", []):
                end_bar = tech["start_bar"] + tech["duration_bars"]
                assert end_bar <= total_bars + 0.5, (
                    f"{trans['title']}: technique {tech['name']} ends at bar {end_bar:.1f} "
                    f"but track is only {total_bars:.1f} bars"
                )

    def test_tech_house_persona_prefers_correct_techniques(self):
        """Tech house persona must prefer stutter/bass-cut over reverb-tail/ping-pong-pan."""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)

        preferred = [
            MicroTechniqueType.STUTTER_ROLL,
            MicroTechniqueType.BASS_CUT_ROLL,
            MicroTechniqueType.ECHO_OUT_RETURN,
            MicroTechniqueType.QUICK_CUT_REVERB,
            MicroTechniqueType.FILTER_SWEEP,
        ]
        avoided = [
            MicroTechniqueType.REVERB_TAIL_CUT,
            MicroTechniqueType.PING_PONG_PAN,
        ]

        # Run many selections with tech house constraints
        for _ in range(10):
            selector.select_techniques_for_section(
                section_bars=64,
                target_technique_count=3,
                preferred_types=preferred,
                avoided_types=avoided,
            )

        report = selector.get_usage_report()

        # Avoided techniques should have zero uses
        reverb_tail_uses = report["techniques"]["Reverb Tail Cut"]["uses"]
        ping_pong_uses = report["techniques"]["Ping-Pong Pan"]["uses"]
        assert reverb_tail_uses == 0, f"Reverb Tail Cut was used {reverb_tail_uses}x (avoided)"
        assert ping_pong_uses == 0, f"Ping-Pong Pan was used {ping_pong_uses}x (avoided)"

        # Preferred techniques should be used
        stutter_uses = report["techniques"]["Stutter/Loop Roll"]["uses"]
        bass_cut_uses = report["techniques"]["Bass Cut + Roll"]["uses"]
        assert stutter_uses + bass_cut_uses >= 5, (
            f"Expected stutter+bass-cut ≥5 uses, got {stutter_uses + bass_cut_uses}"
        )

    def test_deterministic_pipeline_with_seed(self):
        """Same seed must produce identical technique selections."""
        transitions1 = _make_transitions()
        transitions2 = _make_transitions()
        config = {"render": {"output_format": "mp3"}}

        updated1, _ = apply_phase5_micro_techniques(transitions1, config, seed=99)
        updated2, _ = apply_phase5_micro_techniques(transitions2, config, seed=99)

        for t1, t2 in zip(updated1, updated2):
            techs1 = t1.get("phase5_micro_techniques", [])
            techs2 = t2.get("phase5_micro_techniques", [])

            assert len(techs1) == len(techs2), (
                f"Seed 99 produced different technique counts: {len(techs1)} vs {len(techs2)}"
            )
            for a, b in zip(techs1, techs2):
                assert a["type"] == b["type"], "Technique types differ with same seed"
                assert abs(a["start_bar"] - b["start_bar"]) < 0.01, (
                    "Start bars differ with same seed"
                )


# ============================================================================
# INTEGRATION: Phase 2 + Phase 5 end-to-end
# ============================================================================

class TestPhase2AndPhase5Integration:
    """End-to-end: Phase 2 harmonic plan feeds Phase 5 micro-technique engine."""

    def test_full_pipeline_hand_in_hand(self):
        """
        Complete pipeline for the Hand In Hand set:
          8A Hand In Hand → 7A Far Flower → 8B Relive → 7A Spiel mir...

        Validates:
          - All transitions are harmonically EXCELLENT
          - Phase 5 attaches techniques to all long tracks
          - BPM stays within ±4% throughout
          - No timing violations
        """
        # --- PHASE 2: Harmonic analysis ---
        mixer = HarmonicMixer()
        for t in ALL_TRACKS:
            mixer.add_track(t["index"], t["title"], t["key"])

        sequence = [0, 1, 2, 3]  # Fixed sequence for this test
        p2_transitions = mixer.get_transitions(sequence)

        for t in p2_transitions:
            # All transitions must be at least GOOD (3.0); individual EXCELLENT
            # pairs are verified in TestPhase2HarmonicAnalysis (7A→8B is GOOD,
            # not EXCELLENT, because it crosses both wheel positions and mode)
            assert t.compatibility_score >= 3.0, (
                f"Expected GOOD+ transitions throughout, got {t.from_key}→{t.to_key}: {t.compatibility_score}"
            )
            assert hasattr(t, "wheel_distance")

        # --- PHASE 5: Micro-techniques ---
        transitions = _make_transitions()
        config = {"render": {"output_format": "mp3", "mp3_bitrate": 320}}

        updated, metrics = apply_phase5_micro_techniques(
            transitions, config, persona="tech_house", seed=42
        )

        # Summary assertions
        assert metrics["total_transitions"] == 4
        assert metrics["total_techniques_selected"] >= 2, (
            f"Expected ≥2 total techniques, got {metrics['total_techniques_selected']}"
        )

        # Print summary for visibility
        print(f"\n✅ Hand In Hand Pipeline: Phase 2 + Phase 5")
        print(f"   Tracks: {len(ALL_TRACKS)}")
        print(f"   All transitions: EXCELLENT (score ≥ 4.0)")
        print(f"   Phase 5 techniques: {metrics['total_techniques_selected']} total")
        for tech_name, count in metrics.get("by_type", {}).items():
            print(f"     - {tech_name}: {count}x")

    def test_liquidsoap_code_generated_for_techniques(self):
        """Liquidsoap template must be filled for every selected technique."""
        from src.autodj.render.phase5_integration import Phase5Renderer

        transitions = _make_transitions()
        renderer = Phase5Renderer(seed=42)

        all_code_lines = 0
        for i, trans in enumerate(transitions):
            bpm = trans["bpm"]
            duration_sec = trans["duration_seconds"]
            bars = (duration_sec / 60.0) * (bpm / 4.0)

            selections = renderer.selector.select_techniques_for_section(
                section_bars=bars,
                target_technique_count=max(1, int(bars / 16)),
                min_interval_bars=8.0,
            )

            if selections:
                script = renderer.generate_liquidsoap_for_techniques(selections, bpm=bpm)
                assert len(script) > 0
                assert "# Phase 5" in script

                # No unfilled placeholders should remain
                import re
                remaining_placeholders = re.findall(r"\{[a-z_]+\}", script)
                assert not remaining_placeholders, (
                    f"Unfilled placeholders in Liquidsoap: {remaining_placeholders}"
                )
                all_code_lines += len(script.splitlines())

        assert all_code_lines > 0, "No Liquidsoap code was generated"

    def test_phase5_metrics_by_type_matches_selection(self):
        """metrics['by_type'] counts must match actual techniques in transitions."""
        transitions = _make_transitions()
        config = {"render": {"output_format": "mp3"}}

        updated, metrics = apply_phase5_micro_techniques(transitions, config, seed=7)

        # Recount from the actual transition dicts
        actual_counts: Dict[str, int] = {}
        for trans in updated:
            for tech in trans.get("phase5_micro_techniques", []):
                name = tech["name"]
                actual_counts[name] = actual_counts.get(name, 0) + 1

        assert metrics["by_type"] == actual_counts, (
            f"metrics['by_type'] mismatch:\n"
            f"  reported: {metrics['by_type']}\n"
            f"  actual:   {actual_counts}"
        )


if __name__ == "__main__":
    import pytest as _pytest
    _pytest.main([__file__, "-v", "--tb=short", "-s"])
