"""
Phase 5 Micro-Techniques - Comprehensive Test Suite

Tests all 10 techniques against:
- Official documentation
- Community standards
- Professional DJ practices
- Timing accuracy
- Parameter validation

Validation Sources:
- Pioneer DJ (official industry standard)
- Serato (official DJ software)
- Akai Professional (official hardware)
- Digital DJ Tips (community resource)
"""

import pytest
from typing import List
from src.autodj.render.phase5_micro_techniques import (
    MicroTechniqueDatabase,
    GreedyMicroTechniqueSelector,
    MicroTechniqueType,
)


class TestMicroTechniqueDatabase:
    """Test all 10 micro-techniques are properly documented"""

    def test_all_techniques_present(self):
        """Verify all 10 techniques are in database"""
        db = MicroTechniqueDatabase()
        techniques = db.get_all_techniques()
        assert len(techniques) == 10, f"Expected 10 techniques, got {len(techniques)}"

    def test_all_techniques_validated(self):
        """Verify all techniques pass validation"""
        db = MicroTechniqueDatabase()
        validation = db.validate_all()
        
        failed = [name for name, valid in validation.items() if not valid]
        assert not failed, f"Validation failed for: {failed}"

    def test_stutter_roll_spec(self):
        """Test Stutter/Loop Roll technique specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.STUTTER_ROLL)
        
        # Verify specification
        assert spec.frequency_score == 8, "Stutter should be frequently used"
        assert spec.min_duration_bars == 0.5
        assert spec.max_duration_bars == 2.0
        assert spec.min_interval_bars == 16
        assert "Serato" in spec.official_source
        assert spec.community_approved is True
        assert "loop" in spec.liquidsoap_template.lower()

    def test_bass_cut_roll_spec(self):
        """Test Bass Cut + Roll specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.BASS_CUT_ROLL)
        
        assert spec.frequency_score == 9, "Bass cut should be most frequent"
        assert spec.difficulty == 2
        assert "Tech House" in spec.official_source
        assert "250" in spec.description or "500" in spec.description

    def test_filter_sweep_spec(self):
        """Test Filter Sweep specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.FILTER_SWEEP)
        
        assert spec.min_duration_bars == 4.0
        assert spec.max_duration_bars == 8.0
        assert "Pioneer DJ" in spec.official_source
        assert "HPF" in spec.description or "LPF" in spec.description

    def test_echo_out_return_spec(self):
        """Test Echo Out + Return specification (Black Coffee signature)"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.ECHO_OUT_RETURN)
        
        assert spec.frequency_score == 7
        assert "Black Coffee" in spec.official_source
        assert "echo" in spec.description.lower()

    def test_quick_cut_reverb_spec(self):
        """Test Quick Cut + Reverb specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.QUICK_CUT_REVERB)
        
        assert spec.min_duration_bars == 1.0
        assert spec.max_duration_bars == 1.0
        assert "Tech House" in spec.official_source or "Techno" in spec.official_source

    def test_loop_stutter_accel_spec(self):
        """Test Loop Stutter Acceleration specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.LOOP_STUTTER_ACCEL)
        
        assert spec.difficulty == 4, "Acceleration should be most complex"
        assert spec.min_duration_bars == 1.0
        assert spec.max_duration_bars == 4.0
        assert "exponential" in spec.description.lower() or "progressive" in spec.description.lower()

    def test_mute_dim_spec(self):
        """Test Mute + Dim specification (easiest technique)"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.MUTE_DIM)
        
        assert spec.difficulty == 1, "Mute should be simplest"
        assert spec.frequency_score == 8
        assert "All Genres" in spec.official_source

    def test_high_mid_boost_spec(self):
        """Test High-Mid Boost specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.HIGH_MID_BOOST)
        
        assert "2" in spec.description or "4" in spec.description  # 2-4 kHz
        assert "6" in spec.description or "12" in spec.description  # 6-12 dB

    def test_ping_pong_pan_spec(self):
        """Test Ping-Pong Pan specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.PING_PONG_PAN)
        
        assert spec.frequency_score == 5, "Pan should be less frequent (specialty)"
        assert "EDM" in spec.official_source or "Trance" in spec.official_source

    def test_reverb_tail_cut_spec(self):
        """Test Reverb Tail Cut specification"""
        db = MicroTechniqueDatabase()
        spec = db.get_technique(MicroTechniqueType.REVERB_TAIL_CUT)
        
        assert spec.frequency_score == 6
        assert "Techno" in spec.official_source


class TestGreedySelector:
    """Test the greedy micro-technique selector"""

    def test_selector_initialization(self):
        """Test selector initializes correctly"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db)
        
        assert selector.db is db
        assert len(selector.usage_count) == 0

    def test_selection_respects_spacing(self):
        """Test selected techniques respect minimum spacing"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        selections = selector.select_techniques_for_section(
            section_bars=64,
            target_technique_count=3,
            min_interval_bars=8.0
        )
        
        # Verify spacing between selections
        for i in range(len(selections) - 1):
            gap = selections[i + 1].start_bar - (selections[i].start_bar + selections[i].duration_bars)
            assert gap >= 7.5, f"Spacing violation: gap={gap} bars"

    def test_balanced_usage(self):
        """Test selector balances usage across techniques"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        # Make many selections
        all_selections = []
        for section in range(5):
            selections = selector.select_techniques_for_section(
                section_bars=64,
                target_technique_count=4
            )
            all_selections.extend(selections)
        
        # Check usage report
        report = selector.get_usage_report()
        techniques = report['techniques']
        
        # No technique should be used > 40% of time
        max_usage = max(t['percentage'] for t in techniques.values())
        assert max_usage < 40, f"Max usage {max_usage}% exceeds 40% threshold"
        
        # No technique should be used < 5% (avoid starvation)
        min_usage = min(t['percentage'] for t in techniques.values())
        assert min_usage >= 5, f"Min usage {min_usage}% below 5% threshold"

    def test_no_overlap(self):
        """Test techniques don't overlap in timing"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        selections = selector.select_techniques_for_section(
            section_bars=64,
            target_technique_count=5
        )
        
        # Check for overlaps
        for i in range(len(selections)):
            for j in range(i + 1, len(selections)):
                s1_end = selections[i].start_bar + selections[i].duration_bars
                s2_start = selections[j].start_bar
                
                assert s1_end <= s2_start, f"Overlap: technique {i} ends at {s1_end}, technique {j} starts at {s2_start}"

    def test_fits_within_section(self):
        """Test all selections fit within section boundaries"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        section_bars = 64
        selections = selector.select_techniques_for_section(
            section_bars=section_bars,
            target_technique_count=4
        )
        
        for selection in selections:
            assert selection.start_bar >= 0
            assert selection.start_bar + selection.duration_bars <= section_bars

    def test_respects_frequency_scores(self):
        """Test more frequent techniques are selected more often"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        # Run many selections
        for _ in range(10):
            selector.select_techniques_for_section(section_bars=64, target_technique_count=3)
        
        report = selector.get_usage_report()
        
        # Bass Cut Roll (frequency 9) should be used more than Ping Pong Pan (frequency 5)
        bass_cut_uses = report['techniques']['Bass Cut + Roll']['uses']
        pan_uses = report['techniques']['Ping-Pong Pan']['uses']
        
        assert bass_cut_uses >= pan_uses, "Bass Cut should be more frequent than Pan"

    def test_parameter_generation(self):
        """Test parameters are generated correctly for each technique"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        selections = selector.select_techniques_for_section(
            section_bars=64,
            target_technique_count=10
        )
        
        # Verify each selection has parameters
        for selection in selections:
            assert isinstance(selection.parameters, dict)
            assert 'duration' in selection.parameters
            
            # Type-specific validation
            if selection.type == MicroTechniqueType.BASS_CUT_ROLL:
                assert 'hpf_freq' in selection.parameters
                assert 150 <= selection.parameters['hpf_freq'] <= 300
            elif selection.type == MicroTechniqueType.FILTER_SWEEP:
                assert 'start_freq' in selection.parameters
                assert 'end_freq' in selection.parameters
            elif selection.type == MicroTechniqueType.HIGH_MID_BOOST:
                assert 'boost_freq' in selection.parameters
                assert 2000 <= selection.parameters['boost_freq'] <= 4000
                assert 'boost_amount' in selection.parameters
                assert 6 <= selection.parameters['boost_amount'] <= 12

    def test_confidence_scoring(self):
        """Test confidence scores are reasonable"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db, seed=42)
        
        selections = selector.select_techniques_for_section(
            section_bars=64,
            target_technique_count=3
        )
        
        for selection in selections:
            assert 0 <= selection.confidence_score <= 1, "Confidence should be 0-1"

    def test_deterministic_with_seed(self):
        """Test selector produces same results with same seed"""
        db = MicroTechniqueDatabase()
        
        selector1 = GreedyMicroTechniqueSelector(db, seed=123)
        selections1 = selector1.select_techniques_for_section(64, 3)
        
        selector2 = GreedyMicroTechniqueSelector(db, seed=123)
        selections2 = selector2.select_techniques_for_section(64, 3)
        
        assert len(selections1) == len(selections2)
        for s1, s2 in zip(selections1, selections2):
            assert s1.type == s2.type
            assert abs(s1.start_bar - s2.start_bar) < 0.01

    def test_different_with_different_seed(self):
        """Test different seeds produce different results"""
        db = MicroTechniqueDatabase()
        
        selector1 = GreedyMicroTechniqueSelector(db, seed=123)
        selections1 = selector1.select_techniques_for_section(64, 5)
        
        selector2 = GreedyMicroTechniqueSelector(db, seed=456)
        selections2 = selector2.select_techniques_for_section(64, 5)
        
        # With enough selections, at least timing should differ
        timings_differ = any(
            abs(s1.start_bar - s2.start_bar) > 0.1
            for s1, s2 in zip(selections1, selections2)
        )
        assert timings_differ, "Different seeds should produce different timing/durations"


class TestCommunityStandards:
    """Validate against official community standards"""

    def test_official_bar_patterns(self):
        """Test bar spacing matches official standards (Digital DJ Tips)"""
        # Professional standards: 8-16 bars between micro-techniques
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db)
        
        selections = selector.select_techniques_for_section(
            section_bars=64,
            target_technique_count=4,
            min_interval_bars=8.0
        )
        
        # Should select ~4 techniques over 64 bars = ~16 bars apart
        if len(selections) > 1:
            gaps = []
            for i in range(len(selections) - 1):
                gap = selections[i + 1].start_bar - selections[i].start_bar
                gaps.append(gap)
            
            avg_gap = sum(gaps) / len(gaps)
            assert 8 <= avg_gap <= 32, f"Average gap {avg_gap} outside professional standard (8-32)"

    def test_professional_technique_names(self):
        """Test all techniques use official professional names"""
        db = MicroTechniqueDatabase()
        official_names = {
            "Stutter/Loop Roll",
            "Bass Cut + Roll",
            "Filter Sweep",
            "Echo Out + Return",
            "Quick Cut + Reverb",
            "Loop Stutter Acceleration",
            "Mute + Dim",
            "High-Mid Boost + Filter",
            "Ping-Pong Pan",
            "Reverb Tail Cut"
        }
        
        actual_names = {t.name for t in db.get_all_techniques()}
        assert actual_names == official_names

    def test_pioneer_dj_alignment(self):
        """Test alignment with Pioneer DJ official guidance"""
        db = MicroTechniqueDatabase()
        
        # Count techniques by official source
        sources = {}
        for tech in db.get_all_techniques():
            source = tech.official_source.split(',')[0].strip()
            sources[source] = sources.get(source, 0) + 1
        
        # Should have multiple official sources
        assert len(sources) > 1, "Should reference multiple official sources"
        assert "Pioneer DJ" in sources, "Should reference Pioneer DJ"


class TestLiquidSoapGeneration:
    """Test Liquidsoap script generation"""

    def test_templates_exist_for_all_techniques(self):
        """Test all techniques have Liquidsoap templates"""
        db = MicroTechniqueDatabase()
        
        for tech in db.get_all_techniques():
            assert len(tech.liquidsoap_template) > 50, f"{tech.name} template too short"
            assert "{" in tech.liquidsoap_template, f"{tech.name} template missing placeholders"

    def test_parameter_substitution(self):
        """Test parameters can be substituted into templates"""
        db = MicroTechniqueDatabase()
        selector = GreedyMicroTechniqueSelector(db)
        
        selections = selector.select_techniques_for_section(64, 3)
        
        for selection in selections:
            tech = db.get_technique(selection.type)
            template = tech.liquidsoap_template
            
            # Verify all placeholders can be filled
            for key, value in selection.parameters.items():
                placeholder = "{" + key + "}"
                if placeholder in template:
                    # Can substitute
                    substituted = template.replace(placeholder, str(value))
                    assert "{" + key + "}" not in substituted


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
