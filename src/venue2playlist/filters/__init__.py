"""Extensible filter system for venue2playlist.

Filters operate on structured Performance/Artist data.
Add new filters by implementing the Filter protocol.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..models import ExcludedItem, Performance


@dataclass
class FilterResult:
    """Result of applying a filter."""

    included: list[Performance] = field(default_factory=list)
    excluded: list[ExcludedItem] = field(default_factory=list)


@runtime_checkable
class Filter(Protocol):
    """Protocol for performance filters.
    
    All filters operate on structured Performance data and return
    included items plus excluded items with reasons.
    """

    @property
    def name(self) -> str:
        """Unique identifier for this filter."""
        ...

    def apply(self, performances: list[Performance]) -> FilterResult:
        """Apply the filter to a list of performances.
        
        Args:
            performances: List of performances to filter
            
        Returns:
            FilterResult with included and excluded items
        """
        ...


class BaseFilter(ABC):
    """Abstract base class for filters with common functionality."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this filter."""
        pass

    @abstractmethod
    def apply(self, performances: list[Performance]) -> FilterResult:
        """Apply the filter to performances."""
        pass


class FilterChain:
    """Chain of filters applied sequentially.
    
    Each filter receives the included items from the previous filter.
    Excluded items accumulate across all filters.
    """

    def __init__(self):
        self._filters: list[Filter] = []

    def add(self, filter: Filter) -> "FilterChain":
        """Add a filter to the chain. Returns self for chaining."""
        self._filters.append(filter)
        return self

    def apply(self, performances: list[Performance]) -> FilterResult:
        """Apply all filters in sequence."""
        current = performances
        all_excluded: list[ExcludedItem] = []

        for filter in self._filters:
            result = filter.apply(current)
            current = result.included
            all_excluded.extend(result.excluded)

        return FilterResult(included=current, excluded=all_excluded)

    @property
    def filters(self) -> list[Filter]:
        """Get all filters in the chain."""
        return self._filters.copy()


# Re-export filter implementations
from .confidence import ConfidenceFilter
from .date_range import DateRangeFilter
from .field import FieldFilter

__all__ = [
    "Filter",
    "FilterResult",
    "BaseFilter",
    "FilterChain",
    "ConfidenceFilter",
    "DateRangeFilter",
    "FieldFilter",
]
