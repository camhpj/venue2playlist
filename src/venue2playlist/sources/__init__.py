"""Data source interface and base classes.

All data sources must implement the DataSource protocol for modularity.
"""

from abc import ABC, abstractmethod
from datetime import date
from typing import Protocol, runtime_checkable

from ..models import Performance, VenueMatch


@runtime_checkable
class DataSource(Protocol):
    """Protocol for venue performance data sources.
    
    Implement this protocol to add new data sources (e.g., Internet Archive, Wikipedia).
    All sources must provide source attribution for every record.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this data source."""
        ...

    def search_venues(self, venue_name: str, city: str) -> list[VenueMatch]:
        """Search for venues matching the given name and city.
        
        Args:
            venue_name: Name of the venue to search for
            city: City where the venue is located
            
        Returns:
            List of matching venues with their IDs
        """
        ...

    def get_performances(
        self,
        venue_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[Performance]:
        """Get performances at a venue, optionally filtered by date range.
        
        Args:
            venue_id: Venue identifier from search_venues
            start_date: Optional start of date range
            end_date: Optional end of date range
            
        Returns:
            List of performances with source attribution
        """
        ...


class BaseDataSource(ABC):
    """Abstract base class for data sources with common functionality."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this data source."""
        pass

    @abstractmethod
    def search_venues(self, venue_name: str, city: str) -> list[VenueMatch]:
        """Search for venues matching the given name and city."""
        pass

    @abstractmethod
    def get_performances(
        self,
        venue_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[Performance]:
        """Get performances at a venue."""
        pass


class DataSourceRegistry:
    """Registry for managing multiple data sources."""

    def __init__(self):
        self._sources: dict[str, DataSource] = {}

    def register(self, source: DataSource) -> None:
        """Register a data source."""
        self._sources[source.name] = source

    def get(self, name: str) -> DataSource | None:
        """Get a data source by name."""
        return self._sources.get(name)

    def all(self) -> list[DataSource]:
        """Get all registered data sources."""
        return list(self._sources.values())

    @property
    def names(self) -> list[str]:
        """Get names of all registered sources."""
        return list(self._sources.keys())
