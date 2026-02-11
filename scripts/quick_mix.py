#!/usr/bin/env python3
"""
Quick Mix — render a short test mix from specific tracks.

Usage (inside container):
    # By name (fuzzy search — artist, title, or both):
    python3 /app/scripts/quick_mix.py --seed "Deine Angst" --count 3
    python3 /app/scripts/quick_mix.py --seed "klangkuenstler" --count 5
    python3 /app/scripts/quick_mix.py --tracks "Deine Angst" "Toter Schmetterling" "Blood On My Hands"

    # By ID (still works):
    python3 /app/scripts/quick_mix.py --seed ff5a6be4778892c8 --count 3

    # List available tracks:
    python3 /app/scripts/quick_mix.py --list
    python3 /app/scripts/quick_mix.py --search "klangkuenstler"

Environment variables (for Makefile):
    SEED="Deine Angst" TRACK_COUNT=3  make quick-mix
    TRACKS="Deine Angst, Toter Schmetterling, Blood On My Hands"  make quick-mix
"""
import argparse
import json
import os
import sqlite3
import sys
import time

sys.path.insert(0, "/app/src")

from autodj.config import Config
from autodj.db import Database
from autodj.generate.playlist import generate
from autodj.render.render import RenderEngine
from autodj.discord.notifier import DiscordNotifier


DB_PATH = "/app/data/db/metadata.sqlite"


def search_track(query, conn):
    """Find a track by fuzzy name search (title, artist, or both). Returns track ID."""
    query_lower = query.strip().lower()

    # First: try exact ID match (hex hash)
    if len(query_lower) >= 8 and all(c in "0123456789abcdef" for c in query_lower):
        row = conn.execute("SELECT id, title, artist FROM tracks WHERE id = ?", (query_lower,)).fetchone()
        if row:
            return row["id"]

    # Second: search title and artist with LIKE
    c = conn.cursor()
    c.execute("""
        SELECT id, title, artist, bpm, key, duration_seconds
        FROM tracks
        WHERE LOWER(title) LIKE ? OR LOWER(artist) LIKE ?
        ORDER BY
            CASE
                WHEN LOWER(title) LIKE ? THEN 0
                WHEN LOWER(artist) LIKE ? THEN 1
                ELSE 2
            END,
            duration_seconds DESC
        LIMIT 5
    """, (f"%{query_lower}%", f"%{query_lower}%",
          f"%{query_lower}%", f"%{query_lower}%"))

    results = c.fetchall()
    if not results:
        # Try matching words individually
        words = query_lower.split()
        if len(words) > 1:
            conditions = []
            params = []
            for word in words:
                conditions.append("(LOWER(title) LIKE ? OR LOWER(artist) LIKE ?)")
                params.extend([f"%{word}%", f"%{word}%"])
            sql = f"SELECT id, title, artist, bpm, key, duration_seconds FROM tracks WHERE {' AND '.join(conditions)} LIMIT 5"
            c.execute(sql, params)
            results = c.fetchall()

    if not results:
        print(f"  No tracks found matching '{query}'")
        print(f"  Try: --search <keyword> to browse available tracks")
        sys.exit(1)

    if len(results) == 1:
        r = results[0]
        artist = r["artist"] or "Unknown"
        print(f"  Matched: {artist} — {r['title']} ({r['bpm']:.1f} BPM, {r['key']})")
        return r["id"]

    # Multiple matches — pick best, show alternatives
    best = results[0]
    artist = best["artist"] or "Unknown"
    print(f"  Matched: {artist} — {best['title']} ({best['bpm']:.1f} BPM, {best['key']})")
    if len(results) > 1:
        print(f"  (also found: {', '.join(r['title'] for r in results[1:])})")
    return best["id"]


def find_compatible_tracks(seed_id, count, conn):
    """Find BPM/key-compatible tracks for a seed."""
    c = conn.cursor()
    c.execute("SELECT bpm, key FROM tracks WHERE id = ?", (seed_id,))
    row = c.fetchone()
    if not row:
        print(f"ERROR: Seed track {seed_id} not found in database")
        sys.exit(1)

    seed_bpm, seed_key = row
    if not seed_bpm:
        print(f"ERROR: Seed track has no BPM data")
        sys.exit(1)

    # Camelot compatible keys
    key_num = seed_key[:-1] if seed_key else ""
    key_mode = seed_key[-1:] if seed_key else ""
    compatible_keys = [seed_key]
    if key_num.isdigit():
        n = int(key_num)
        prev_n = 12 if n == 1 else n - 1
        next_n = 1 if n == 12 else n + 1
        opposite = "B" if key_mode == "A" else "A"
        compatible_keys += [
            f"{prev_n}{key_mode}", f"{next_n}{key_mode}",
            f"{n}{opposite}"
        ]

    bpm_lo = seed_bpm * 0.85
    bpm_hi = seed_bpm * 1.15
    placeholders = ",".join("?" * len(compatible_keys))

    c.execute(f"""
        SELECT id FROM tracks
        WHERE bpm BETWEEN ? AND ?
        AND key IN ({placeholders})
        AND id != ?
        AND duration_seconds > 120
        ORDER BY ABS(bpm - ?)
        LIMIT ?
    """, [bpm_lo, bpm_hi] + compatible_keys + [seed_id, seed_bpm, count - 1])

    return [seed_id] + [r[0] for r in c.fetchall()]


def list_tracks(conn, search=None):
    """List tracks in the library."""
    c = conn.cursor()
    if search:
        search_lower = f"%{search.lower()}%"
        c.execute("""
            SELECT id, title, artist, bpm, key, duration_seconds
            FROM tracks
            WHERE LOWER(title) LIKE ? OR LOWER(artist) LIKE ?
            ORDER BY artist, title
        """, (search_lower, search_lower))
    else:
        c.execute("""
            SELECT id, title, artist, bpm, key, duration_seconds
            FROM tracks ORDER BY artist, title
        """)

    rows = c.fetchall()
    if not rows:
        print("No tracks found.")
        return

    print(f"\n{'Artist':<25} {'Title':<35} {'BPM':>6} {'Key':>4} {'Dur':>5}")
    print("-" * 80)
    for r in rows:
        artist = (r["artist"] or "?")[:24]
        title = (r["title"] or "?")[:34]
        bpm = f"{r['bpm']:.1f}" if r["bpm"] else "?"
        key = r["key"] or "?"
        dur = f"{r['duration_seconds'] / 60:.1f}m" if r["duration_seconds"] else "?"
        print(f"{artist:<25} {title:<35} {bpm:>6} {key:>4} {dur:>5}")
    print(f"\n{len(rows)} tracks total")


def main():
    parser = argparse.ArgumentParser(
        description="Quick Mix — test render with human-readable track names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --seed "Deine Angst" --count 3
  %(prog)s --seed "klangkuenstler" --count 5
  %(prog)s --tracks "Deine Angst" "Toter Schmetterling" "Blood On My Hands"
  %(prog)s --list
  %(prog)s --search "klangkuenstler"
        """,
    )
    parser.add_argument("--tracks", nargs="+", help="Track names or IDs to mix (in order)")
    parser.add_argument("--seed", help="Seed track name or ID (auto-find compatible)")
    parser.add_argument("--count", type=int, default=3, help="Number of tracks (with --seed)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--list", action="store_true", help="List all tracks in library")
    parser.add_argument("--search", help="Search tracks by name/artist")
    args = parser.parse_args()

    # Environment variable fallback
    if not args.tracks and not args.seed and not args.list and not args.search:
        env_tracks = os.environ.get("TRACKS", "").strip()
        env_seed = os.environ.get("SEED", "").strip()
        if not env_seed:
            env_seed = os.environ.get("SEED_TRACK_ID", "").strip()
        if env_tracks:
            # Support comma-separated or space-separated
            if "," in env_tracks:
                args.tracks = [t.strip() for t in env_tracks.split(",") if t.strip()]
            else:
                args.tracks = [env_tracks]
        elif env_seed:
            args.seed = env_seed
            args.count = int(os.environ.get("TRACK_COUNT", "3"))

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Handle list/search modes
    if args.list:
        list_tracks(conn)
        return
    if args.search:
        list_tracks(conn, args.search)
        return

    if not args.tracks and not args.seed:
        print("Usage: quick_mix.py --seed 'track name' --count N")
        print("       quick_mix.py --tracks 'name1' 'name2' 'name3'")
        print("       quick_mix.py --list")
        print("       quick_mix.py --search 'keyword'")
        sys.exit(1)

    # Resolve track names to IDs
    print("Resolving tracks...")
    if args.tracks:
        track_ids = []
        for name in args.tracks:
            tid = search_track(name, conn)
            track_ids.append(tid)
    else:
        seed_id = search_track(args.seed, conn)
        track_ids = find_compatible_tracks(seed_id, args.count, conn)

    if len(track_ids) < 2:
        print(f"ERROR: Need at least 2 tracks, found {len(track_ids)}")
        sys.exit(1)

    # Load library data
    library = []
    print(f"\nQuick Mix: {len(track_ids)} tracks")
    print("=" * 60)
    for idx, tid in enumerate(track_ids):
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (tid,)).fetchone()
        if not row:
            print(f"  ERROR: Track {tid} not found!")
            sys.exit(1)
        library.append(dict(row))
        artist = row["artist"] or "Unknown"
        print(f"  {idx + 1}. {artist} — {row['title']}")
        print(f"     {row['bpm']:.1f} BPM | {row['key']} | {row['duration_seconds'] / 60:.1f} min")
    conn.close()

    # Generate (with database for section-aware transitions)
    config = Config.load()
    db = Database(DB_PATH)
    db.connect()
    print(f"\nGenerating transitions...")
    result = generate(
        track_ids=track_ids,
        library=library,
        config=config.data,
        output_dir="/app/data/playlists",
        database=db,
    )
    if not result:
        print("ERROR: generate() failed")
        sys.exit(1)

    playlist_path, transitions_path = result

    with open(transitions_path) as f:
        plan = json.load(f)
    transitions = plan.get("transitions", [])
    
    # Post playlist notification to Discord
    notifier = DiscordNotifier()
    notifier.post_playlist({
        'transitions': transitions,
        'mix_duration_seconds': plan.get('mix_duration_seconds', 0)
    }, db_path=DB_PATH)
    
    print(f"\nTransition Plan:")
    print("=" * 70)
    for i, t in enumerate(transitions):
        xfade = t.get("mix_out_seconds", 0)
        title = t.get("title", "?")
        bpm = t.get("bpm", 0)
        target = t.get("target_bpm", 0)
        tt = t.get("transition_type", "bass_swap")
        overlap = t.get("overlap_bars", 8)
        next_id = t.get("next_track_id")
        print(f"  {i+1}. {title}")
        print(f"     {bpm:.1f} -> {target:.1f} BPM | xfade {xfade:.1f}s")
        if next_id:
            tt_display = {
                "bass_swap": "BASS SWAP (HPF out + LPF in)",
                "loop_hold": "LOOP HOLD (hold groove, blend in)",
                "drop_swap": "DROP SWAP (slam at drop!)",
                "loop_roll": "LOOP ROLL (8->4->2->1 tighten)",
                "eq_blend": "EQ BLEND (long smooth 32-bar)",
            }.get(tt, tt)
            print(f"     --> [{tt_display}] ({overlap} bars)")
    print("=" * 70)

    # Display transition type distribution
    transition_counts = {}
    transition_icons = {
        "bass_swap": "🔉",
        "loop_hold": "🔁",
        "drop_swap": "💥",
        "loop_roll": "⚙️",
        "eq_blend": "🎚️",
    }
    for t in transitions:
        tt = t.get("transition_type", "bass_swap")
        transition_counts[tt] = transition_counts.get(tt, 0) + 1

    if transition_counts:
        print(f"\nTransition Type Distribution:")
        total_transitions = sum(transition_counts.values())
        for tt in ["bass_swap", "loop_hold", "drop_swap", "loop_roll", "eq_blend"]:
            count = transition_counts.get(tt, 0)
            pct = (count / total_transitions * 100) if total_transitions > 0 else 0
            icon = transition_icons.get(tt, "")
            if count > 0:
                print(f"  {icon} {tt.upper():15} {count:2}x ({pct:3.0f}%)")

    # Render
    if not args.output:
        ts = time.strftime("%Y%m%d-%H%M%S")
        args.output = f"/app/data/mixes/quick-mix-{ts}.mp3"

    print(f"\nRendering to {args.output}...")
    start = time.time()
    engine = RenderEngine(config=config.data)
    success = engine.render_playlist(
        transitions_json_path=transitions_path,
        playlist_m3u_path=playlist_path,
        output_path=args.output,
        timeout_seconds=600,
    )
    elapsed = time.time() - start

    if success and os.path.exists(args.output):
        size_mb = os.path.getsize(args.output) / (1024 * 1024)
        print(f"\nSUCCESS!")
        print(f"  Output: {args.output}")
        print(f"  Size:   {size_mb:.1f} MB")
        print(f"  Time:   {elapsed:.0f}s")
        
        # Post completion notification to Discord
        notifier.post_complete({
            'File': os.path.basename(args.output),
            'Size': f'{size_mb:.1f} MB',
            'Duration': f'{elapsed:.0f}s'
        })
    else:
        print(f"\nFAILED after {elapsed:.0f}s")
        sys.exit(1)


if __name__ == "__main__":
    main()
