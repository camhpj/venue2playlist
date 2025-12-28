"""venue2playlist - Create Spotify playlists from historic venue performances.

A deterministic, source-driven CLI tool that creates Spotify playlists
based on documented historic performances at music venues.
"""

from .cli import main

__all__ = ["main"]
