"""venue2playlist CLI using Typer.

Commands:
- create: Create a playlist from a venue's performance history
"""

from datetime import date
from pathlib import Path
from typing import Annotated, Optional

import typer

from .config import get_settings
from .logging import configure_logging, get_logger
from .pipeline import Pipeline

app = typer.Typer(
    name="venue2playlist",
    help="Create Spotify playlists from historic venue performances.",
    add_completion=False,
)


def parse_date(value: str) -> date:
    """Parse a date string in YYYY-MM-DD format."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter(f"Invalid date format: {value}. Use YYYY-MM-DD.")


@app.command()
def create(
    venue: Annotated[str, typer.Option("--venue", "-v", help="Name of the venue")],
    city: Annotated[str, typer.Option("--city", "-c", help="City where the venue is located")],
    start_date: Annotated[str, typer.Option("--start-date", "-s", help="Start date (YYYY-MM-DD)")],
    end_date: Annotated[str, typer.Option("--end-date", "-e", help="End date (YYYY-MM-DD)")],
    playlist_name: Annotated[str, typer.Option("--playlist-name", "-n", help="Name for the Spotify playlist")],
    strategy: Annotated[str, typer.Option("--strategy", "-t", help="Track selection strategy (top-N, random-N, era-N, deep-N)")] = "top-3",
    min_confidence: Annotated[float, typer.Option("--min-confidence", help="Minimum confidence score (0.0-1.0)")] = 0.5,
    output_json: Annotated[Optional[Path], typer.Option("--output", "-o", help="Output JSON file for results")] = None,
    log_level: Annotated[str, typer.Option("--log-level", help="Log level (DEBUG, INFO, WARNING, ERROR)")] = "INFO",
    log_format: Annotated[str, typer.Option("--log-format", help="Log format (console, json)")] = "console",
) -> None:
    """Create a Spotify playlist from a venue's performance history.
    
    Example:
        venue2playlist create --venue "CBGB" --city "New York" \\
            --start-date 1978-01-01 --end-date 1980-12-31 \\
            --strategy top-3 --playlist-name "CBGB 78-80"
    """
    # Configure logging
    configure_logging(level=log_level, format=log_format)
    logger = get_logger(__name__)

    # Parse dates
    try:
        start = parse_date(start_date)
        end = parse_date(end_date)
    except typer.BadParameter as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    if start > end:
        typer.echo("Error: start-date must be before end-date", err=True)
        raise typer.Exit(1)

    typer.echo(f"Creating playlist '{playlist_name}' for {venue} ({city})")
    typer.echo(f"Date range: {start} to {end}")
    typer.echo(f"Strategy: {strategy}")
    typer.echo()

    # Run pipeline
    try:
        pipeline = Pipeline()
        result = pipeline.run(
            venue_name=venue,
            city=city,
            start_date=start,
            end_date=end,
            strategy=strategy,
            playlist_name=playlist_name,
            min_confidence=min_confidence,
        )
    except ValueError as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        logger.exception("pipeline_failed", error=str(e))
        typer.echo(f"Error: Pipeline failed - {e}", err=True)
        raise typer.Exit(1)

    # Output summary
    typer.echo()
    typer.echo("=" * 60)
    typer.echo("PLAYLIST CREATED SUCCESSFULLY")
    typer.echo("=" * 60)
    typer.echo()
    typer.echo(f"Playlist: {result.playlist_name}")
    typer.echo(f"URL: {result.playlist_url}")
    typer.echo(f"Artists: {result.total_artists}")
    typer.echo(f"Tracks: {len(result.tracks)}")
    typer.echo()

    # Data sources used
    typer.echo("Data Sources:")
    for source in result.sources_used:
        typer.echo(f"  - {source}")
    typer.echo()

    # Excluded items summary
    if result.excluded_items:
        typer.echo(f"Excluded Items: {len(result.excluded_items)}")
        # Group by reason
        reasons: dict[str, int] = {}
        for item in result.excluded_items:
            key = item.reason.split(":")[0] if ":" in item.reason else item.reason[:50]
            reasons[key] = reasons.get(key, 0) + 1
        for reason, count in sorted(reasons.items(), key=lambda x: -x[1])[:5]:
            typer.echo(f"  - {reason}: {count}")
        if len(reasons) > 5:
            typer.echo(f"  ... and {len(reasons) - 5} more reasons")
    typer.echo()

    # Output JSON if requested
    if output_json:
        import json
        output_json.write_text(result.model_dump_json(indent=2))
        typer.echo(f"Results written to: {output_json}")

    typer.echo("Done!")


@app.command()
def search_venue(
    venue: Annotated[str, typer.Option("--venue", "-v", help="Name of the venue")],
    city: Annotated[str, typer.Option("--city", "-c", help="City where the venue is located")],
) -> None:
    """Search for a venue across data sources.
    
    Useful for finding the correct venue ID before creating a playlist.
    """
    configure_logging(level="WARNING")

    pipeline = Pipeline()
    venues = pipeline.search_venues(venue, city)

    if not venues:
        typer.echo(f"No venues found matching '{venue}' in {city}")
        raise typer.Exit(1)

    typer.echo(f"Found {len(venues)} venue(s):")
    typer.echo()
    
    for i, v in enumerate(venues, 1):
        typer.echo(f"{i}. {v.venue_name}")
        typer.echo(f"   City: {v.city}")
        if v.country:
            typer.echo(f"   Country: {v.country}")
        typer.echo(f"   Source: {v.source_name}")
        typer.echo(f"   ID: {v.venue_id}")
        typer.echo()


@app.command()
def clear_cache() -> None:
    """Clear the local cache."""
    from .cache import Cache
    
    settings = get_settings()
    cache = Cache(settings.cache_path)
    
    cache.clear_all()
    typer.echo("Cache cleared.")


def main() -> None:
    """CLI entry point."""
    app()
