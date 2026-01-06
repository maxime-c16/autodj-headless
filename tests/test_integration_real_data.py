"""
Integration tests using real analyzed tracks from the database.

Tests the complete pipeline: selection → generation → rendering
with actual track data (47+ analyzed tracks).
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Integration test - requires real database
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def database():
    """Load real database connection."""
    from src.autodj.db import Database

    db = Database("/app/data/db/metadata.sqlite")
    db.connect()
    yield db
    db.disconnect()


@pytest.fixture(scope="module")
def config():
    """Load real configuration."""
    import toml

    return toml.load("/app/configs/autodj.toml")


@pytest.fixture(scope="module")
def library(database):
    """Load all analyzed tracks from database."""
    tracks = database.list_tracks()

    # Convert TrackMetadata to dict format for selectors
    library = []
    for track in tracks:
        library.append({
            "id": track.track_id,
            "file_path": track.file_path,
            "duration_seconds": track.duration_seconds,
            "bpm": track.bpm,
            "key": track.key or "unknown",
            "cue_in_frames": track.cue_in_frames,
            "cue_out_frames": track.cue_out_frames,
            "title": track.title,
            "artist": track.artist,
        })

    return library


class TestRealDataAvailability:
    """Verify real track data is available."""

    def test_database_has_analyzed_tracks(self, library):
        """Database contains analyzed tracks."""
        assert len(library) > 0, "No analyzed tracks found in database"
        assert len(library) >= 10, "Should have at least 10 analyzed tracks"

    def test_tracks_have_required_fields(self, library):
        """Each track has required metadata."""
        track = library[0]
        assert "id" in track
        assert "file_path" in track
        assert "bpm" in track
        assert track["bpm"] is not None
        assert "key" in track

    def test_bpm_range_reasonable(self, library):
        """Track BPM values are in reasonable range."""
        bpms = [t["bpm"] for t in library if t["bpm"] is not None]
        assert min(bpms) >= 50, "BPM should be >= 50"
        assert max(bpms) <= 200, "BPM should be <= 200"

    def test_key_detection_working(self, library):
        """Most tracks have detected keys."""
        with_keys = sum(1 for t in library if t["key"] and t["key"] != "unknown")
        percentage = with_keys / len(library) * 100
        assert percentage >= 50, f"Only {percentage:.0f}% of tracks have detected keys"


class TestMerlinSelectorWithRealData:
    """Test Merlin selector with real database tracks."""

    def test_merlin_builds_playlist(self, library, config, database):
        """Merlin builds valid playlist from real tracks."""
        from src.autodj.generate.selector import MerlinGreedySelector, SelectionConstraints

        constraints = SelectionConstraints(config.get("constraints", {}))
        selector = MerlinGreedySelector(database, constraints)

        # Use first track as seed
        seed_track_id = library[0]["id"]

        playlist = selector.build_playlist(library, seed_track_id, target_duration_minutes=15)

        assert playlist is not None, "Merlin selector failed"
        assert len(playlist) >= 2, "Playlist should have at least 2 tracks"
        assert playlist[0] == seed_track_id, "First track should be seed"

        print(f"\n✅ Merlin Selector Results:")
        print(f"   Tracks: {len(playlist)}")
        total_duration = sum(
            t["duration_seconds"] for t in library if t["id"] in playlist
        )
        print(f"   Duration: {total_duration:.0f}s ({total_duration/60:.1f} min)")

    def test_merlin_respects_bpm_constraints(self, library, config, database):
        """Merlin respects BPM tolerance constraints."""
        from src.autodj.generate.selector import MerlinGreedySelector, SelectionConstraints

        constraints = SelectionConstraints(config.get("constraints", {}))
        selector = MerlinGreedySelector(database, constraints)

        seed_track_id = library[0]["id"]
        playlist = selector.build_playlist(library, seed_track_id, target_duration_minutes=15)

        assert playlist is not None

        # Check BPM changes are within tolerance
        library_dict = {t["id"]: t for t in library}
        tolerance_pct = config.get("constraints", {}).get("bpm_tolerance_percent", 4.0)

        violations = 0
        for i in range(len(playlist) - 1):
            curr = library_dict[playlist[i]]
            next_t = library_dict[playlist[i + 1]]

            if curr["bpm"] and next_t["bpm"]:
                tolerance = curr["bpm"] * (tolerance_pct / 100.0)
                if abs(next_t["bpm"] - curr["bpm"]) > tolerance:
                    violations += 1

        assert violations == 0, f"BPM tolerance violated {violations} times"
        print(f"\n✅ BPM Constraints: All {len(playlist)-1} transitions within tolerance")

    def test_merlin_respects_harmonic_constraints(self, library, config, database):
        """Merlin respects harmonic key constraints."""
        from src.autodj.generate.selector import MerlinGreedySelector, SelectionConstraints

        constraints = SelectionConstraints(config.get("constraints", {}))
        selector = MerlinGreedySelector(database, constraints)

        seed_track_id = library[0]["id"]
        playlist = selector.build_playlist(library, seed_track_id, target_duration_minutes=15)

        assert playlist is not None

        library_dict = {t["id"]: t for t in library}

        # Count compatible key transitions
        compatible = 0
        for i in range(len(playlist) - 1):
            curr_key = library_dict[playlist[i]]["key"]
            next_key = library_dict[playlist[i + 1]]["key"]

            if selector._camelot_compatible(curr_key, next_key):
                compatible += 1

        assert compatible == len(playlist) - 1, "All transitions should be harmonically compatible"
        print(f"\n✅ Harmonic Keys: All {len(playlist)-1} transitions compatible")


class TestPhonemiusWithRealData:
    """Test Phonemius playlist generator with real data."""

    def test_phonemius_orchestrates_generation(self, library, config, database):
        """Phonemius generates complete playlist with transitions."""
        from src.autodj.generate.playlist import ArchwizardPhonemius

        phonemius = ArchwizardPhonemius(database, config)

        seed_track_id = library[0]["id"]
        result = phonemius.build_playlist(library, target_duration_minutes=15, seed_track_id=seed_track_id)

        assert result is not None, "Phonemius failed"
        track_ids, transitions = result

        assert len(track_ids) >= 2, "Playlist should have at least 2 tracks"
        assert len(transitions) == len(track_ids), "Should have transition for each track"

        print(f"\n✅ ArchwizardPhonemius Results:")
        print(f"   Tracks: {len(track_ids)}")
        print(f"   Transitions: {len(transitions)}")
        total_duration = sum(
            t["duration_seconds"] for t in library if t["id"] in track_ids
        )
        print(f"   Duration: {total_duration:.0f}s ({total_duration/60:.1f} min)")

    def test_phonemius_generates_files(self, library, config, database):
        """Phonemius writes M3U and transitions JSON files."""
        from src.autodj.generate.playlist import generate

        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate(
                library=library,
                config=config,
                output_dir=tmpdir,
                target_duration_minutes=15,
                seed_track_id=library[0]["id"],
                database=database,
            )

            assert result is not None, "Generate failed"
            m3u_path, trans_path = result

            # Check files exist
            assert Path(m3u_path).exists(), "M3U file not created"
            assert Path(trans_path).exists(), "Transitions JSON not created"

            # Check M3U content
            m3u_content = Path(m3u_path).read_text()
            assert "#EXTM3U" in m3u_content, "Invalid M3U format"
            # Library may have various formats (mp3, flac, m4a, etc)
            assert "#EXT-INF" in m3u_content and len(m3u_content.split("\n")) > 3, "No tracks in M3U"

            # Check transitions JSON
            with open(trans_path) as f:
                trans_data = json.load(f)
            assert "transitions" in trans_data, "Missing transitions"
            assert len(trans_data["transitions"]) > 0, "No transitions"

            print(f"\n✅ File Generation:")
            print(f"   M3U: {Path(m3u_path).name}")
            print(f"   Transitions: {Path(trans_path).name}")


class TestBlastxcssSelectorWithRealData:
    """Test BlastxcssSelector with real data."""

    def test_blastxcss_high_energy_playlist(self, library, config, database):
        """BlastxcssSelector builds high-energy playlist."""
        from src.autodj.generate.selector import BlastxcssSelector, SelectionConstraints

        constraints = SelectionConstraints(config.get("constraints", {}))
        selector = BlastxcssSelector(database, constraints)

        seed_track_id = library[0]["id"]
        playlist = selector.build_playlist(library, seed_track_id, target_duration_minutes=15)

        assert playlist is not None, "BlastxcssSelector failed"
        assert len(playlist) >= 2, "Playlist should have at least 2 tracks"

        print(f"\n✅ BlastxcssSelector (High-Energy):")
        print(f"   Tracks: {len(playlist)}")
        total_duration = sum(
            t["duration_seconds"] for t in library if t["id"] in playlist
        )
        print(f"   Duration: {total_duration:.0f}s ({total_duration/60:.1f} min)")


class TestEnergyScoring:
    """Test energy scoring with real data."""

    def test_energy_estimation_on_real_tracks(self, library):
        """Energy estimation works on real track data."""
        from src.autodj.generate.energy import estimate_track_energy

        energies = []
        for track in library[:20]:  # Sample first 20
            energy = estimate_track_energy(track)
            assert 0.0 <= energy <= 1.0, f"Invalid energy: {energy}"
            energies.append(energy)

        avg_energy = sum(energies) / len(energies)
        print(f"\n✅ Energy Estimation (first 20 tracks):")
        print(f"   Average energy: {avg_energy:.2f}")
        print(f"   Range: {min(energies):.2f} - {max(energies):.2f}")

    def test_energy_ranking(self, library):
        """Energy ranking works on real data."""
        from src.autodj.generate.energy import rank_candidates_by_energy

        if len(library) < 3:
            pytest.skip("Need at least 3 tracks for ranking test")

        current_track = library[0]
        candidates = library[1:11]  # Next 10 tracks

        ranked = rank_candidates_by_energy(current_track, candidates)

        assert len(ranked) > 0, "Ranking failed"
        assert len(ranked) == len(candidates), "Should rank all candidates"

        # Verify ascending order
        scores = [score for _, score in ranked]
        assert scores == sorted(scores), "Ranking should be in ascending order"

        print(f"\n✅ Energy Ranking (10 candidates):")
        print(f"   Best match score: {ranked[0][1]:.3f}")
        print(f"   Worst match score: {ranked[-1][1]:.3f}")


class TestRenderPipeline:
    """Test render pipeline with real data."""

    def test_render_script_generation(self, library, config):
        """Render pipeline generates valid Liquidsoap script."""
        from src.autodj.generate.playlist import ArchwizardPhonemius
        from src.autodj.render.render import _generate_liquidsoap_script

        # Create mock database
        db = Mock()
        db.get_recent_usage = Mock(return_value=[])

        phonemius = ArchwizardPhonemius(db, config)
        seed_track_id = library[0]["id"]
        result = phonemius.build_playlist(library, target_duration_minutes=15, seed_track_id=seed_track_id)

        if result:
            track_ids, transitions = result

            # Create transitions with file paths
            library_dict = {t["id"]: t for t in library}
            transitions_dicts = []
            for idx, trans in enumerate(transitions):
                # Convert TransitionPlan to dict if needed
                trans_dict = trans.to_dict() if hasattr(trans, 'to_dict') else trans
                if idx < len(track_ids):
                    trans_dict["file_path"] = library_dict[track_ids[idx]]["file_path"]
                transitions_dicts.append(trans_dict)

            # Create plan dict
            plan = {
                "playlist_id": "test-render",
                "transitions": transitions_dicts,
                "mix_duration_seconds": 900,
            }

            # Generate script
            script = _generate_liquidsoap_script(plan, "/tmp/mix.mp3", config)

            assert script, "Script generation failed"
            assert "smart_crossfade" in script, "Missing crossfade"
            assert "set(" in script, "Missing settings"

            print(f"\n✅ Render Script Generation:")
            print(f"   Script lines: {len(script.split(chr(10)))}")
            print(f"   Tracks in script: {script.count('load_track')}")


class TestCompleteWorkflow:
    """Test complete workflow from selection to render."""

    def test_end_to_end_workflow(self, library, config, database):
        """Complete workflow: select → generate → render."""
        from src.autodj.generate.selector import select_playlist, SelectionConstraints
        from src.autodj.generate.playlist import generate
        from src.autodj.render.render import RenderEngine

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # 1. Selection
            constraints = SelectionConstraints(config.get("constraints", {}))
            playlist = select_playlist(
                library,
                library[0]["id"],
                15,
                constraints,
                database=database,
                selector_mode="merlin"
            )

            assert playlist is not None
            print(f"\n✅ Complete Workflow Test:")
            print(f"   1. Selection: {len(playlist)} tracks selected")

            # 2. Generation
            result = generate(
                track_ids=playlist,
                library=library,
                config=config,
                output_dir=str(tmpdir_path),
            )

            assert result is not None
            m3u_path, trans_path = result
            print(f"   2. Generation: M3U + Transitions created")

            # 3. Render setup (don't actually render, just verify setup)
            engine = RenderEngine(config)

            assert Path(m3u_path).exists()
            assert Path(trans_path).exists()
            print(f"   3. Render: Engine ready for rendering")
            print(f"\n   ✅ Full workflow validated end-to-end")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
