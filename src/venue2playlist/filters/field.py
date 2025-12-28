"""Generic field filter for extensible filtering on metadata fields."""

from typing import Any

from ..models import ExcludedItem, Performance
from . import BaseFilter, FilterResult


class FieldFilter(BaseFilter):
    """Generic filter on any structured metadata field.
    
    This filter enables extensible filtering without code changes.
    Simply ensure your data source populates the metadata field,
    then create a FieldFilter for it.
    
    Examples:
        # Filter by genre
        FieldFilter("genre", {"punk", "rock", "new wave"})
        
        # Filter by country
        FieldFilter("country", {"US", "UK"})
        
        # Filter by decade
        FieldFilter("decade", {"1970s", "1980s"})
    """

    def __init__(
        self,
        field: str,
        allowed_values: set[Any],
        *,
        case_insensitive: bool = True,
        include_missing: bool = False,
    ):
        """Initialize the field filter.
        
        Args:
            field: Metadata field name to filter on (e.g., "genre", "country")
            allowed_values: Set of allowed values for the field
            case_insensitive: If True, compare string values case-insensitively
            include_missing: If True, include items where the field is missing
        """
        self.field = field
        self.allowed_values = allowed_values
        self.case_insensitive = case_insensitive
        self.include_missing = include_missing

        # Pre-normalize allowed values for case-insensitive comparison
        if case_insensitive:
            self._normalized_allowed = {
                v.lower() if isinstance(v, str) else v for v in allowed_values
            }
        else:
            self._normalized_allowed = allowed_values

    @property
    def name(self) -> str:
        values_str = ",".join(str(v) for v in sorted(self.allowed_values, key=str))
        return f"field({self.field}={{{values_str}}})"

    def _normalize_value(self, value: Any) -> Any:
        """Normalize a value for comparison."""
        if self.case_insensitive and isinstance(value, str):
            return value.lower()
        return value

    def _matches(self, value: Any) -> bool:
        """Check if a value matches the allowed values."""
        normalized = self._normalize_value(value)

        # Handle list values (e.g., multiple genres)
        if isinstance(value, list):
            return any(self._normalize_value(v) in self._normalized_allowed for v in value)

        return normalized in self._normalized_allowed

    def apply(self, performances: list[Performance]) -> FilterResult:
        included: list[Performance] = []
        excluded: list[ExcludedItem] = []

        for perf in performances:
            field_value = perf.metadata.get(self.field)

            if field_value is None:
                if self.include_missing:
                    included.append(perf)
                else:
                    excluded.append(
                        ExcludedItem(
                            item_type="performance",
                            name=f"{perf.artist_name} @ {perf.venue_name}",
                            reason=f"Missing metadata field '{self.field}'",
                            filter_name=self.name,
                        )
                    )
            elif self._matches(field_value):
                included.append(perf)
            else:
                excluded.append(
                    ExcludedItem(
                        item_type="performance",
                        name=f"{perf.artist_name} @ {perf.venue_name}",
                        reason=f"Field '{self.field}' value '{field_value}' not in allowed values",
                        filter_name=self.name,
                    )
                )

        return FilterResult(included=included, excluded=excluded)
