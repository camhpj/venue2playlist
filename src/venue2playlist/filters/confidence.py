"""Confidence threshold filter for performances."""

from ..models import ExcludedItem, Performance
from . import BaseFilter, FilterResult


class ConfidenceFilter(BaseFilter):
    """Filter performances below a confidence threshold.
    
    Excludes performances where the confidence score is below
    the specified minimum threshold.
    """

    def __init__(self, min_confidence: float = 0.5):
        """Initialize the confidence filter.
        
        Args:
            min_confidence: Minimum confidence score (0.0-1.0)
        """
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0.0 and 1.0")
        self.min_confidence = min_confidence

    @property
    def name(self) -> str:
        return f"confidence(>={self.min_confidence})"

    def apply(self, performances: list[Performance]) -> FilterResult:
        included: list[Performance] = []
        excluded: list[ExcludedItem] = []

        for perf in performances:
            if perf.confidence_score >= self.min_confidence:
                included.append(perf)
            else:
                excluded.append(
                    ExcludedItem(
                        item_type="performance",
                        name=f"{perf.artist_name} @ {perf.venue_name}",
                        reason=f"Confidence {perf.confidence_score:.2f} below threshold {self.min_confidence}",
                        filter_name=self.name,
                    )
                )

        return FilterResult(included=included, excluded=excluded)
