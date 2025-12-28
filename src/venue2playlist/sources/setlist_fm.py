"""Setlist.fm data source implementation.

Primary source for structured concert data.
API documentation: https://api.setlist.fm/docs/1.0/index.html
"""

from datetime import date, datetime

import httpx

from ..cache import Cache
from ..logging import get_logger
from ..models import Performance, VenueMatch
from . import BaseDataSource

logger = get_logger(__name__)


class SetlistFmSource(BaseDataSource):
    """Setlist.fm API data source.
    
    Provides structured concert setlist data with dates, venues, and artists.
    """

    BASE_URL = "https://api.setlist.fm/rest/1.0"

    def __init__(self, api_key: str, cache: Cache | None = None):
        """Initialize the Setlist.fm source.
        
        Args:
            api_key: Setlist.fm API key
            cache: Optional cache instance for caching results
        """
        self.api_key = api_key
        self.cache = cache
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/json",
                "x-api-key": api_key,
            },
            timeout=30.0,
        )

    @property
    def name(self) -> str:
        return "setlist.fm"

    def _parse_date(self, date_str: str) -> date | None:
        """Parse setlist.fm date format (dd-MM-yyyy)."""
        try:
            return datetime.strptime(date_str, "%d-%m-%Y").date()
        except (ValueError, TypeError):
            logger.warning("failed_to_parse_date", date_str=date_str)
            return None

    def search_venues(self, venue_name: str, city: str) -> list[VenueMatch]:
        """Search for venues by name and city."""
        # Check cache first
        if self.cache:
            cached = self.cache.get_venue_search(venue_name, city, self.name)
            if cached:
                logger.info("venue_search_cache_hit", venue=venue_name, city=city)
                return cached

        logger.info("searching_venues", venue=venue_name, city=city, source=self.name)

        try:
            response = self._client.get(
                "/search/venues",
                params={"name": venue_name, "cityName": city, "p": 1},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as e:
            logger.error("venue_search_failed", error=str(e), venue=venue_name, city=city)
            return []

        venues = data.get("venue", [])
        results = []

        for venue in venues:
            city_data = venue.get("city", {})
            country_data = city_data.get("country", {})

            match = VenueMatch(
                venue_id=venue.get("id", ""),
                venue_name=venue.get("name", ""),
                city=city_data.get("name", ""),
                country=country_data.get("code"),
                source_name=self.name,
                metadata={
                    "state": city_data.get("state"),
                    "state_code": city_data.get("stateCode"),
                    "coords": city_data.get("coords"),
                },
            )
            results.append(match)

        logger.info("venue_search_complete", venue=venue_name, city=city, results=len(results))

        # Cache results
        if self.cache and results:
            self.cache.set_venue_search(venue_name, city, self.name, results)

        return results

    def get_performances(
        self,
        venue_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[Performance]:
        """Get performances at a venue, optionally filtered by date range.
        
        Note: Setlist.fm API doesn't support date range filtering directly,
        so we fetch all and filter client-side.
        """
        # Check cache first
        start_str = start_date.isoformat() if start_date else None
        end_str = end_date.isoformat() if end_date else None

        if self.cache:
            cached = self.cache.get_performances(venue_id, self.name, start_str, end_str)
            if cached:
                logger.info("performances_cache_hit", venue_id=venue_id)
                return cached

        logger.info(
            "fetching_performances",
            venue_id=venue_id,
            start_date=start_str,
            end_date=end_str,
            source=self.name,
        )

        all_setlists = []
        page = 1
        total_pages = 1

        while page <= total_pages:
            try:
                response = self._client.get(
                    f"/venue/{venue_id}/setlists",
                    params={"p": page},
                )
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPError as e:
                logger.error("performances_fetch_failed", error=str(e), venue_id=venue_id, page=page)
                break

            setlists = data.get("setlist", [])
            all_setlists.extend(setlists)

            # Handle pagination
            items_per_page = data.get("itemsPerPage", 20)
            total = data.get("total", 0)
            total_pages = (total + items_per_page - 1) // items_per_page if items_per_page > 0 else 1

            logger.debug("fetched_page", page=page, total_pages=total_pages, count=len(setlists))
            page += 1

            # Rate limiting: setlist.fm allows 2 requests/second
            # The httpx client handles this reasonably, but we could add explicit delays

        # Convert to Performance records
        performances = []
        for setlist in all_setlists:
            perf = self._setlist_to_performance(setlist)
            if perf:
                # Apply date filter if specified
                if start_date and end_date:
                    if perf.overlaps_range(start_date, end_date):
                        performances.append(perf)
                else:
                    performances.append(perf)

        logger.info(
            "performances_fetch_complete",
            venue_id=venue_id,
            total_fetched=len(all_setlists),
            after_filter=len(performances),
        )

        # Cache results
        if self.cache and performances:
            self.cache.set_performances(venue_id, self.name, performances, start_str, end_str)

        return performances

    def _setlist_to_performance(self, setlist: dict) -> Performance | None:
        """Convert a setlist.fm setlist to a Performance record."""
        artist = setlist.get("artist", {})
        venue = setlist.get("venue", {})
        venue_city = venue.get("city", {})
        venue_country = venue_city.get("country", {})

        event_date = self._parse_date(setlist.get("eventDate", ""))
        if not event_date:
            logger.warning(
                "skipping_setlist_no_date",
                setlist_id=setlist.get("id"),
                artist=artist.get("name"),
            )
            return None

        # Build source reference URL
        setlist_url = setlist.get("url", f"https://www.setlist.fm/setlist/{setlist.get('id', '')}")

        return Performance(
            artist_name=artist.get("name", "Unknown Artist"),
            venue_name=venue.get("name", "Unknown Venue"),
            city=venue_city.get("name", ""),
            country=venue_country.get("code"),
            performance_date=event_date,
            performance_date_range=None,
            source_name=self.name,
            source_reference=setlist_url,
            confidence_score=1.0,  # Setlist.fm has exact dates
            metadata={
                "setlist_id": setlist.get("id"),
                "artist_mbid": artist.get("mbid"),
                "tour_name": setlist.get("tour", {}).get("name"),
            },
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "SetlistFmSource":
        return self

    def __exit__(self, *args) -> None:
        self.close()
