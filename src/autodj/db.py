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

    SCHEMA_VERSION = 1

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
            self.conn.commit()
            logger.info(f"✅ Database schema initialized (v{self.SCHEMA_VERSION})")
        else:
            # Check for schema upgrades
            cursor.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
            current_version = cursor.fetchone()[0]
            if current_version < self.SCHEMA_VERSION:
                logger.warning(
                    f"Schema version mismatch: {current_version} < {self.SCHEMA_VERSION}. "
                    f"Consider running migration."
                )

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
