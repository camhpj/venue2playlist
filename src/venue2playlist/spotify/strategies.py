"""Track selection strategies for Spotify playlist creation.

Strategies:
- TopN: Artist's top N tracks by popularity
- RandomN: Random N tracks from artist's catalog
- EraWeighted: Prefer releases near performance date
- DeepCuts: Exclude highly popular tracks
"""

import random
from abc import ABC, abstractmethod
from datetime import date
from typing import Any, Protocol, runtime_checkable

from ..logging import get_logger
from ..models import Track

logger = get_logger(__name__)


@runtime_checkable
class TrackSelectionStrategy(Protocol):
    """Protocol for track selection strategies."""

    @property
    def name(self) -> str:
        """Strategy identifier."""
        ...

    def select_tracks(
        self,
        artist_id: str,
        artist_name: str,
        tracks: list[dict[str, Any]],
        performance_date: date | None = None,
        count: int = 3,
    ) -> list[Track]:
        """Select tracks for an artist.
        
        Args:
            artist_id: Spotify artist ID
            artist_name: Artist name for logging/metadata
            tracks: List of track data from Spotify API
            performance_date: Optional performance date for era-based selection
            count: Number of tracks to select
            
        Returns:
            List of selected Track objects
        """
        ...


class BaseStrategy(ABC):
    """Abstract base class for track selection strategies."""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def select_tracks(
        self,
        artist_id: str,
        artist_name: str,
        tracks: list[dict[str, Any]],
        performance_date: date | None = None,
        count: int = 3,
    ) -> list[Track]:
        pass

    def _track_to_model(
        self, track: dict[str, Any], reason: str
    ) -> Track:
        """Convert Spotify track data to Track model."""
        # Parse release date
        release_date_str = track.get("album", {}).get("release_date", "")
        release_date = None
        if release_date_str:
            try:
                # Handle YYYY, YYYY-MM, YYYY-MM-DD formats
                parts = release_date_str.split("-")
                if len(parts) >= 3:
                    release_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
                elif len(parts) == 2:
                    release_date = date(int(parts[0]), int(parts[1]), 1)
                elif len(parts) == 1 and parts[0].isdigit():
                    release_date = date(int(parts[0]), 1, 1)
            except (ValueError, IndexError):
                pass

        return Track(
            spotify_id=track["id"],
            name=track["name"],
            artist_name=track.get("artists", [{}])[0].get("name", "Unknown"),
            album_name=track.get("album", {}).get("name", "Unknown"),
            release_date=release_date,
            popularity=track.get("popularity", 0),
            selection_strategy=self.name,
            selection_reason=reason,
        )


class TopNStrategy(BaseStrategy):
    """Select artist's top N tracks by Spotify popularity."""

    @property
    def name(self) -> str:
        return "top_n"

    def select_tracks(
        self,
        artist_id: str,
        artist_name: str,
        tracks: list[dict[str, Any]],
        performance_date: date | None = None,
        count: int = 3,
    ) -> list[Track]:
        # Tracks should already be sorted by popularity from Spotify
        selected = tracks[:count]

        return [
            self._track_to_model(t, f"Top {i + 1} by popularity")
            for i, t in enumerate(selected)
        ]


class RandomNStrategy(BaseStrategy):
    """Select random N tracks from artist's catalog."""

    @property
    def name(self) -> str:
        return "random_n"

    def select_tracks(
        self,
        artist_id: str,
        artist_name: str,
        tracks: list[dict[str, Any]],
        performance_date: date | None = None,
        count: int = 3,
    ) -> list[Track]:
        if len(tracks) <= count:
            selected = tracks
        else:
            selected = random.sample(tracks, count)

        return [
            self._track_to_model(t, "Random selection from catalog")
            for t in selected
        ]


class EraWeightedStrategy(BaseStrategy):
    """Prefer releases near the performance date.
    
    Weights tracks by proximity to the performance date,
    with a fallback to popularity if no date available.
    """

    @property
    def name(self) -> str:
        return "era_weighted"

    def select_tracks(
        self,
        artist_id: str,
        artist_name: str,
        tracks: list[dict[str, Any]],
        performance_date: date | None = None,
        count: int = 3,
    ) -> list[Track]:
        if not performance_date:
            # Fall back to top N if no performance date
            logger.debug(
                "era_weighted_no_date",
                artist=artist_name,
                fallback="top_n",
            )
            return TopNStrategy().select_tracks(
                artist_id, artist_name, tracks, performance_date, count
            )

        # Score tracks by proximity to performance date
        scored_tracks = []
        for track in tracks:
            release_str = track.get("album", {}).get("release_date", "")
            score = self._calculate_era_score(release_str, performance_date)
            scored_tracks.append((score, track))

        # Sort by score (higher = closer to performance date)
        scored_tracks.sort(key=lambda x: x[0], reverse=True)

        selected = [t for _, t in scored_tracks[:count]]

        return [
            self._track_to_model(
                t,
                f"Era-weighted: released {t.get('album', {}).get('release_date', 'unknown')}",
            )
            for t in selected
        ]

    def _calculate_era_score(self, release_date_str: str, performance_date: date) -> float:
        """Calculate score based on proximity to performance date."""
        if not release_date_str:
            return 0.0

        try:
            parts = release_date_str.split("-")
            release_year = int(parts[0])
        except (ValueError, IndexError):
            return 0.0

        perf_year = performance_date.year
        years_diff = abs(release_year - perf_year)

        # Score: 100 for same year, decreasing by 10 per year difference
        # Cap at 0 (don't go negative)
        return max(0.0, 100.0 - (years_diff * 10))


class DeepCutsStrategy(BaseStrategy):
    """Exclude highly popular tracks, prefer lesser-known songs.
    
    Filters out tracks above a popularity threshold, then
    selects randomly or by release date from what remains.
    """

    def __init__(self, max_popularity: int = 60):
        """Initialize deep cuts strategy.
        
        Args:
            max_popularity: Maximum popularity score (0-100) to include
        """
        self.max_popularity = max_popularity

    @property
    def name(self) -> str:
        return f"deep_cuts(max_pop={self.max_popularity})"

    def select_tracks(
        self,
        artist_id: str,
        artist_name: str,
        tracks: list[dict[str, Any]],
        performance_date: date | None = None,
        count: int = 3,
    ) -> list[Track]:
        # Filter out popular tracks
        deep_cuts = [
            t for t in tracks
            if t.get("popularity", 0) <= self.max_popularity
        ]

        if not deep_cuts:
            logger.warning(
                "no_deep_cuts",
                artist=artist_name,
                max_popularity=self.max_popularity,
                fallback="least_popular",
            )
            # Fall back to least popular tracks
            sorted_tracks = sorted(tracks, key=lambda t: t.get("popularity", 0))
            deep_cuts = sorted_tracks[:count * 2]  # Take extra for variety

        # Select randomly from deep cuts
        if len(deep_cuts) <= count:
            selected = deep_cuts
        else:
            selected = random.sample(deep_cuts, count)

        return [
            self._track_to_model(
                t,
                f"Deep cut: popularity {t.get('popularity', 'unknown')}",
            )
            for t in selected
        ]


def get_strategy(name: str, **kwargs) -> TrackSelectionStrategy:
    """Get a track selection strategy by name.
    
    Args:
        name: Strategy name (top_n, random_n, era_weighted, deep_cuts, or top-N format)
        **kwargs: Additional arguments for strategy initialization
        
    Returns:
        Configured strategy instance
    """
    # Handle "top-3", "random-5" format
    if "-" in name:
        parts = name.split("-")
        strategy_name = parts[0].lower()
        # The number is used as count in select_tracks, not here
    else:
        strategy_name = name.lower()

    strategies = {
        "top": TopNStrategy,
        "top_n": TopNStrategy,
        "random": RandomNStrategy,
        "random_n": RandomNStrategy,
        "era": EraWeightedStrategy,
        "era_weighted": EraWeightedStrategy,
        "deep": DeepCutsStrategy,
        "deep_cuts": DeepCutsStrategy,
    }

    strategy_class = strategies.get(strategy_name)
    if not strategy_class:
        logger.warning("unknown_strategy", name=name, fallback="top_n")
        return TopNStrategy()

    if strategy_class == DeepCutsStrategy:
        return strategy_class(max_popularity=kwargs.get("max_popularity", 60))

    return strategy_class()
