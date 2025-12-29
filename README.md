# venue2playlist

Create Spotify playlists from historic venue performances.

A deterministic, source-driven CLI tool that creates Spotify playlists based on **documented historic performances at music venues**. Prioritizes correctness over completeness with full source attribution.

## Installation

```bash
# Using uv (recommended)
uv sync

# Or with pip
pip install -e .
```

## Configuration

Create a `.env` file with your API keys:

```bash
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
GEMINI_API_KEY=your_gemini_api_key
SETLIST_FM_API_KEY=your_setlist_fm_api_key
```

## Usage

### Create a Playlist

```bash
venue2playlist create \
  --venue "CBGB" \
  --city "New York" \
  --start-date 1978-01-01 \
  --end-date 1980-12-31 \
  --strategy top-3 \
  --playlist-name "CBGB 78-80"
```

### Track Selection Strategies

- `top-N` - Artist's top N tracks by popularity (e.g., `top-3`)
- `random-N` - Random N tracks from catalog
- `era-N` - Prefer releases near performance date
- `deep-N` - Exclude highly popular tracks (deep cuts)

### Search for a Venue

```bash
venue2playlist search-venue --venue "CBGB" --city "New York"
```

### Clear Cache

```bash
venue2playlist clear-cache
```

## Architecture

```
venue2playlist/
├── cli.py           # Typer CLI
├── pipeline.py      # Orchestration
├── config.py        # Settings (pydantic-settings)
├── models.py        # Pydantic schemas
├── cache.py         # SQLite caching
├── sources/         # Data sources (modular)
│   ├── setlist_fm.py
│   └── musicbrainz.py
├── filters/         # Extensible filters
│   ├── date_range.py
│   ├── confidence.py
│   └── field.py     # Generic metadata filter
├── parser/
│   └── llm.py       # Gemini structured parsing
└── spotify/
    ├── client.py    # Spotify API
    └── strategies.py
```

## Extensibility

### Adding Data Sources

Implement the `DataSource` protocol:

```python
from venue2playlist.sources import DataSource, DataSourceRegistry

class MySource(DataSource):
    @property
    def name(self) -> str:
        return "my_source"
    
    def search_venues(self, venue_name: str, city: str) -> list[VenueMatch]:
        ...
    
    def get_performances(self, venue_id: str, ...) -> list[Performance]:
        ...

# Register
registry = DataSourceRegistry()
registry.register(MySource())
```

### Adding Filters

Use `FieldFilter` for metadata-based filtering:

```python
from venue2playlist.filters import FieldFilter, FilterChain

# Filter by genre
genre_filter = FieldFilter("genre", {"punk", "rock", "new wave"})

# Filter by country
country_filter = FieldFilter("country", {"US", "UK"})

# Compose filters
chain = FilterChain().add(genre_filter).add(country_filter)
result = chain.apply(performances)
```
