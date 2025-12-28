"""Date range filter for performances."""

from datetime import date

from ..models import ExcludedItem, Performance
from . import BaseFilter, FilterResult


class DateRangeFilter(BaseFilter):
    """Filter performances by date range.
    
    Includes performances if:
    - The performance date falls within the range, OR
    - The documented date range overlaps with the requested range
    
    Excludes performances without temporal evidence.
    """

    def __init__(self, start_date: date, end_date: date):
        """Initialize the date range filter.
        
        Args:
            start_date: Start of the date range (inclusive)
            end_date: End of the date range (inclusive)
        """
        self.start_date = start_date
        self.end_date = end_date

    @property
    def name(self) -> str:
        return f"date_range({self.start_date}:{self.end_date})"

    def apply(self, performances: list[Performance]) -> FilterResult:
        included: list[Performance] = []
        excluded: list[ExcludedItem] = []

        for perf in performances:
            if not perf.has_valid_date():
                excluded.append(
                    ExcludedItem(
                        item_type="performance",
                        name=f"{perf.artist_name} @ {perf.venue_name}",
                        reason="No temporal evidence (missing date)",
                        filter_name=self.name,
                    )
                )
            elif perf.overlaps_range(self.start_date, self.end_date):
                included.append(perf)
            else:
                date_str = str(perf.performance_date or perf.performance_date_range)
                excluded.append(
                    ExcludedItem(
                        item_type="performance",
                        name=f"{perf.artist_name} @ {perf.venue_name}",
                        reason=f"Date {date_str} outside range {self.start_date} to {self.end_date}",
                        filter_name=self.name,
                    )
                )

        return FilterResult(included=included, excluded=excluded)
