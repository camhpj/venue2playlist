"""Spotify API client for playlist creation.

Handles:
- OAuth authentication with token caching
- Artist search and matching
- Track retrieval
- Playlist creation and management
"""

from datetime import date
from pathlib import Path
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from ..cache import Cache
from ..logging import get_logger
from ..models import Artist, ExcludedItem, Track

logger = get_logger(__name__)


class SpotifyClient:
    """Spotify API client for venue2playlist.
    
    Wraps spotipy with caching and structured logging.
    """

    SCOPE = "playlist-modify-public playlist-modify-private"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str = "http://localhost:8888/callback",
        cache_path: Path | None = None,
        cache: Cache | None = None,
    ):
        """Initialize the Spotify client.
        
        Args:
            client_id: Spotify application client ID
            client_secret: Spotify application client secret
            redirect_uri: OAuth redirect URI
            cache_path: Path for token cache file
            cache: Optional data cache for artist/track lookups
        """
        self.cache = cache

        # Set up OAuth
        auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=self.SCOPE,
            cache_path=str(cache_path) if cache_path else None,
            open_browser=True,
        )

        self._client = spotipy.Spotify(auth_manager=auth_manager)
        self._user_id: str | None = None

        logger.info("spotify_client_initialized")

    @property
    def user_id(self) -> str:
        """Get the current user's Spotify ID."""
        if not self._user_id:
            user = self._client.current_user()
            self._user_id = user["id"]
            logger.info("spotify_user_authenticated", user_id=self._user_id)
        return self._user_id

    def search_artist(self, artist_name: str) -> Artist | None:
        """Search for an artist on Spotify.
        
        Args:
            artist_name: Artist name to search
            
        Returns:
            Artist with Spotify ID, or None if not found
        """
        # Check cache first
        if self.cache:
            cached = self.cache.get_artist_mapping(artist_name)
            if cached and cached.spotify_id:
                logger.debug("artist_cache_hit", artist=artist_name)
                return cached

        logger.info("searching_artist", artist=artist_name)

        try:
            results = self._client.search(q=f'artist:"{artist_name}"', type="artist", limit=5)
            artists = results.get("artists", {}).get("items", [])

            if not artists:
                logger.warning("artist_not_found", artist=artist_name)
                return None

            # Find best match
            best_match = None
            for artist in artists:
                if artist["name"].lower() == artist_name.lower():
                    best_match = artist
                    break

            if not best_match:
                # Use first result
                best_match = artists[0]
                logger.debug(
                    "artist_fuzzy_match",
                    query=artist_name,
                    matched=best_match["name"],
                )

            artist = Artist(
                name=best_match["name"],
                spotify_id=best_match["id"],
                metadata={
                    "genres": best_match.get("genres", []),
                    "popularity": best_match.get("popularity"),
                    "followers": best_match.get("followers", {}).get("total"),
                    "image_url": (
                        best_match.get("images", [{}])[0].get("url")
                        if best_match.get("images")
                        else None
                    ),
                },
            )

            # Update cache
            if self.cache:
                self.cache.set_artist_mapping(artist_name, artist)

            return artist

        except spotipy.SpotifyException as e:
            logger.error("artist_search_failed", error=str(e), artist=artist_name)
            return None

    def get_artist_top_tracks(
        self, artist_id: str, market: str = "US"
    ) -> list[dict[str, Any]]:
        """Get an artist's top tracks.
        
        Args:
            artist_id: Spotify artist ID
            market: Market for track availability
            
        Returns:
            List of track data dicts
        """
        try:
            results = self._client.artist_top_tracks(artist_id, country=market)
            return results.get("tracks", [])
        except spotipy.SpotifyException as e:
            logger.error("top_tracks_failed", error=str(e), artist_id=artist_id)
            return []

    def get_artist_albums(
        self, artist_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get an artist's albums.
        
        Args:
            artist_id: Spotify artist ID
            limit: Maximum albums to fetch
            
        Returns:
            List of album data dicts
        """
        try:
            results = self._client.artist_albums(
                artist_id,
                album_type="album,single",
                limit=limit,
            )
            return results.get("items", [])
        except spotipy.SpotifyException as e:
            logger.error("albums_failed", error=str(e), artist_id=artist_id)
            return []

    def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        """Get tracks from an album.
        
        Args:
            album_id: Spotify album ID
            
        Returns:
            List of track data dicts
        """
        try:
            results = self._client.album_tracks(album_id)
            return results.get("items", [])
        except spotipy.SpotifyException as e:
            logger.error("album_tracks_failed", error=str(e), album_id=album_id)
            return []

    def get_artist_catalog(
        self, artist_id: str, max_albums: int = 10
    ) -> list[dict[str, Any]]:
        """Get a broader selection of an artist's tracks.
        
        Fetches tracks from multiple albums for strategies like random_n.
        
        Args:
            artist_id: Spotify artist ID
            max_albums: Maximum albums to sample from
            
        Returns:
            List of track data dicts with album info
        """
        albums = self.get_artist_albums(artist_id, limit=max_albums)
        all_tracks = []

        for album in albums:
            tracks = self.get_album_tracks(album["id"])
            # Enhance track data with album info
            for track in tracks:
                track["album"] = album
            all_tracks.extend(tracks)

        return all_tracks

    def create_playlist(
        self,
        name: str,
        description: str = "",
        public: bool = True,
    ) -> dict[str, Any]:
        """Create a new playlist.
        
        Args:
            name: Playlist name
            description: Playlist description
            public: Whether the playlist is public
            
        Returns:
            Playlist data dict with id and url
        """
        logger.info("creating_playlist", name=name, public=public)

        try:
            playlist = self._client.user_playlist_create(
                user=self.user_id,
                name=name,
                public=public,
                description=description,
            )

            logger.info(
                "playlist_created",
                name=name,
                id=playlist["id"],
                url=playlist["external_urls"]["spotify"],
            )

            return playlist
        except spotipy.SpotifyException as e:
            logger.error("playlist_creation_failed", error=str(e), name=name)
            raise

    def add_tracks_to_playlist(
        self, playlist_id: str, track_ids: list[str]
    ) -> int:
        """Add tracks to a playlist in batches.
        
        Spotify API limits to 100 tracks per request.
        
        Args:
            playlist_id: Spotify playlist ID
            track_ids: List of Spotify track IDs
            
        Returns:
            Number of tracks successfully added
        """
        if not track_ids:
            return 0

        # Convert to URIs
        uris = [f"spotify:track:{tid}" for tid in track_ids]

        added = 0
        batch_size = 100

        for i in range(0, len(uris), batch_size):
            batch = uris[i : i + batch_size]
            try:
                self._client.playlist_add_items(playlist_id, batch)
                added += len(batch)
                logger.debug(
                    "tracks_added_batch",
                    playlist_id=playlist_id,
                    batch_num=i // batch_size + 1,
                    count=len(batch),
                )
            except spotipy.SpotifyException as e:
                logger.error(
                    "add_tracks_failed",
                    error=str(e),
                    playlist_id=playlist_id,
                    batch_num=i // batch_size + 1,
                )

        logger.info(
            "tracks_added",
            playlist_id=playlist_id,
            total=added,
        )

        return added

    def get_tracks_for_artist(
        self,
        artist_name: str,
        strategy_name: str,
        performance_date: date | None = None,
    ) -> tuple[list[Track], list[ExcludedItem]]:
        """Get tracks for an artist using the specified strategy.
        
        This is the main method used by the pipeline.
        
        Args:
            artist_name: Artist name to search
            strategy_name: Track selection strategy (e.g., "top-3")
            performance_date: Optional performance date for era-based selection
            
        Returns:
            Tuple of (selected tracks, excluded items)
        """
        from .strategies import get_strategy

        # Parse count from strategy name (e.g., "top-3" -> 3)
        count = 3
        if "-" in strategy_name:
            try:
                count = int(strategy_name.split("-")[1])
            except (ValueError, IndexError):
                pass

        strategy = get_strategy(strategy_name)
        excluded: list[ExcludedItem] = []

        # Search for artist
        artist = self.search_artist(artist_name)
        if not artist or not artist.spotify_id:
            excluded.append(
                ExcludedItem(
                    item_type="artist",
                    name=artist_name,
                    reason="Artist not found on Spotify",
                    filter_name=None,
                )
            )
            return [], excluded

        # Get tracks based on strategy
        if "era" in strategy_name.lower() or "random" in strategy_name.lower():
            # These strategies need full catalog
            tracks = self.get_artist_catalog(artist.spotify_id)
        else:
            # Use top tracks for efficiency
            tracks = self.get_artist_top_tracks(artist.spotify_id)

        if not tracks:
            excluded.append(
                ExcludedItem(
                    item_type="artist",
                    name=artist_name,
                    reason="No tracks available on Spotify",
                    filter_name=None,
                )
            )
            return [], excluded

        # Select tracks using strategy
        selected = strategy.select_tracks(
            artist_id=artist.spotify_id,
            artist_name=artist.name,
            tracks=tracks,
            performance_date=performance_date,
            count=count,
        )

        logger.info(
            "tracks_selected",
            artist=artist_name,
            strategy=strategy_name,
            count=len(selected),
        )

        return selected, excluded
