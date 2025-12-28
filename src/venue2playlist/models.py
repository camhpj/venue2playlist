"""Pydantic data models for venue2playlist.

All parsed data must conform to these schemas for validation and filtering.
"""

from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class Performance(BaseModel):
    """A verified performance record from a data source.
    
    Each record must include temporal evidence (date or date range).
    Records without dates must be excluded.
    """

    artist_name: str = Field(description="Artist or band name as documented")
    venue_name: str = Field(description="Venue name as documented")
    city: str = Field(description="City where the venue is located")
    country: str | None = Field(default=None, description="Country code (ISO 3166-1 alpha-2)")

    # Temporal data - at least one must be present
    performance_date: date | None = Field(default=None, description="Exact performance date if known")
    performance_date_range: tuple[date, date] | None = Field(
        default=None, description="Date range (start, end) if exact date unknown"
    )

    # Source attribution (required)
    source_name: str = Field(description="Name of the data source (e.g., 'setlist.fm')")
    source_reference: str = Field(description="URL or identifier for the source record")

    # Confidence scoring
    confidence_score: float = Field(
        ge=0.0, le=1.0, description="Confidence in the record (0.0-1.0). < 1.0 if dates approximate"
    )

    # Extensible metadata for filtering
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured fields (genre, country, etc.) for filtering",
    )

    def has_valid_date(self) -> bool:
        """Check if this performance has temporal evidence."""
        return self.performance_date is not None or self.performance_date_range is not None

    def overlaps_range(self, start: date, end: date) -> bool:
        """Check if this performance falls within or overlaps the given date range."""
        if self.performance_date:
            return start <= self.performance_date <= end
        if self.performance_date_range:
            perf_start, perf_end = self.performance_date_range
            # Ranges overlap if neither ends before the other starts
            return perf_start <= end and start <= perf_end
        return False


class Artist(BaseModel):
    """A canonicalized artist identity."""

    name: str = Field(description="Canonical artist name")
    aliases: list[str] = Field(default_factory=list, description="Known aliases and spelling variants")
    musicbrainz_id: str | None = Field(default=None, description="MusicBrainz artist MBID")
    spotify_id: str | None = Field(default=None, description="Spotify artist ID")

    # Extensible metadata for filtering
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured fields (genres, country, active_years, etc.)",
    )


class Track(BaseModel):
    """A Spotify track selected for the playlist."""

    spotify_id: str = Field(description="Spotify track ID")
    name: str = Field(description="Track name")
    artist_name: str = Field(description="Artist name on Spotify")
    album_name: str = Field(description="Album name")
    release_date: date | None = Field(default=None, description="Album/track release date")
    popularity: int = Field(ge=0, le=100, description="Spotify popularity score (0-100)")

    # Selection metadata
    selection_strategy: str = Field(description="Strategy used to select this track")
    selection_reason: str = Field(description="Why this track was selected")


class ExcludedItem(BaseModel):
    """A performance or artist that was excluded from the playlist."""

    item_type: str = Field(description="Type of item: 'performance' or 'artist'")
    name: str = Field(description="Artist or performance identifier")
    reason: str = Field(description="Reason for exclusion")
    filter_name: str | None = Field(default=None, description="Filter that caused exclusion")


class PlaylistResult(BaseModel):
    """Final output of the playlist creation process."""

    playlist_id: str = Field(description="Spotify playlist ID")
    playlist_url: str = Field(description="Spotify playlist URL")
    playlist_name: str = Field(description="Name of the created playlist")

    # Included data
    performances: list[Performance] = Field(description="Performances included in the playlist")
    tracks: list[Track] = Field(description="Tracks added to the playlist")

    # Audit trail
    excluded_items: list[ExcludedItem] = Field(
        default_factory=list, description="Items excluded with reasons"
    )
    sources_used: list[str] = Field(description="Data sources queried")
    total_artists: int = Field(description="Total unique artists in playlist")


class VenueMatch(BaseModel):
    """A venue match from a data source search."""

    venue_id: str = Field(description="Venue identifier in the data source")
    venue_name: str = Field(description="Venue name")
    city: str = Field(description="City name")
    country: str | None = Field(default=None, description="Country code")
    source_name: str = Field(description="Data source name")

    # Extensible metadata
    metadata: dict[str, Any] = Field(default_factory=dict)
