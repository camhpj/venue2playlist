"""Gemini LLM client for structured parsing.

The LLM is used ONLY for:
- Parsing provided text into structured JSON
- Normalizing names
- Assigning confidence scores

The LLM must NEVER:
- Decide who performed
- Infer missing dates
- Fill gaps with "likely" performers
- Merge conflicting claims without sources
"""

import json
from datetime import date

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from ..logging import get_logger
from ..models import Performance

logger = get_logger(__name__)


class ParsedPerformance(BaseModel):
    """LLM output schema for a parsed performance."""

    artist_name: str = Field(description="Artist or band name exactly as stated in the source")
    performance_date: str | None = Field(
        default=None, description="Performance date in YYYY-MM-DD format, if explicitly stated"
    )
    performance_date_approximate: bool = Field(
        default=False, description="True if the date is approximate or inferred from context"
    )
    date_range_start: str | None = Field(
        default=None, description="Start of date range in YYYY-MM-DD if exact date unknown"
    )
    date_range_end: str | None = Field(
        default=None, description="End of date range in YYYY-MM-DD if exact date unknown"
    )
    confidence_notes: str = Field(
        default="", description="Notes on confidence, e.g., source reliability, date precision"
    )


class ParsedPerformanceList(BaseModel):
    """LLM output schema for multiple parsed performances."""

    performances: list[ParsedPerformance]
    parsing_notes: str = Field(
        default="", description="General notes about the parsing, issues encountered, etc."
    )


class GeminiParser:
    """Gemini-based parser for extracting structured performance data from text.
    
    Uses structured output (JSON mode) to ensure LLM responses conform to schema.
    """

    SYSTEM_PROMPT = """You are a data extraction assistant. Your task is to extract performance records from provided text.

CRITICAL RULES:
1. Extract ONLY information that is EXPLICITLY stated in the text
2. NEVER infer, guess, or assume facts that are not stated
3. NEVER add artists or dates that are not mentioned
4. If a date is approximate (e.g., "around 1978", "early 1980"), set performance_date_approximate to true
5. If only a year or year range is given, use date_range_start and date_range_end
6. If information is ambiguous or unclear, note it in confidence_notes

You are extracting data to create a playlist. False positives (adding artists who didn't perform) are UNACCEPTABLE.
False negatives (missing some artists) are acceptable.

Respond with valid JSON matching the schema provided."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        """Initialize the Gemini parser.
        
        Args:
            api_key: Google Gemini API key
            model: Model to use (default: gemini-2.0-flash)
        """
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def parse_performances_from_text(
        self,
        text: str,
        venue_name: str,
        city: str,
        source_name: str,
        source_reference: str,
    ) -> list[Performance]:
        """Parse performance records from unstructured text.
        
        Args:
            text: Raw text to parse (from web page, document, etc.)
            venue_name: Name of the venue
            city: City where venue is located
            source_name: Name of the data source
            source_reference: URL or identifier for the source
            
        Returns:
            List of validated Performance records
        """
        logger.info(
            "parsing_text_with_llm",
            venue=venue_name,
            source=source_name,
            text_length=len(text),
        )

        prompt = f"""Extract all performance records from the following text about {venue_name} in {city}.

TEXT:
{text}

Extract each artist performance with dates. Remember:
- Only extract explicitly stated information
- Mark approximate dates appropriately
- Use date ranges for imprecise dates (e.g., "1978" becomes 1978-01-01 to 1978-12-31)"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=self.SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=ParsedPerformanceList,
                    temperature=0.1,  # Low temperature for deterministic output
                ),
            )

            # Parse response
            result_text = response.text
            parsed_data = ParsedPerformanceList.model_validate_json(result_text)

        except Exception as e:
            logger.error("llm_parsing_failed", error=str(e), venue=venue_name)
            return []

        # Convert to Performance records
        performances = []
        for parsed in parsed_data.performances:
            perf = self._to_performance(
                parsed,
                venue_name=venue_name,
                city=city,
                source_name=source_name,
                source_reference=source_reference,
            )
            if perf:
                performances.append(perf)

        logger.info(
            "llm_parsing_complete",
            venue=venue_name,
            extracted=len(performances),
            notes=parsed_data.parsing_notes[:100] if parsed_data.parsing_notes else None,
        )

        return performances

    def _to_performance(
        self,
        parsed: ParsedPerformance,
        venue_name: str,
        city: str,
        source_name: str,
        source_reference: str,
    ) -> Performance | None:
        """Convert parsed LLM output to a Performance record."""
        # Parse dates
        perf_date = None
        perf_range = None

        if parsed.performance_date:
            try:
                perf_date = date.fromisoformat(parsed.performance_date)
            except ValueError:
                logger.warning(
                    "invalid_date_format",
                    date=parsed.performance_date,
                    artist=parsed.artist_name,
                )

        if parsed.date_range_start and parsed.date_range_end:
            try:
                range_start = date.fromisoformat(parsed.date_range_start)
                range_end = date.fromisoformat(parsed.date_range_end)
                perf_range = (range_start, range_end)
            except ValueError:
                logger.warning(
                    "invalid_date_range",
                    start=parsed.date_range_start,
                    end=parsed.date_range_end,
                    artist=parsed.artist_name,
                )

        # Must have some temporal evidence
        if not perf_date and not perf_range:
            logger.warning(
                "skipping_no_date",
                artist=parsed.artist_name,
                venue=venue_name,
            )
            return None

        # Calculate confidence
        confidence = 1.0
        if parsed.performance_date_approximate:
            confidence = 0.7
        if perf_range and not perf_date:
            confidence = min(confidence, 0.8)
        if "LLM-parsed" in source_name or source_name.startswith("parsed:"):
            confidence = min(confidence, 0.9)

        return Performance(
            artist_name=parsed.artist_name,
            venue_name=venue_name,
            city=city,
            performance_date=perf_date,
            performance_date_range=perf_range,
            source_name=f"parsed:{source_name}",
            source_reference=source_reference,
            confidence_score=confidence,
            metadata={
                "confidence_notes": parsed.confidence_notes,
                "approximate_date": parsed.performance_date_approximate,
            },
        )
