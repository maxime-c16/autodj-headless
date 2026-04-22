#!/usr/bin/env python3
"""
Quick Mix — render a short test mix from specific tracks.

Usage (inside container):
    # By name (fuzzy search — artist, title, or both):
    python3 /app/scripts/quick_mix.py --seed "Deine Angst" --count 3
    python3 /app/scripts/quick_mix.py --seed "klangkuenstler" --count 5
    python3 /app/scripts/quick_mix.py --tracks "Deine Angst" "Toter Schmetterling" "Blood On My Hands"

    # Full album:
    python3 /app/scripts/quick_mix.py --album "Rusty Chains"
    python3 /app/scripts/quick_mix.py --album "Never Enough"

    # By ID (still works):
    python3 /app/scripts/quick_mix.py --seed ff5a6be4778892c8 --count 3

    # List available tracks:
    python3 /app/scripts/quick_mix.py --list
    python3 /app/scripts/quick_mix.py --search "klangkuenstler"

Environment variables (for Makefile):
    SEED="Deine Angst" TRACK_COUNT=3  make quick-mix
    TRACKS="Deine Angst, Toter Schmetterling, Blood On My Hands"  make quick-mix
    ALBUM="Rusty Chains"  make quick-mix
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
from autodj.render.render import RenderEngine, render as render_mix
from autodj.discord.notifier import DiscordNotifier

# Phase 5 Micro-Techniques
try:
    from autodj.render.render import apply_phase5_micro_techniques, PHASE_5_AVAILABLE
except ImportError:
    PHASE_5_AVAILABLE = False

# DJ Techniques Integration
try:
    from autodj.render.dj_techniques_render import DJTechniquesRenderer, create_listening_guide
    DJ_TECHNIQUES_AVAILABLE = True
except ImportError:
    DJ_TECHNIQUES_AVAILABLE = False


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
    """Find BPM/key-compatible tracks for a seed (excludes seed track and duplicate titles)."""
    c = conn.cursor()
    c.execute("SELECT bpm, key, title FROM tracks WHERE id = ?", (seed_id,))
    row = c.fetchone()
    if not row:
        print(f"ERROR: Seed track {seed_id} not found in database")
        sys.exit(1)

    seed_bpm, seed_key, seed_title = row
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

    # Find compatible tracks, excluding:
    # 1. The seed track itself
    # 2. Tracks with same title (prevents duplicate songs)
    c.execute(f"""
        SELECT DISTINCT id FROM tracks
        WHERE bpm BETWEEN ? AND ?
        AND key IN ({placeholders})
        AND id != ?
        AND LOWER(title) != LOWER(?)
        AND duration_seconds > 120
        ORDER BY ABS(bpm - ?)
        LIMIT ?
    """, [bpm_lo, bpm_hi] + compatible_keys + [seed_id, seed_title, seed_bpm, count - 1])

    compatible_ids = [r[0] for r in c.fetchall()]
    
    # Enforce no duplicates - return unique track IDs
    result = [seed_id] + compatible_ids[:count - 1]
    
    if len(result) < 2:
        raise ValueError(f"Could not find enough unique compatible tracks. Found {len(result)}, need at least 2")
    
    return result


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


def get_album_tracks(album_name, conn):
    """Find all tracks in an album (sorted by track number). Returns list of track IDs."""
    album_lower = album_name.strip().lower()
    
    # First: try exact album name match
    c = conn.cursor()
    c.execute("""
        SELECT id, title FROM tracks
        WHERE LOWER(album) = ?
        ORDER BY title
    """, (album_lower,))
    
    results = c.fetchall()
    
    if not results:
        # Try fuzzy match
        c.execute("""
            SELECT id, title FROM tracks
            WHERE LOWER(album) LIKE ?
            ORDER BY title
        """, (f"%{album_lower}%",))
        results = c.fetchall()
    
    if not results:
        print(f"❌ No album found matching '{album_name}'")
        print(f"\n📀 Available albums:")
        c.execute("SELECT DISTINCT album FROM tracks WHERE album IS NOT NULL ORDER BY album")
        for row in c.fetchall():
            if row['album']:
                print(f"    - {row['album']}")
        sys.exit(1)
    
    track_ids = [r["id"] for r in results]
    print(f"  ✅ Album matched: '{album_name}' ({len(track_ids)} tracks)")
    return track_ids


def main():
    parser = argparse.ArgumentParser(
        description="Quick Mix — test render with human-readable track names",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --seed "Deine Angst" --count 3
  %(prog)s --seed "klangkuenstler" --count 5
  %(prog)s --tracks "Deine Angst" "Toter Schmetterling" "Blood On My Hands"
  %(prog)s --album "Rusty Chains"
  %(prog)s --list
  %(prog)s --search "klangkuenstler"
        """,
    )
    parser.add_argument("--tracks", nargs="+", help="Track names or IDs to mix (in order)")
    parser.add_argument("--seed", help="Seed track name or ID (auto-find compatible)")
    parser.add_argument("--count", type=int, default=3, help="Number of tracks (with --seed)")
    parser.add_argument("--album", help="Album name to use all tracks from album (in order)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--list", action="store_true", help="List all tracks in library")
    parser.add_argument("--search", help="Search tracks by name/artist")
    args = parser.parse_args()

    # Environment variable fallback
    if not args.tracks and not args.seed and not args.album and not args.list and not args.search:
        env_tracks = os.environ.get("TRACKS", "").strip()
        env_seed = os.environ.get("SEED", "").strip()
        env_album = os.environ.get("ALBUM", "").strip()
        if not env_seed:
            env_seed = os.environ.get("SEED_TRACK_ID", "").strip()
        if env_tracks:
            # Support comma-separated or space-separated
            if "," in env_tracks:
                args.tracks = [t.strip() for t in env_tracks.split(",") if t.strip()]
            else:
                args.tracks = [env_tracks]
        elif env_album:
            args.album = env_album
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

    if not args.tracks and not args.seed and not args.album:
        print("Usage: quick_mix.py --seed 'track name' --count N")
        print("       quick_mix.py --tracks 'name1' 'name2' 'name3'")
        print("       quick_mix.py --album 'Album Name'")
        print("       quick_mix.py --list")
        print("       quick_mix.py --search 'keyword'")
        sys.exit(1)

    # Resolve track names to IDs
    print("Resolving tracks...")
    if args.album:
        track_ids = get_album_tracks(args.album, conn)
    elif args.tracks:
        track_ids = []
        for name in args.tracks:
            tid = search_track(name, conn)
            track_ids.append(tid)
    else:
        seed_id = search_track(args.seed, conn)
        track_ids = find_compatible_tracks(seed_id, args.count, conn)

    # ENFORCE: No duplicate track IDs (deduplicate while preserving order)
    seen = set()
    dedup_track_ids = []
    for tid in track_ids:
        if tid not in seen:
            dedup_track_ids.append(tid)
            seen.add(tid)
        else:
            print(f"  ⚠️  Removing duplicate track: {tid}")
    
    track_ids = dedup_track_ids
    
    if len(track_ids) < 2:
        print(f"ERROR: Need at least 2 unique tracks, found {len(track_ids)}")
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
    
    # ========================================================================
    # PHASE 1: Add Spectral Analysis (only new tracks)
    # ========================================================================
    print(f"\n🔍 Enhancing transitions with spectral analysis...")
    try:
        from autodj.render.spectral_cache_manager import enhance_transitions_with_spectral_data
        transitions = enhance_transitions_with_spectral_data(transitions)
        print(f"  ✅ Spectral data added to transitions (Phase 1 ready!)")
    except Exception as e:
        print(f"  ⚠️  Spectral enhancement failed: {e}")
        print(f"     Phase 1 will be skipped (using fallback)")
    
    # Post playlist notification to Discord
    notifier = DiscordNotifier(config_dict=config.data)
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

    # Check EQ_ENABLED environment variable
    eq_enabled = os.environ.get('EQ_ENABLED', 'true').lower() == 'true'
    persona = os.environ.get('PERSONA', 'tech_house').lower()

    print(f"\nRendering to {args.output}...")
    print(f"  EQ: {'ON' if eq_enabled else 'OFF'} | Phase 5: {'ON' if PHASE_5_AVAILABLE else 'OFF'} | Persona: {persona}")
    start = time.time()

    # Route through render() — NOT render_playlist() — so Phase 0/1/2/5 all activate:
    #   Phase 0: BPM precision validators
    #   Phase 1: 16-bar early transitions
    #   Phase 2: EQ pre-processing (ffmpeg, per eq_annotation)
    #   Phase 5: Micro-technique injection (stutter, bass cut, filter sweep...)
    success = render_mix(
        transitions_json_path=transitions_path,
        output_path=args.output,
        config=config.data,
        timeout_seconds=None,   # No cap — offline render runs as fast as Liquidsoap allows
        eq_enabled=eq_enabled,
        phase5_enabled=PHASE_5_AVAILABLE,
        persona=persona,
    )
    elapsed = time.time() - start

    if success and os.path.exists(args.output):
        size_mb = os.path.getsize(args.output) / (1024 * 1024)
        print(f"\nSUCCESS!")
        print(f"  Output: {args.output}")
        print(f"  Size:   {size_mb:.1f} MB")
        print(f"  Time:   {elapsed:.0f}s")
        
        # Print which phases were active during this render
        print(f"\n🎛️ RENDER PHASES ACTIVE:")
        print(f"  Phase 0 (BPM Precision):  ✅ Confidence + multipass + grid validators")
        print(f"  Phase 1 (Early Starts):   ✅ 16-bar pre-blend on eligible transitions")
        print(f"  Phase 2 (DJ EQ):          {'✅ Beat-synced EQ annotation + preprocessing' if eq_enabled else '⏭️  Disabled (EQ_ENABLED=false)'}")
        print(f"  Phase 5 (Micro-Tech):     {'✅ Stutter, bass-cut, filter-sweep, echo...' if PHASE_5_AVAILABLE else '⚠️  Unavailable (import failed)'}")
        print(f"\n🎧 LISTENING GUIDE:")
        print(f"  ✅ Early blends: incoming track fades in ~30s before outgoing ends")
        print(f"  ✅ Bass control: low-end swaps during all crossfades")
        print(f"  ✅ Micro-effects: listen for stutter rolls, filter sweeps between tracks")
        
        # Post completion notification to Discord
        output_filename = os.path.basename(args.output)
        output_dir = os.path.dirname(args.output)
        notifier.post_complete({
            'File': output_filename,
            'Size': f'{size_mb:.1f} MB',
            'Location': output_dir,
            'Duration': f'{elapsed:.0f}s',
            'Status': '✅ Ready for broadcast'
        })
    else:
        print(f"\nFAILED after {elapsed:.0f}s")
        sys.exit(1)


if __name__ == "__main__":
    main()
