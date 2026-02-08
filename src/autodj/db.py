"""
SQLite Database Management for AutoDJ-Headless.

Manages track metadata, cue points, and playlist history.

Per SPEC.md § 2:
- Schema: tracks (BPM, key, cue points, ID3 metadata)
- History: playlists (track_id, used_at) for repeat decay
- Atomic writes, no concurrent access (single machine)
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class TrackMetadata:
    """Immutable container for track analysis data."""

    track_id: str
    file_path: str
    duration_seconds: float
    bpm: Optional[float]
    key: Optional[str]  # Camelot notation (1A-12B) or "unknown"
    cue_in_frames: Optional[int]
    cue_out_frames: Optional[int]
    loop_start_frames: Optional[int]
    loop_length_bars: Optional[int]
    analyzed_at: str
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None


class Database:
    """SQLite database manager for AutoDJ metadata."""

    SCHEMA_VERSION = 2

    # SQL schema definition
    SCHEMA = """
    -- Tracks table: core metadata + analysis results
    CREATE TABLE IF NOT EXISTS tracks (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL UNIQUE,
        duration_seconds REAL NOT NULL,
        bpm REAL,
        key TEXT,
        cue_in_frames INTEGER,
        cue_out_frames INTEGER,
        loop_start_frames INTEGER,
        loop_length_bars INTEGER,
        title TEXT,
        artist TEXT,
        album TEXT,
        analyzed_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- Playlist history: for repeat decay calculation
    CREATE TABLE IF NOT EXISTS playlist_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        track_id TEXT NOT NULL,
        playlist_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        used_at TEXT NOT NULL,
        FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
    );

    -- Schema version tracking
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        updated_at TEXT NOT NULL
    );

    -- Indices for common queries
    CREATE INDEX IF NOT EXISTS idx_tracks_bpm ON tracks(bpm);
    CREATE INDEX IF NOT EXISTS idx_tracks_key ON tracks(key);
    CREATE INDEX IF NOT EXISTS idx_playlist_track_id ON playlist_history(track_id);
    CREATE INDEX IF NOT EXISTS idx_playlist_used_at ON playlist_history(used_at);

    -- Analysis progress: single-row state for analyzer
    CREATE TABLE IF NOT EXISTS analysis_progress (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        total INTEGER NOT NULL DEFAULT 0,
        processed INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    );

    -- Rich track analysis: JSON blobs for structure, cues, loops, spectral, loudness
    CREATE TABLE IF NOT EXISTS track_analysis (
        track_id TEXT PRIMARY KEY,
        sections_json TEXT,
        cue_points_json TEXT,
        loop_regions_json TEXT,
        energy_profile_json TEXT,
        spectral_json TEXT,
        loudness_json TEXT,
        kick_pattern TEXT,
        downbeat_seconds REAL,
        total_bars INTEGER,
        has_vocal INTEGER,
        analyzed_at TEXT NOT NULL,
        FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
    );
    """

    def __init__(self, db_path: str = "data/db/metadata.sqlite"):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn: Optional[sqlite3.Connection] = None

    def connect(self) -> None:
        """Open database connection and initialize schema."""
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        logger.info(f"Connected to database: {self.db_path}")
        self._initialize_schema()

    def disconnect(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database disconnected")

    def _initialize_schema(self) -> None:
        """Initialize or migrate schema."""
        assert self.conn is not None
        cursor = self.conn.cursor()

        # Check current schema version
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if not cursor.fetchone():
            # First initialization
            logger.info("Initializing database schema...")
            cursor.executescript(self.SCHEMA)
            cursor.execute(
                "INSERT INTO schema_version (version, updated_at) VALUES (?, ?)",
                (self.SCHEMA_VERSION, datetime.now(timezone.utc).isoformat()),
            )

            # Initialize analysis_progress row (single row id=1)
            cursor.execute(
                "INSERT OR REPLACE INTO analysis_progress (id, total, processed, updated_at) VALUES (1, 0, 0, ?)",
                (datetime.now(timezone.utc).isoformat(),),
            )

            self.conn.commit()
            logger.info(f"✅ Database schema initialized (v{self.SCHEMA_VERSION})")
        else:
            # Check for schema upgrades
            cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            current_version = cursor.fetchone()[0]
            if current_version < self.SCHEMA_VERSION:
                self._run_migrations(current_version)

            # Ensure analysis_progress table exists on older DBs (migration)
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_progress'"
            )
            if not cursor.fetchone():
                logger.info("Adding missing analysis_progress table (migration)")
                cursor.executescript(
                    "CREATE TABLE IF NOT EXISTS analysis_progress (\n"
                    "    id INTEGER PRIMARY KEY CHECK (id = 1),\n"
                    "    total INTEGER NOT NULL DEFAULT 0,\n"
                    "    processed INTEGER NOT NULL DEFAULT 0,\n"
                    "    updated_at TEXT NOT NULL\n"
                    ");\n"
                )
                cursor.execute(
                    "INSERT OR REPLACE INTO analysis_progress (id, total, processed, updated_at) VALUES (1, 0, 0, ?)",
                    (datetime.now(timezone.utc).isoformat(),),
                )
                self.conn.commit()

    def _run_migrations(self, current_version: int) -> None:
        """Run schema migrations from current_version to SCHEMA_VERSION."""
        assert self.conn is not None
        cursor = self.conn.cursor()

        if current_version < 2:
            logger.info("Migrating schema v1 -> v2: adding track_analysis table")
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS track_analysis (
                    track_id TEXT PRIMARY KEY,
                    sections_json TEXT,
                    cue_points_json TEXT,
                    loop_regions_json TEXT,
                    energy_profile_json TEXT,
                    spectral_json TEXT,
                    loudness_json TEXT,
                    kick_pattern TEXT,
                    downbeat_seconds REAL,
                    total_bars INTEGER,
                    has_vocal INTEGER,
                    analyzed_at TEXT NOT NULL,
                    FOREIGN KEY (track_id) REFERENCES tracks(id) ON DELETE CASCADE
                );
            """)
            cursor.execute(
                "INSERT OR REPLACE INTO schema_version (version, updated_at) VALUES (?, ?)",
                (2, datetime.now(timezone.utc).isoformat()),
            )
            self.conn.commit()
            logger.info("Schema migration v1 -> v2 complete")


    def add_track(self, metadata: TrackMetadata) -> None:
        """
        Add or update a track in the database.

        Args:
            metadata: TrackMetadata object with analysis results.
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO tracks (
                id, file_path, duration_seconds, bpm, key,
                cue_in_frames, cue_out_frames, loop_start_frames, loop_length_bars,
                title, artist, album, analyzed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata.track_id,
                metadata.file_path,
                metadata.duration_seconds,
                metadata.bpm,
                metadata.key,
                metadata.cue_in_frames,
                metadata.cue_out_frames,
                metadata.loop_start_frames,
                metadata.loop_length_bars,
                metadata.title,
                metadata.artist,
                metadata.album,
                metadata.analyzed_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        logger.debug(f"Added/updated track: {metadata.track_id}")

    def get_track(self, track_id: str) -> Optional[TrackMetadata]:
        """
        Retrieve track metadata by ID.

        Args:
            track_id: Unique track identifier.

        Returns:
            TrackMetadata or None if not found.
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM tracks WHERE id = ?", (track_id,))
        row = cursor.fetchone()

        if not row:
            return None

        return TrackMetadata(
            track_id=row["id"],
            file_path=row["file_path"],
            duration_seconds=row["duration_seconds"],
            bpm=row["bpm"],
            key=row["key"],
            cue_in_frames=row["cue_in_frames"],
            cue_out_frames=row["cue_out_frames"],
            loop_start_frames=row["loop_start_frames"],
            loop_length_bars=row["loop_length_bars"],
            analyzed_at=row["analyzed_at"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
        )

    def get_track_by_path(self, file_path: str) -> Optional[TrackMetadata]:
        """
        Retrieve track by file path.

        Args:
            file_path: Path to audio file.

        Returns:
            TrackMetadata or None if not found.
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        cursor.execute("SELECT * FROM tracks WHERE file_path = ?", (file_path,))
        row = cursor.fetchone()

        if not row:
            return None

        return TrackMetadata(
            track_id=row["id"],
            file_path=row["file_path"],
            duration_seconds=row["duration_seconds"],
            bpm=row["bpm"],
            key=row["key"],
            cue_in_frames=row["cue_in_frames"],
            cue_out_frames=row["cue_out_frames"],
            loop_start_frames=row["loop_start_frames"],
            loop_length_bars=row["loop_length_bars"],
            analyzed_at=row["analyzed_at"],
            title=row["title"],
            artist=row["artist"],
            album=row["album"],
        )

    def list_tracks(
        self, bpm_range: Optional[tuple] = None, key: Optional[str] = None
    ) -> List[TrackMetadata]:
        """
        List tracks with optional filtering.

        Args:
            bpm_range: Tuple (min_bpm, max_bpm) to filter by BPM range.
            key: Camelot key to filter by exact key.

        Returns:
            List of TrackMetadata objects matching filters.
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        query = "SELECT * FROM tracks WHERE 1=1"
        params = []

        if bpm_range:
            min_bpm, max_bpm = bpm_range
            query += " AND bpm BETWEEN ? AND ?"
            params.extend([min_bpm, max_bpm])

        if key:
            query += " AND key = ?"
            params.append(key)

        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            TrackMetadata(
                track_id=row["id"],
                file_path=row["file_path"],
                duration_seconds=row["duration_seconds"],
                bpm=row["bpm"],
                key=row["key"],
                cue_in_frames=row["cue_in_frames"],
                cue_out_frames=row["cue_out_frames"],
                loop_start_frames=row["loop_start_frames"],
                loop_length_bars=row["loop_length_bars"],
                analyzed_at=row["analyzed_at"],
                title=row["title"],
                artist=row["artist"],
                album=row["album"],
            )
            for row in rows
        ]

    def record_playlist_usage(
        self, track_id: str, playlist_id: str, position: int
    ) -> None:
        """
        Record track usage in a playlist for repeat decay tracking.

        Args:
            track_id: Track ID.
            playlist_id: Generated playlist ID.
            position: Track position in playlist.
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        cursor.execute(
            """
            INSERT INTO playlist_history (track_id, playlist_id, position, used_at)
            VALUES (?, ?, ?, ?)
            """,
            (track_id, playlist_id, position, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    # ===== Analysis progress helpers =====
    def set_analysis_progress(self, total: int, processed: int) -> None:
        """Set the single-row analysis progress state."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO analysis_progress (id, total, processed, updated_at) VALUES (1, ?, ?, ?)",
            (total, processed, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def update_analysis_progress(self, processed_increment: int = 1) -> None:
        """Increment the processed count by `processed_increment`."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE analysis_progress SET processed = processed + ?, updated_at = ? WHERE id = 1",
            (processed_increment, datetime.now(timezone.utc).isoformat()),
        )
        self.conn.commit()

    def get_analysis_progress(self) -> dict:
        """Return the analysis progress as a dict: {total, processed, updated_at}."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT total, processed, updated_at FROM analysis_progress WHERE id = 1")
        row = cursor.fetchone()
        if not row:
            return {"total": 0, "processed": 0, "updated_at": None}
        return {"total": row[0], "processed": row[1], "updated_at": row[2]}

    def get_recent_usage(self, track_id: str, hours_back: int = 168) -> List[Dict[str, Any]]:
        """
        Get recent playlist usages for repeat decay calculation.

        Args:
            track_id: Track ID.
            hours_back: Number of hours to look back (default: 7 days = 168h).

        Returns:
            List of usage records (playlist_id, position, used_at).
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        # Calculate cutoff time
        from datetime import timedelta

        cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()

        cursor.execute(
            """
            SELECT playlist_id, position, used_at FROM playlist_history
            WHERE track_id = ? AND used_at > ?
            ORDER BY used_at DESC
            """,
            (track_id, cutoff_time),
        )
        rows = cursor.fetchall()

        return [dict(row) for row in rows]

    # ===== Rich track analysis (Phase 5: structure) =====

    def save_track_analysis(self, track_id: str, analysis: Dict[str, Any]) -> None:
        """
        Save or update rich track analysis data.

        Args:
            track_id: Track ID (must exist in tracks table).
            analysis: Dict with keys matching track_analysis columns.
                      JSON-serializable values for *_json columns.
        """
        assert self.conn is not None
        import json

        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO track_analysis (
                track_id, sections_json, cue_points_json, loop_regions_json,
                energy_profile_json, spectral_json, loudness_json,
                kick_pattern, downbeat_seconds, total_bars, has_vocal,
                analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_id,
                json.dumps(analysis.get("sections")) if analysis.get("sections") is not None else None,
                json.dumps(analysis.get("cue_points")) if analysis.get("cue_points") is not None else None,
                json.dumps(analysis.get("loop_regions")) if analysis.get("loop_regions") is not None else None,
                json.dumps(analysis.get("energy_profile")) if analysis.get("energy_profile") is not None else None,
                json.dumps(analysis.get("spectral")) if analysis.get("spectral") is not None else None,
                json.dumps(analysis.get("loudness")) if analysis.get("loudness") is not None else None,
                analysis.get("kick_pattern"),
                analysis.get("downbeat_seconds"),
                analysis.get("total_bars"),
                1 if analysis.get("has_vocal") else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.conn.commit()
        logger.debug(f"Saved track analysis: {track_id}")

    def get_track_analysis(self, track_id: str) -> Optional[Dict[str, Any]]:
        """
        Load rich track analysis data.

        Args:
            track_id: Track ID.

        Returns:
            Dict with analysis data, or None if not found.
        """
        assert self.conn is not None
        import json

        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM track_analysis WHERE track_id = ?", (track_id,))
        row = cursor.fetchone()

        if not row:
            return None

        result = {
            "track_id": row["track_id"],
            "sections": json.loads(row["sections_json"]) if row["sections_json"] else None,
            "cue_points": json.loads(row["cue_points_json"]) if row["cue_points_json"] else None,
            "loop_regions": json.loads(row["loop_regions_json"]) if row["loop_regions_json"] else None,
            "energy_profile": json.loads(row["energy_profile_json"]) if row["energy_profile_json"] else None,
            "spectral": json.loads(row["spectral_json"]) if row["spectral_json"] else None,
            "loudness": json.loads(row["loudness_json"]) if row["loudness_json"] else None,
            "kick_pattern": row["kick_pattern"],
            "downbeat_seconds": row["downbeat_seconds"],
            "total_bars": row["total_bars"],
            "has_vocal": bool(row["has_vocal"]),
            "analyzed_at": row["analyzed_at"],
        }
        return result

    def list_tracks_with_analysis(self) -> List[Dict[str, Any]]:
        """
        List all tracks that have rich analysis data.

        Returns:
            List of dicts with track metadata joined with analysis data.
        """
        assert self.conn is not None
        import json

        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT t.*, ta.kick_pattern, ta.downbeat_seconds, ta.total_bars,
                   ta.has_vocal, ta.sections_json, ta.cue_points_json
            FROM tracks t
            INNER JOIN track_analysis ta ON t.id = ta.track_id
        """)
        rows = cursor.fetchall()

        result = []
        for row in rows:
            track = {
                "id": row["id"],
                "file_path": row["file_path"],
                "duration_seconds": row["duration_seconds"],
                "bpm": row["bpm"],
                "key": row["key"],
                "cue_in_frames": row["cue_in_frames"],
                "cue_out_frames": row["cue_out_frames"],
                "title": row["title"],
                "artist": row["artist"],
                "kick_pattern": row["kick_pattern"],
                "downbeat_seconds": row["downbeat_seconds"],
                "total_bars": row["total_bars"],
                "has_vocal": bool(row["has_vocal"]),
            }
            if row["cue_points_json"]:
                track["cue_points"] = json.loads(row["cue_points_json"])
            if row["sections_json"]:
                track["sections"] = json.loads(row["sections_json"])
            result.append(track)

        return result

    def get_stats(self) -> Dict[str, Any]:
        """
        Get database statistics.

        Returns:
            Dictionary with counts and analysis stats.
        """
        assert self.conn is not None
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM tracks")
        total_tracks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) as analyzed FROM tracks WHERE bpm IS NOT NULL")
        analyzed_tracks = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) as with_cues FROM tracks WHERE cue_in_frames IS NOT NULL")
        tracks_with_cues = cursor.fetchone()[0]

        cursor.execute(
            "SELECT MIN(bpm) as min_bpm, MAX(bpm) as max_bpm, AVG(bpm) as avg_bpm FROM tracks WHERE bpm IS NOT NULL"
        )
        bpm_stats = dict(cursor.fetchone())

        return {
            "total_tracks": total_tracks,
            "analyzed_tracks": analyzed_tracks,
            "tracks_with_cues": tracks_with_cues,
            "bpm_stats": bpm_stats,
        }
