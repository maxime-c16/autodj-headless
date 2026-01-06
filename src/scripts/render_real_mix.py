#!/usr/bin/env python3
"""
End-to-end rendering test: Generate an actual MP3 mix from real tracks.

This script:
1. Selects 3-5 real tracks from the database
2. Generates a transitions plan
3. Renders to an actual MP3 file using Liquidsoap
4. Validates the output
5. Outputs the file path so you can listen to it

Usage:
    python render_real_mix.py
"""

import sys
import json
import tempfile
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/src")

from src.autodj.db import Database
from src.autodj.generate.playlist import ArchwizardPhonemius, generate
from src.autodj.render.render import RenderEngine
import toml

def main():
    # Load config
    config = toml.load("/app/configs/autodj.toml")

    # Connect to database
    db = Database("/app/data/db/metadata.sqlite")
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

        track_ids = [t["track_id"] for t in plan["transitions"]]
        library_dict = {t["id"]: t for t in library}

        total_duration = 0
        print(f"\n📋 Playlist ({len(track_ids)} tracks):")
        print("-" * 80)
        for i, track_id in enumerate(track_ids, 1):
            track = library_dict[track_id]
            total_duration += track["duration_seconds"]
            dur_min = int(track["duration_seconds"] // 60)
            dur_sec = int(track["duration_seconds"] % 60)
            artist_title = f"{(track['artist'] or 'Unknown')[:30]} - {track['title'][:30]}"
            print(f"{i:2d}. {artist_title:<65} {track['bpm']:6.1f} BPM | {dur_min}:{dur_sec:02d}")

        total_min = int(total_duration // 60)
        total_sec = int(total_duration % 60)
        print(f"\n⏱️  Total Duration: {total_min}:{total_sec:02d}\n")

        # Render the mix
        print("🎙️  RENDERING MIX...")
        print("-" * 80)

        # First, show what we're about to render
        print("\n📋 M3U PLAYLIST FILE:")
        with open(m3u_path) as f:
            m3u_content = f.read()
            print(m3u_content[:500])  # First 500 chars
            if len(m3u_content) > 500:
                print(f"... ({len(m3u_content) - 500} more chars)")

        print("\n📋 TRANSITIONS PLAN (first transition):")
        print(json.dumps(plan["transitions"][0], indent=2))

        print("\n🔧 DEBUGGING INFO:")
        print(f"   Transitions JSON path: {trans_path}")
        print(f"   M3U playlist path: {m3u_path}")
        print(f"   M3U file exists: {Path(m3u_path).exists()}")
        print(f"   M3U file size: {Path(m3u_path).stat().st_size if Path(m3u_path).exists() else 'N/A'} bytes")
        print(f"   Transitions file exists: {Path(trans_path).exists()}")
        print(f"   Transitions file size: {Path(trans_path).stat().st_size if Path(trans_path).exists() else 'N/A'} bytes")

        output_dir = Path("/app/data/mixes")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file = output_dir / "demo_mix_real.mp3"

        engine = RenderEngine(config)
        success = engine.render_playlist(
            str(trans_path),
            str(m3u_path),
            str(output_file),
            timeout_seconds=420,  # 7 minutes max
        )

        if success:
            file_size_mb = output_file.stat().st_size / (1024 * 1024)
            print(f"\n✅ RENDER SUCCESSFUL!")
            print(f"   File: {output_file}")
            print(f"   Size: {file_size_mb:.1f} MiB")
            print(f"\n🎧 You can now listen to: {output_file}")
            print(f"\n📥 To download to your computer:")
            print(f"   scp mcauchy@192.168.1.57:{output_file} ~/Downloads/")
            db.disconnect()
            return True
        else:
            print("❌ Rendering failed - check logs above")
            if output_file.exists():
                output_file.unlink()
            db.disconnect()
            return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
