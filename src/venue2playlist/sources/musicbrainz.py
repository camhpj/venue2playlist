"""MusicBrainz artist canonicalization.

Used to normalize artist identities and resolve aliases.
Not a full data source - provides artist metadata enrichment.
"""

import musicbrainzngs

from ..cache import Cache
from ..logging import get_logger
from ..models import Artist

logger = get_logger(__name__)

# Configure musicbrainzngs
musicbrainzngs.set_useragent(
    "venue2playlist",
    "0.1.0",
    "https://github.com/venue2playlist/venue2playlist",
)


class MusicBrainzClient:
    """MusicBrainz API client for artist canonicalization.
    
    Provides:
    - Artist name normalization
    - Alias resolution
    - MusicBrainz ID lookup
    - Metadata enrichment (genres, country, etc.)
    """

    def __init__(self, cache: Cache | None = None):
        """Initialize the MusicBrainz client.
        
        Args:
            cache: Optional cache instance
        """
        self.cache = cache

    def canonicalize_artist(self, artist_name: str, mbid: str | None = None) -> Artist | None:
        """Canonicalize an artist name and get metadata.
        
        Args:
            artist_name: Artist name to look up
            mbid: Optional MusicBrainz ID (from setlist.fm, etc.)
            
        Returns:
            Canonicalized Artist with metadata, or None if not found
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_artist_mapping(artist_name)
            if cached:
                logger.info("artist_cache_hit", artist=artist_name)
                return cached

        logger.info("canonicalizing_artist", artist=artist_name, mbid=mbid)

        try:
            if mbid:
                # Direct lookup by MBID
                result = musicbrainzngs.get_artist_by_id(
                    mbid,
                    includes=["aliases", "tags"],
                )
                artist_data = result.get("artist", {})
            else:
                # Search by name
                result = musicbrainzngs.search_artists(artist=artist_name, limit=5)
                artists = result.get("artist-list", [])

                if not artists:
                    logger.warning("artist_not_found", artist=artist_name)
                    return None

                # Find best match (exact name match preferred)
                artist_data = None
                for a in artists:
                    if a.get("name", "").lower() == artist_name.lower():
                        artist_data = a
                        break
                    # Check aliases
                    for alias in a.get("alias-list", []):
                        if alias.get("alias", "").lower() == artist_name.lower():
                            artist_data = a
                            break
                    if artist_data:
                        break

                if not artist_data:
                    # Use first result if no exact match
                    artist_data = artists[0]

        except musicbrainzngs.WebServiceError as e:
            logger.error("musicbrainz_error", error=str(e), artist=artist_name)
            return None

        # Extract data
        canonical_name = artist_data.get("name", artist_name)
        artist_mbid = artist_data.get("id")

        # Get aliases
        aliases = []
        for alias in artist_data.get("alias-list", []):
            alias_name = alias.get("alias")
            if alias_name and alias_name != canonical_name:
                aliases.append(alias_name)

        # Get genres/tags
        genres = []
        for tag in artist_data.get("tag-list", []):
            tag_name = tag.get("name")
            if tag_name:
                genres.append(tag_name)

        # Get country
        country = artist_data.get("country")

        # Get active years
        begin_area = artist_data.get("begin-area", {})
        life_span = artist_data.get("life-span", {})

        artist = Artist(
            name=canonical_name,
            aliases=aliases,
            musicbrainz_id=artist_mbid,
            spotify_id=None,  # Will be set by Spotify client
            metadata={
                "genres": genres,
                "country": country,
                "begin_year": life_span.get("begin"),
                "end_year": life_span.get("end"),
                "ended": life_span.get("ended", False),
                "type": artist_data.get("type"),  # Person, Group, etc.
                "origin_area": begin_area.get("name"),
            },
        )

        logger.info(
            "artist_canonicalized",
            original=artist_name,
            canonical=canonical_name,
            mbid=artist_mbid,
            genres=genres[:3],
        )

        # Cache result
        if self.cache:
            self.cache.set_artist_mapping(artist_name, artist)

        return artist

    def enrich_performance_metadata(
        self, artist_name: str, mbid: str | None = None
    ) -> dict:
        """Get artist metadata for enriching Performance records.
        
        Returns a dict suitable for merging into Performance.metadata.
        """
        artist = self.canonicalize_artist(artist_name, mbid)
        if not artist:
            return {}

        return {
            "artist_canonical": artist.name,
            "artist_mbid": artist.musicbrainz_id,
            "genres": artist.metadata.get("genres", []),
            "country": artist.metadata.get("country"),
            "artist_type": artist.metadata.get("type"),
        }
