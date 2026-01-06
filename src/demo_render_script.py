#!/usr/bin/env python3
"""Generate demo mix and show the Liquidsoap render script."""

import json
import tempfile
from pathlib import Path
from src.autodj.db import Database
from src.autodj.generate.playlist import generate
from src.autodj.render.render import _generate_liquidsoap_script

# Load config from file manually
config_path = Path("/app/configs/autodj.toml") if Path("/app/configs/autodj.toml").exists() else Path("configs/autodj.toml")
try:
    import toml
    config = toml.load(str(config_path))
except ImportError:
    # Minimal config without toml
    config = {
        "constraints": {
            "bpm_tolerance_percent": 4.0,
            "energy_window_size": 3,
            "min_track_duration_seconds": 120,
            "max_repeat_decay_hours": 168,
        },
        "render": {
            "output_format": "mp3",
            "mp3_bitrate": 192,
            "crossfade_duration_seconds": 4.0,
        }
    }

db = Database("/app/data/db/metadata.sqlite")
db.connect()

all_tracks = db.list_tracks()
print(f"\n{'='*90}")
print(f"AutoDJ-Headless Demo: Generating Real DJ Mix")
print(f"{'='*90}\n")
print(f"📚 Total analyzed tracks in database: {len(all_tracks)}\n")

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

print(f"✅ Loaded {len(library)} tracks for selection\n")

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

        library_dict = {t["id"]: t for t in library}
        track_ids = [t["track_id"] for t in plan["transitions"]]

        print(f"{'─'*90}")
        print(f"🎵 GENERATED PLAYLIST")
        print(f"{'─'*90}")
        print(f"Playlist ID: {plan.get('playlist_id')}")
        print(f"Target Duration: 15 minutes\n")

        total_duration = 0
        print(f"{'#':<3} {'Artist - Title':<60} {'BPM':<8} {'Key':<6} {'Length':<8}")
        print(f"{'-'*90}")
        for i, track_id in enumerate(track_ids, 1):
            track = library_dict[track_id]
            total_duration += track["duration_seconds"]
            dur_min = int(track["duration_seconds"] // 60)
            dur_sec = int(track["duration_seconds"] % 60)
            duration_str = f"{dur_min}:{dur_sec:02d}"
            artist = (track["artist"] or "Unknown")[:28]
            title = track["title"][:30]
            artist_title = f"{artist} - {title}"
            print(f"{i:<3} {artist_title:<60} {track['bpm']:6.1f}  {track['key']:<6} {duration_str:<8}")

        print(f"{'-'*90}")
        total_min = int(total_duration // 60)
        total_sec = int(total_duration % 60)
        print(f"\n⏱️  ACTUAL DURATION: {total_min}:{total_sec:02d} (target: 15:00)")
        print(f"   Difference: {(total_duration - 900)//60:+d} minutes\n")

        print(f"{'─'*90}")
        print(f"🔄 TRANSITION PLAN (Harmonic Mixing)")
        print(f"{'─'*90}\n")
        for i in range(len(track_ids) - 1):
            curr = library_dict[track_ids[i]]
            next_t = library_dict[track_ids[i+1]]
            trans = plan["transitions"][i]

            curr_title = f"{curr['artist'] or 'Unknown'} - {curr['title']}"[:50]
            next_title = f"{next_t['artist'] or 'Unknown'} - {next_t['title']}"[:50]

            print(f"Transition {i+1}:")
            print(f"  From: {curr_title}")
            print(f"         {curr['bpm']:6.1f} BPM | Key {curr['key']}")
            print(f"  To:   {next_title}")
            print(f"         {next_t['bpm']:6.1f} BPM | Key {next_t['key']}")
            print(f"  Effect: {trans.get('effect', 'crossfade')} ({trans.get('mix_out_seconds', 4.0):.1f}s)")

            # Analyze compatibility
            bpm_diff = abs(next_t['bpm'] - curr['bpm'])
            bpm_tolerance = curr['bpm'] * 0.04
            is_bpm_ok = bpm_diff <= bpm_tolerance

            print(f"  ✓ BPM change: {bpm_diff:+.1f} BPM ({'+' if bpm_diff > 0 else ''}{bpm_diff/curr['bpm']*100:.1f}%) - {'✅ OK' if is_bpm_ok else '❌ VIOLATION'}")
            print()

        # Generate and show Liquidsoap script
        transitions_dicts = []
        for idx, trans in enumerate(plan["transitions"]):
            trans_dict = trans if isinstance(trans, dict) else trans.to_dict() if hasattr(trans, 'to_dict') else trans
            if idx < len(track_ids):
                trans_dict["file_path"] = library_dict[track_ids[idx]]["file_path"]
            transitions_dicts.append(trans_dict)

        plan_dict = {
            "playlist_id": plan.get("playlist_id"),
            "transitions": transitions_dicts,
            "mix_duration_seconds": total_duration,
        }

        script = _generate_liquidsoap_script(plan_dict, "/tmp/demo_mix.mp3", config)

        print(f"{'─'*90}")
        print(f"🎙️  LIQUIDSOAP OFFLINE RENDERING SCRIPT")
        print(f"{'─'*90}\n")
        print("This script would be executed by Liquidsoap to render the final mix:\n")
        script_lines = script.split('\n')
        for i, line in enumerate(script_lines[:40], 1):
            print(f"{i:3d}  {line}")
        if len(script_lines) > 40:
            print(f"     ... ({len(script_lines) - 40} more lines)")
        print(f"\n     Total: {len(script_lines)} lines of Liquidsoap code")
        print(f"     Output: MP3 (192 kbps stereo)")
        print(f"     Crossfade: 4.0 seconds")

        print(f"\n{'─'*90}")
        print(f"✅ Demo complete!")
        print(f"{'─'*90}\n")

db.disconnect()
