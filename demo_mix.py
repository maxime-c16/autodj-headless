#!/usr/bin/env python3
"""Generate and display a demo DJ mix with real database."""

import json
import tempfile
from pathlib import Path
from src.autodj.db import Database
from src.autodj.generate.playlist import generate
import toml

config = toml.load("/app/configs/autodj.toml")
db = Database("/app/data/db/metadata.sqlite")
db.connect()

all_tracks = db.list_tracks()
print(f"📚 Total analyzed tracks: {len(all_tracks)}\n")

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

with tempfile.TemporaryDirectory() as tmpdir:
    result = generate(
        library=library,
        config=config,
        output_dir=tmpdir,
        target_duration_minutes=15,
        seed_track_id=library[0]["id"],
        database=db,
    )

    if result:
        m3u_path, trans_path = result
        with open(trans_path) as f:
            plan = json.load(f)

        playlist_id = plan.get("playlist_id")
        num_tracks = len(plan["transitions"])
        print("🎵 GENERATED PLAYLIST:")
        print(f"   Playlist ID: {playlist_id}")
        print(f"   Tracks: {num_tracks}\n")

        library_dict = {t["id"]: t for t in library}
        track_ids = [t["track_id"] for t in plan["transitions"]]

        total_duration = 0
        print("📋 TRACK SEQUENCE:")
        print("-" * 90)
        for i, track_id in enumerate(track_ids, 1):
            track = library_dict[track_id]
            total_duration += track["duration_seconds"]
            dur_min = int(track["duration_seconds"] // 60)
            dur_sec = int(track["duration_seconds"] % 60)
            duration_str = f"{dur_min}:{dur_sec:02d}"
            artist = (track["artist"] or "Unknown")[:30]
            title = track["title"][:40]
            artist_title = f"{artist} - {title}"
            bpm = track["bpm"]
            key = track["key"]
            print(f"{i:2d}. {artist_title:<75} | {bpm:6.1f} BPM | {key:<5} | {duration_str}")

        print("-" * 90)
        total_min = int(total_duration // 60)
        total_sec = int(total_duration % 60)
        print(f"\n⏱️  TOTAL DURATION: {total_min}:{total_sec:02d}\n")

        print("🔄 TRANSITIONS:")
        print("-" * 90)
        for i in range(len(track_ids) - 1):
            curr = library_dict[track_ids[i]]
            next_t = library_dict[track_ids[i+1]]
            trans = plan["transitions"][i]
            curr_bpm = curr["bpm"]
            next_bpm = next_t["bpm"]
            curr_key = curr["key"]
            next_key = next_t["key"]
            effect = trans.get("effect", "crossfade")
            print(f"  {i+1}→{i+2}: {curr_bpm:6.1f}({curr_key}) → {next_bpm:6.1f}({next_key}) | {effect}")

        print("-" * 90)

db.disconnect()
print("\n✅ Mix generation complete!")
