#!/usr/bin/env python3
"""
Debug script for Liquidsoap rendering failures.

This script:
1. Generates a simple playlist from real tracks
2. Creates the Liquidsoap script
3. Writes script to disk for inspection
4. Runs Liquidsoap with full error output
5. Shows why rendering is failing
"""

import sys
import json
import tempfile
import subprocess
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.autodj.db import Database
from src.autodj.generate.playlist import generate
from src.autodj.render.render import _generate_liquidsoap_script
import toml

def main():
    # Find config path - try local first, then /app
    config_path = Path(__file__).parent.parent.parent / "configs" / "autodj.toml"
    if not config_path.exists():
        config_path = Path("/app/configs/autodj.toml")

    print(f"📋 Using config: {config_path}\n")
    config = toml.load(str(config_path))

    # Find database path
    db_path = Path(__file__).parent.parent.parent / "data" / "db" / "metadata.sqlite"
    if not db_path.exists():
        db_path = Path("/app/data/db/metadata.sqlite")

    print(f"📊 Using database: {db_path}\n")
    db = Database(str(db_path))
    db.connect()

    # Get all tracks
    all_tracks = db.list_tracks()
    print(f"📚 Database has {len(all_tracks)} analyzed tracks\n")

    if len(all_tracks) < 3:
        print("❌ Not enough tracks in database for rendering")
        db.disconnect()
        return False

    # Convert to library format
    library = []
    for track in all_tracks:
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

    print(f"✅ Loaded {len(library)} tracks\n")

    # Generate playlist with real tracks
    print("🎵 GENERATING PLAYLIST...")
    print("-" * 80)

    with tempfile.TemporaryDirectory() as tmpdir:
        result = generate(
            library=library,
            config=config,
            output_dir=tmpdir,
            target_duration_minutes=15,
            seed_track_id=library[0]["id"],
            database=db,
        )

        if not result:
            print("❌ Generation failed")
            db.disconnect()
            return False

        m3u_path, trans_path = result

        # Load and display playlist
        with open(trans_path) as f:
            plan = json.load(f)

        # Load M3U
        with open(m3u_path) as f:
            m3u_lines = f.readlines()

        # Extract file paths from M3U
        file_paths = [line.strip() for line in m3u_lines
                     if not line.startswith("#") and line.strip()]

        print(f"\n📋 Generated Playlist ({len(file_paths)} tracks):")
        print("-" * 80)

        track_ids = [t["track_id"] for t in plan["transitions"]]
        library_dict = {t["id"]: t for t in library}

        for i, (track_id, file_path) in enumerate(zip(track_ids, file_paths), 1):
            track = library_dict[track_id]
            print(f"{i}. {track['artist'] or 'Unknown'} - {track['title']}")
            print(f"   Path: {file_path}")
            print(f"   Exists: {Path(file_path).exists()}")
            print(f"   Size: {Path(file_path).stat().st_size if Path(file_path).exists() else 'N/A'} bytes")
            print()

        # Generate Liquidsoap script
        print("\n" + "=" * 80)
        print("🎙️  LIQUIDSOAP SCRIPT GENERATION")
        print("=" * 80)

        # Map file paths into transitions
        for idx, trans in enumerate(plan.get("transitions", [])):
            if idx < len(file_paths):
                trans["file_path"] = file_paths[idx]

        script = _generate_liquidsoap_script(plan, "/tmp/test_mix.mp3", config)

        if not script:
            print("❌ Failed to generate Liquidsoap script")
            db.disconnect()
            return False

        print(f"✅ Generated {len(script.split(chr(10)))} lines of Liquidsoap code\n")

        # Write script to disk for inspection
        script_path = Path("/tmp/debug_render.liq")
        script_path.write_text(script)
        print(f"📄 Script saved to: {script_path}")
        print(f"   You can inspect it with: cat {script_path}\n")

        # Show first 50 lines
        print("First 50 lines of generated script:")
        print("-" * 80)
        lines = script.split('\n')
        for i, line in enumerate(lines[:50], 1):
            print(f"{i:3d}  {line}")
        if len(lines) > 50:
            print(f"     ... ({len(lines) - 50} more lines)")
        print()

        # Try to run Liquidsoap with debugging
        print("=" * 80)
        print("🔧 ATTEMPTING LIQUIDSOAP EXECUTION")
        print("=" * 80)

        output_file = Path("/tmp/debug_mix.mp3")
        if output_file.exists():
            output_file.unlink()

        print(f"\nCommand: liquidsoap {script_path}")
        print(f"Output: {output_file}\n")

        try:
            result = subprocess.run(
                ["liquidsoap", str(script_path)],
                timeout=60,
                capture_output=True,
                text=True,
            )

            print(f"Return code: {result.returncode}\n")

            if result.stdout:
                print("STDOUT:")
                print("-" * 80)
                print(result.stdout)
                print()

            if result.stderr:
                print("STDERR:")
                print("-" * 80)
                print(result.stderr)
                print()

            if result.returncode == 0:
                if output_file.exists():
                    size_mb = output_file.stat().st_size / (1024 * 1024)
                    print(f"✅ SUCCESS! Output file: {output_file}")
                    print(f"   Size: {size_mb:.1f} MiB")
                else:
                    print("⚠️  Return code 0 but output file not created")
            else:
                print(f"❌ Liquidsoap failed with return code {result.returncode}")

        except subprocess.TimeoutExpired:
            print("❌ Liquidsoap timed out after 60 seconds")
        except Exception as e:
            print(f"❌ Error running Liquidsoap: {e}")

        db.disconnect()
        return True

if __name__ == "__main__":
    main()
