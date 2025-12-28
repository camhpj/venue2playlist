"""Pipeline orchestrator for venue2playlist.

Coordinates the full flow:
1. Search venue in data sources
2. Get performances
3. Filter performances
4. Enrich with MusicBrainz metadata
5. Get tracks from Spotify
6. Create playlist
"""

from datetime import date
from pathlib import Path

from .cache import Cache
from .config import Settings, get_settings
from .filters import ConfidenceFilter, DateRangeFilter, FilterChain
from .logging import configure_logging, get_logger
from .models import ExcludedItem, Performance, PlaylistResult, Track, VenueMatch
from .sources import DataSourceRegistry
from .sources.musicbrainz import MusicBrainzClient
from .sources.setlist_fm import SetlistFmSource
from .spotify import SpotifyClient

logger = get_logger(__name__)


class Pipeline:
    """Main pipeline orchestrator for venue2playlist."""

    def __init__(self, settings: Settings | None = None):
        """Initialize the pipeline.
        
        Args:
            settings: Optional settings override
        """
        self.settings = settings or get_settings()
        
        # Configure logging
        configure_logging(
            level=self.settings.log_level,
            format=self.settings.log_format,
        )

        # Initialize cache
        self.cache = Cache(self.settings.cache_path)

        # Initialize data sources
        self.source_registry = DataSourceRegistry()
        self._init_sources()

        # Initialize MusicBrainz client
        self.musicbrainz = MusicBrainzClient(cache=self.cache)

        # Spotify client (initialized lazily to defer OAuth)
        self._spotify: SpotifyClient | None = None

    def _init_sources(self) -> None:
        """Initialize and register data sources."""
        setlist_fm = SetlistFmSource(
            api_key=self.settings.setlist_fm_api_key,
            cache=self.cache,
        )
        self.source_registry.register(setlist_fm)

        logger.info(
            "pipeline_initialized",
            sources=self.source_registry.names,
        )

    @property
    def spotify(self) -> SpotifyClient:
        """Lazy initialization of Spotify client."""
        if not self._spotify:
            self._spotify = SpotifyClient(
                client_id=self.settings.spotify_client_id,
                client_secret=self.settings.spotify_client_secret,
                redirect_uri=self.settings.spotify_redirect_uri,
                cache_path=self.settings.token_cache_path,
                cache=self.cache,
            )
        return self._spotify

    def search_venues(self, venue_name: str, city: str) -> list[VenueMatch]:
        """Search for venues across all data sources.
        
        Args:
            venue_name: Venue name to search
            city: City where venue is located
            
        Returns:
            Combined list of venue matches from all sources
        """
        logger.info("searching_venues", venue=venue_name, city=city)

        all_matches: list[VenueMatch] = []
        for source in self.source_registry.all():
            try:
                matches = source.search_venues(venue_name, city)
                all_matches.extend(matches)
            except Exception as e:
                logger.error(
                    "source_search_failed",
                    source=source.name,
                    error=str(e),
                )

        logger.info("venues_found", count=len(all_matches))
        return all_matches

    def get_performances(
        self,
        venue_id: str,
        source_name: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[Performance]:
        """Get performances from a specific source.
        
        Args:
            venue_id: Venue ID from search results
            source_name: Data source to query
            start_date: Optional date filter start
            end_date: Optional date filter end
            
        Returns:
            List of performances
        """
        source = self.source_registry.get(source_name)
        if not source:
            logger.error("source_not_found", source_name=source_name)
            return []

        return source.get_performances(venue_id, start_date, end_date)

    def run(
        self,
        venue_name: str,
        city: str,
        start_date: date,
        end_date: date,
        strategy: str,
        playlist_name: str,
        min_confidence: float = 0.5,
        enrich_metadata: bool = True,
    ) -> PlaylistResult:
        """Run the full pipeline to create a playlist.
        
        Args:
            venue_name: Name of the venue
            city: City where venue is located
            start_date: Start of date range
            end_date: End of date range
            strategy: Track selection strategy (e.g., "top-3")
            playlist_name: Name for the created playlist
            min_confidence: Minimum confidence threshold
            enrich_metadata: Whether to enrich with MusicBrainz
            
        Returns:
            PlaylistResult with all details
        """
        logger.info(
            "pipeline_start",
            venue=venue_name,
            city=city,
            date_range=f"{start_date} to {end_date}",
            strategy=strategy,
        )

        all_excluded: list[ExcludedItem] = []
        sources_used: list[str] = []

        # Step 1: Search for venue
        venues = self.search_venues(venue_name, city)
        if not venues:
            logger.error("no_venues_found", venue=venue_name, city=city)
            raise ValueError(f"No venues found matching '{venue_name}' in {city}")

        # Use first match (could add interactive selection later)
        venue = venues[0]
        logger.info(
            "venue_selected",
            venue_id=venue.venue_id,
            venue_name=venue.venue_name,
            source=venue.source_name,
        )
        sources_used.append(venue.source_name)

        # Step 2: Get performances
        performances = self.get_performances(
            venue.venue_id,
            venue.source_name,
            start_date,
            end_date,
        )
        logger.info("performances_fetched", count=len(performances))

        # Step 3: Apply filters
        filter_chain = (
            FilterChain()
            .add(DateRangeFilter(start_date, end_date))
            .add(ConfidenceFilter(min_confidence))
        )

        filter_result = filter_chain.apply(performances)
        filtered_performances = filter_result.included
        all_excluded.extend(filter_result.excluded)

        logger.info(
            "performances_filtered",
            before=len(performances),
            after=len(filtered_performances),
            excluded=len(filter_result.excluded),
        )

        # Step 4: Deduplicate artists
        seen_artists: set[str] = set()
        unique_performances: list[Performance] = []
        for perf in filtered_performances:
            artist_key = perf.artist_name.lower()
            if artist_key not in seen_artists:
                seen_artists.add(artist_key)
                unique_performances.append(perf)

        logger.info(
            "artists_deduplicated",
            unique=len(unique_performances),
        )

        # Step 5: Enrich with MusicBrainz (optional)
        if enrich_metadata:
            for perf in unique_performances:
                mbid = perf.metadata.get("artist_mbid")
                enrichment = self.musicbrainz.enrich_performance_metadata(
                    perf.artist_name, mbid
                )
                perf.metadata.update(enrichment)

        # Step 6: Get tracks from Spotify
        all_tracks: list[Track] = []
        for perf in unique_performances:
            tracks, excluded = self.spotify.get_tracks_for_artist(
                perf.artist_name,
                strategy,
                perf.performance_date,
            )
            all_tracks.extend(tracks)
            all_excluded.extend(excluded)

        logger.info("tracks_collected", count=len(all_tracks))

        if not all_tracks:
            logger.error("no_tracks_found")
            raise ValueError("No tracks found for any artists")

        # Step 7: Create playlist
        description = (
            f"Artists who performed at {venue_name} ({city}) "
            f"from {start_date} to {end_date}. "
            f"Created by venue2playlist."
        )
        playlist = self.spotify.create_playlist(
            name=playlist_name,
            description=description,
        )

        # Step 8: Add tracks
        track_ids = [t.spotify_id for t in all_tracks]
        added_count = self.spotify.add_tracks_to_playlist(
            playlist["id"],
            track_ids,
        )

        logger.info(
            "pipeline_complete",
            playlist_id=playlist["id"],
            tracks_added=added_count,
            excluded_count=len(all_excluded),
        )

        return PlaylistResult(
            playlist_id=playlist["id"],
            playlist_url=playlist["external_urls"]["spotify"],
            playlist_name=playlist_name,
            performances=unique_performances,
            tracks=all_tracks,
            excluded_items=all_excluded,
            sources_used=sources_used,
            total_artists=len(unique_performances),
        )
