#!/usr/bin/env python3
"""
Demo: Structure Analysis Pipeline — Showcase All New Features
=============================================================
Runs full structure analysis on 3 tracks, displays rich metadata,
then generates a section-aware 3-track mix.

Features demonstrated:
  1. Self-similarity section detection (Foote 2000)
  2. Section classification (intro/drop/breakdown/buildup/outro)
  3. Semantic cue point generation (mix_in, drop_1, breakdown_1, mix_out, last_32)
  4. Loop region detection with stability scoring
  5. Kick pattern analysis (four_on_floor / minimal / none)
  6. Vocal detection
  7. Database persistence (track_analysis table, schema v2)
  8. Section-aware transition planning (outro_start, drop_position)
  9. Section-aware Liquidsoap render (cue_out override)
"""

import sys
import os
import json
import time
import subprocess
from dataclasses import asdict

import numpy as np

sys.path.insert(0, '/app/src')

from autodj.db import Database
from autodj.analyze.structure import analyze_track_structure

# Target sample rate for analysis (22050 is standard for MIR, saves memory)
ANALYSIS_SR = 22050


def load_audio_ffmpeg(file_path, sr=ANALYSIS_SR):
    """Load audio via ffmpeg — works with any format (m4a, mp3, flac, wav)."""
    result = subprocess.run(
        ['ffmpeg', '-i', file_path, '-f', 'f32le', '-acodec', 'pcm_f32le',
         '-ar', str(sr), '-ac', '1', '-v', 'quiet', '-'],
        capture_output=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f'ffmpeg failed: {result.stderr.decode()[:200]}')
    audio = np.frombuffer(result.stdout, dtype=np.float32)
    if len(audio) == 0:
        raise RuntimeError('ffmpeg produced no output')
    return audio, sr

# ─── Configuration ──────────────────────────────────────────────────────────

TRACK_IDS = [
    'ff5a6be4778892c8',  # Deine Angst — Klangkuenstler (8A, 152.1 BPM)
    '72b6b2cdf85c1382',  # Blood On My Hands — 6EJOU & BSLS (7A, 152.3 BPM)
    'ce10a83892f99340',  # Last Kiss Before Death — I Hate Models (7A, 150.6 BPM)
]

SEPARATOR = '=' * 78
SUBSEP = '-' * 78


def format_time(seconds):
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f'{m}:{s:02d}'


def print_header(text):
    print(f'\n{SEPARATOR}')
    print(f'  {text}')
    print(SEPARATOR)


def print_section_table(sections):
    """Print sections as a formatted table."""
    print(f'  {"#":<3} {"Label":<12} {"Start":>7} {"End":>7} {"Bars":>6} {"Energy":>7} {"Kick":>6} {"Conf":>6}')
    print(f'  {"-"*3} {"-"*12} {"-"*7} {"-"*7} {"-"*6} {"-"*7} {"-"*6} {"-"*6}')
    for i, s in enumerate(sections):
        kick = "YES" if s.has_kick else "no"
        print(f'  {i+1:<3} {s.label:<12} {format_time(s.start_seconds):>7} {format_time(s.end_seconds):>7} '
              f'{s.start_bar:>3}-{s.end_bar:<3}{s.energy:>6.2f}  {kick:>5}  {s.confidence:>5.2f}')


def print_cue_table(cues):
    """Print semantic cues as a formatted table."""
    print(f'  {"Label":<16} {"Position":>9} {"Bar":>5} {"Type":<12}')
    print(f'  {"-"*16} {"-"*9} {"-"*5} {"-"*12}')
    for c in cues:
        print(f'  {c.label:<16} {format_time(c.position_seconds):>9} {c.position_bar:>5} {c.type:<12}')


def print_loop_table(loops):
    """Print loop regions as a formatted table."""
    if not loops:
        print('  (no loops detected)')
        return
    print(f'  {"Label":<18} {"Start":>7} {"End":>7} {"Bars":>5} {"Energy":>7} {"Stability":>10}')
    print(f'  {"-"*18} {"-"*7} {"-"*7} {"-"*5} {"-"*7} {"-"*10}')
    for l in loops:
        print(f'  {l.label:<18} {format_time(l.start_seconds):>7} {format_time(l.end_seconds):>7} '
              f'{l.length_bars:>5} {l.energy:>7.2f} {l.stability:>10.3f}')


def analyze_and_display(track_info, db):
    """Run full structure analysis on a track and display results."""
    track_id = track_info['id']
    title = track_info['title'] or 'Unknown'
    artist = track_info['artist'] or 'Unknown Artist'
    bpm = track_info['bpm']
    key = track_info['key']
    file_path = track_info['file_path']
    duration = track_info['duration_seconds']

    print_header(f'{title}  —  {artist}')
    print(f'  File: {os.path.basename(file_path)}')
    print(f'  BPM: {bpm:.1f}  |  Key: {key}  |  Duration: {format_time(duration)}')
    print()

    # Load audio via ffmpeg (handles m4a/mp3/flac/wav)
    print(f'  Loading audio via ffmpeg...')
    t0 = time.time()
    try:
        audio, sr = load_audio_ffmpeg(file_path)
    except Exception as e:
        print(f'  ERROR loading audio: {e}')
        return None
    load_time = time.time() - t0
    print(f'  Loaded: {len(audio)/sr:.1f}s @ {sr}Hz ({len(audio)*4/1024/1024:.1f} MiB) in {load_time:.1f}s')

    # Run structure analysis
    print(f'  Analyzing structure...')
    t0 = time.time()
    structure = analyze_track_structure(audio, sr, bpm)
    analysis_time = time.time() - t0
    print(f'  Analysis complete in {analysis_time:.1f}s')

    # ─── Feature 1: Section Detection ──────────────────────────────────
    print(f'\n  SECTIONS ({len(structure.sections)} detected)')
    print(SUBSEP)
    print_section_table(structure.sections)

    # ─── Feature 2: Kick Pattern ───────────────────────────────────────
    print(f'\n  KICK PATTERN: {structure.kick_pattern}')
    print(f'  VOCAL CONTENT: {"Yes" if structure.has_vocal else "No"}')
    print(f'  TOTAL BARS: {structure.total_bars}')
    print(f'  DOWNBEAT: {format_time(structure.downbeat_position)} ({structure.downbeat_position:.3f}s)')
    print(f'  BARS PER PHRASE: {structure.bars_per_phrase}')

    # ─── Feature 3: Semantic Cue Points ────────────────────────────────
    print(f'\n  SEMANTIC CUE POINTS ({len(structure.cue_points)} generated)')
    print(SUBSEP)
    print_cue_table(structure.cue_points)

    # ─── Feature 4: Loop Regions ───────────────────────────────────────
    print(f'\n  LOOP REGIONS ({len(structure.loop_regions)} detected)')
    print(SUBSEP)
    print_loop_table(structure.loop_regions)

    # ─── Feature 5: Database Persistence ───────────────────────────────
    analysis_dict = {
        'sections': [asdict(s) for s in structure.sections],
        'cue_points': [asdict(c) for c in structure.cue_points],
        'loop_regions': [asdict(l) for l in structure.loop_regions],
        'kick_pattern': structure.kick_pattern,
        'downbeat_seconds': structure.downbeat_position,
        'total_bars': structure.total_bars,
        'has_vocal': structure.has_vocal,
    }
    db.save_track_analysis(track_id, analysis_dict)
    print(f'\n  Saved to database (track_analysis table)')

    return structure


def demo_transition_planning(tracks_data, structures, db):
    """Demonstrate section-aware transition planning."""
    print_header('SECTION-AWARE TRANSITION PLAN')

    for i in range(len(tracks_data) - 1):
        outgoing = tracks_data[i]
        incoming = tracks_data[i + 1]
        out_structure = structures[i]
        in_structure = structures[i + 1]

        out_title = outgoing['title'] or 'Unknown'
        in_title = incoming['title'] or 'Unknown'

        print(f'\n  TRANSITION {i+1}: {out_title}  -->  {in_title}')
        print(SUBSEP)

        # Find mix_out cue on outgoing track
        mix_out = next((c for c in out_structure.cue_points if c.label == 'mix_out'), None)
        outro_start = None
        if mix_out:
            outro_start = mix_out.position_seconds
            print(f'  Outgoing mix_out point: {format_time(outro_start)} (bar {mix_out.position_bar})')
        else:
            print(f'  Outgoing mix_out: not found (using cue_out_frames fallback)')

        # Find the outro section
        outro_section = next((s for s in out_structure.sections if s.label == 'outro'), None)
        if outro_section:
            print(f'  Outro section: {format_time(outro_section.start_seconds)} - {format_time(outro_section.end_seconds)} '
                  f'(energy={outro_section.energy:.2f}, kick={"YES" if outro_section.has_kick else "no"})')

        # Find mix_in cue on incoming track
        mix_in = next((c for c in in_structure.cue_points if c.label == 'mix_in'), None)
        if mix_in:
            print(f'  Incoming mix_in point: {format_time(mix_in.position_seconds)} (bar {mix_in.position_bar})')

        # Find drop_1 on incoming track
        drop_1 = next((c for c in in_structure.cue_points if c.label == 'drop_1'), None)
        if drop_1:
            print(f'  Incoming drop_1 point: {format_time(drop_1.position_seconds)} (bar {drop_1.position_bar})')

        # Compute bar-aligned crossfade duration
        avg_bpm = (outgoing['bpm'] + incoming['bpm']) / 2
        bars = 8
        crossfade_seconds = bars * 4 * 60 / avg_bpm
        print(f'  Crossfade: {bars} bars = {crossfade_seconds:.1f}s @ {avg_bpm:.1f} BPM avg')

        # BPM stretch
        target_bpm = avg_bpm
        out_stretch = target_bpm / outgoing['bpm']
        in_stretch = target_bpm / incoming['bpm']
        print(f'  BPM matching: target={target_bpm:.1f} '
              f'(out stretch={out_stretch:.4f}, in stretch={in_stretch:.4f})')

        # Harmonic compatibility
        print(f'  Harmonic: {outgoing["key"]} -> {incoming["key"]}')

        # What render.py will do
        if outro_start:
            print(f'\n  RENDER ACTION: liq_cue_out overridden to {outro_start:.3f}s '
                  f'(was {outgoing["cue_out_frames"]/44100:.1f}s from cue_out_frames)')
        if drop_1:
            print(f'  RENDER ACTION: drop_position available at {drop_1.position_seconds:.3f}s '
                  f'for FX timing')


def demo_liquidsoap_output(tracks_data, structures):
    """Show what the Liquidsoap script would look like with section-aware timing."""
    print_header('LIQUIDSOAP SCRIPT PREVIEW (section-aware)')

    # Build transition list like render.py does
    transitions = []
    for i, track in enumerate(tracks_data):
        structure = structures[i]
        t = {
            'track_index': i,
            'title': track['title'],
            'artist': track['artist'],
            'file_path': track['file_path'],
            'bpm': track['bpm'],
            'cue_in_frames': track['cue_in_frames'] or 0,
            'cue_out_frames': track['cue_out_frames'] or int(track['duration_seconds'] * 44100),
        }

        # Add section-aware fields
        mix_out = next((c for c in structure.cue_points if c.label == 'mix_out'), None)
        drop_1 = next((c for c in structure.cue_points if c.label == 'drop_1'), None)

        if mix_out:
            t['outro_start_seconds'] = mix_out.position_seconds
        if drop_1:
            t['drop_position_seconds'] = drop_1.position_seconds

        transitions.append(t)

    # Show what render.py generates
    for i, trans in enumerate(transitions):
        cue_in = trans['cue_in_frames'] / 44100
        cue_out = trans['cue_out_frames'] / 44100

        # Section-aware override
        outro_start = trans.get('outro_start_seconds')
        if outro_start and outro_start > 0:
            old_cue_out = cue_out
            cue_out = outro_start
            print(f'  Track {i+1}: {trans["title"]}')
            print(f'    cue_in:  {format_time(cue_in)} ({cue_in:.3f}s)')
            print(f'    cue_out: {format_time(cue_out)} ({cue_out:.3f}s)  <-- OVERRIDDEN from {format_time(old_cue_out)}')
        else:
            print(f'  Track {i+1}: {trans["title"]}')
            print(f'    cue_in:  {format_time(cue_in)} ({cue_in:.3f}s)')
            print(f'    cue_out: {format_time(cue_out)} ({cue_out:.3f}s)')

        if trans.get('drop_position_seconds'):
            print(f'    drop_1:  {format_time(trans["drop_position_seconds"])} ({trans["drop_position_seconds"]:.3f}s)')
        print()


def main():
    print(SEPARATOR)
    print('  AUTODJ STRUCTURE ANALYSIS DEMO')
    print('  Showcasing Rekordbox-quality metadata on 3 real tracks')
    print(SEPARATOR)

    # Connect to database
    db = Database('/app/data/db/metadata.sqlite')
    db.connect()

    # Load track info
    tracks_data = []
    for track_id in TRACK_IDS:
        row = db.conn.execute('SELECT * FROM tracks WHERE id = ?', (track_id,)).fetchone()
        if not row:
            print(f'ERROR: Track {track_id} not found in database')
            return
        tracks_data.append(dict(row))

    print(f'\n  Set: {len(tracks_data)} tracks selected')
    for i, t in enumerate(tracks_data):
        print(f'    {i+1}. [{t["key"]}] {t["bpm"]:.1f} BPM  {t["title"]}')

    structures = []

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 1: Structure Analysis (per-track)
    # ═══════════════════════════════════════════════════════════════════
    for track in tracks_data:
        structure = analyze_and_display(track, db)
        structures.append(structure)

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 2: Section-Aware Transition Planning
    # ═══════════════════════════════════════════════════════════════════
    demo_transition_planning(tracks_data, structures, db)

    # ═══════════════════════════════════════════════════════════════════
    # PHASE 3: Liquidsoap Script Preview
    # ═══════════════════════════════════════════════════════════════════
    demo_liquidsoap_output(tracks_data, structures)

    # ═══════════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════════
    print_header('ANALYSIS SUMMARY')

    total_sections = sum(len(s.sections) for s in structures)
    total_cues = sum(len(s.cue_points) for s in structures)
    total_loops = sum(len(s.loop_regions) for s in structures)

    print(f'  Tracks analyzed:     {len(structures)}')
    print(f'  Sections detected:   {total_sections}')
    print(f'  Semantic cues:       {total_cues}')
    print(f'  Loop regions:        {total_loops}')
    print()
    for i, (t, s) in enumerate(zip(tracks_data, structures)):
        print(f'  Track {i+1}: {t["title"]}')
        print(f'    Sections: {" -> ".join(sec.label.upper() for sec in s.sections)}')
        print(f'    Kick: {s.kick_pattern}  |  Vocal: {"yes" if s.has_vocal else "no"}  |  Bars: {s.total_bars}')
        mix_in = next((c for c in s.cue_points if c.label == 'mix_in'), None)
        mix_out = next((c for c in s.cue_points if c.label == 'mix_out'), None)
        if mix_in:
            print(f'    Mix In:  {format_time(mix_in.position_seconds)} (bar {mix_in.position_bar})')
        if mix_out:
            print(f'    Mix Out: {format_time(mix_out.position_seconds)} (bar {mix_out.position_bar})')
        print()

    # Verify DB persistence
    ta_count = db.conn.execute('SELECT COUNT(*) FROM track_analysis').fetchone()[0]
    print(f'  Database: {ta_count} tracks now have rich analysis in track_analysis table')

    db.disconnect()
    print(f'\n{SEPARATOR}')
    print('  DEMO COMPLETE')
    print(SEPARATOR)


if __name__ == '__main__':
    main()
