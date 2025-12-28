"""SQLite caching layer for venue2playlist.

Caches:
- Venue → performance records (with TTL)
- Artist → Spotify ID mappings
- Track selections
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Generator

from .models import Artist, Performance, VenueMatch


class Cache:
    """SQLite-based cache for API responses and processed data."""

    DEFAULT_TTL_DAYS = 7

    def __init__(self, db_path: Path):
        """Initialize the cache.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self._ensure_db_exists()
        self._create_tables()

    def _ensure_db_exists(self) -> None:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _create_tables(self) -> None:
        """Create cache tables if they don't exist."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS venue_searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_name TEXT NOT NULL,
                    city TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    results_json TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(venue_name, city, source_name)
                );

                CREATE TABLE IF NOT EXISTS performances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    venue_id TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    performances_json TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(venue_id, source_name, start_date, end_date)
                );

                CREATE TABLE IF NOT EXISTS artist_mappings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artist_name TEXT NOT NULL,
                    canonical_name TEXT,
                    musicbrainz_id TEXT,
                    spotify_id TEXT,
                    metadata_json TEXT,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(artist_name)
                );

                CREATE TABLE IF NOT EXISTS track_selections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spotify_artist_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    tracks_json TEXT NOT NULL,
                    cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(spotify_artist_id, strategy)
                );

                CREATE INDEX IF NOT EXISTS idx_venue_searches_lookup 
                    ON venue_searches(venue_name, city, source_name);
                CREATE INDEX IF NOT EXISTS idx_performances_lookup 
                    ON performances(venue_id, source_name);
                CREATE INDEX IF NOT EXISTS idx_artist_mappings_name 
                    ON artist_mappings(artist_name);
            """)
            conn.commit()

    def _is_expired(self, cached_at: str, ttl_days: int | None = None) -> bool:
        """Check if a cached entry has expired."""
        ttl = ttl_days or self.DEFAULT_TTL_DAYS
        cached_time = datetime.fromisoformat(cached_at)
        return datetime.now() - cached_time > timedelta(days=ttl)

    # Venue searches
    def get_venue_search(
        self, venue_name: str, city: str, source_name: str
    ) -> list[VenueMatch] | None:
        """Get cached venue search results."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT results_json, cached_at FROM venue_searches
                WHERE venue_name = ? AND city = ? AND source_name = ?
                """,
                (venue_name.lower(), city.lower(), source_name),
            ).fetchone()

            if row and not self._is_expired(row["cached_at"]):
                data = json.loads(row["results_json"])
                return [VenueMatch.model_validate(v) for v in data]
            return None

    def set_venue_search(
        self, venue_name: str, city: str, source_name: str, results: list[VenueMatch]
    ) -> None:
        """Cache venue search results."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO venue_searches (venue_name, city, source_name, results_json, cached_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    venue_name.lower(),
                    city.lower(),
                    source_name,
                    json.dumps([v.model_dump() for v in results], default=str),
                ),
            )
            conn.commit()

    # Performance records
    def get_performances(
        self,
        venue_id: str,
        source_name: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[Performance] | None:
        """Get cached performance records."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT performances_json, cached_at FROM performances
                WHERE venue_id = ? AND source_name = ? 
                    AND (start_date = ? OR (start_date IS NULL AND ? IS NULL))
                    AND (end_date = ? OR (end_date IS NULL AND ? IS NULL))
                """,
                (venue_id, source_name, start_date, start_date, end_date, end_date),
            ).fetchone()

            if row and not self._is_expired(row["cached_at"]):
                data = json.loads(row["performances_json"])
                return [Performance.model_validate(p) for p in data]
            return None

    def set_performances(
        self,
        venue_id: str,
        source_name: str,
        performances: list[Performance],
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> None:
        """Cache performance records."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO performances 
                    (venue_id, source_name, start_date, end_date, performances_json, cached_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    venue_id,
                    source_name,
                    start_date,
                    end_date,
                    json.dumps([p.model_dump() for p in performances], default=str),
                ),
            )
            conn.commit()

    # Artist mappings
    def get_artist_mapping(self, artist_name: str) -> Artist | None:
        """Get cached artist mapping."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT canonical_name, musicbrainz_id, spotify_id, metadata_json, cached_at
                FROM artist_mappings WHERE artist_name = ?
                """,
                (artist_name.lower(),),
            ).fetchone()

            if row and not self._is_expired(row["cached_at"]):
                metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                return Artist(
                    name=row["canonical_name"] or artist_name,
                    musicbrainz_id=row["musicbrainz_id"],
                    spotify_id=row["spotify_id"],
                    metadata=metadata,
                )
            return None

    def set_artist_mapping(self, artist_name: str, artist: Artist) -> None:
        """Cache artist mapping."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO artist_mappings 
                    (artist_name, canonical_name, musicbrainz_id, spotify_id, metadata_json, cached_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    artist_name.lower(),
                    artist.name,
                    artist.musicbrainz_id,
                    artist.spotify_id,
                    json.dumps(artist.metadata, default=str),
                ),
            )
            conn.commit()

    # Track selections
    def get_track_selections(self, spotify_artist_id: str, strategy: str) -> list[dict] | None:
        """Get cached track selections for an artist and strategy."""
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT tracks_json, cached_at FROM track_selections
                WHERE spotify_artist_id = ? AND strategy = ?
                """,
                (spotify_artist_id, strategy),
            ).fetchone()

            if row and not self._is_expired(row["cached_at"]):
                return json.loads(row["tracks_json"])
            return None

    def set_track_selections(
        self, spotify_artist_id: str, strategy: str, tracks: list[dict]
    ) -> None:
        """Cache track selections."""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO track_selections 
                    (spotify_artist_id, strategy, tracks_json, cached_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (spotify_artist_id, strategy, json.dumps(tracks, default=str)),
            )
            conn.commit()

    def clear_expired(self, ttl_days: int | None = None) -> int:
        """Clear all expired entries. Returns count of deleted rows."""
        ttl = ttl_days or self.DEFAULT_TTL_DAYS
        cutoff = (datetime.now() - timedelta(days=ttl)).isoformat()
        total_deleted = 0

        with self._get_connection() as conn:
            for table in ["venue_searches", "performances", "artist_mappings", "track_selections"]:
                cursor = conn.execute(f"DELETE FROM {table} WHERE cached_at < ?", (cutoff,))
                total_deleted += cursor.rowcount
            conn.commit()

        return total_deleted

    def clear_all(self) -> None:
        """Clear all cached data."""
        with self._get_connection() as conn:
            for table in ["venue_searches", "performances", "artist_mappings", "track_selections"]:
                conn.execute(f"DELETE FROM {table}")
            conn.commit()
