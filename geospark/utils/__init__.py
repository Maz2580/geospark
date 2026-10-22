"""GeoSpark Utilities."""

from __future__ import annotations

import os
from pathlib import Path

from geospark import __version__

REPO_URL = "https://github.com/Maz2580/geospark"

# Identifies GeoSpark to public services (Nominatim, Overpass) as their usage policies require.
USER_AGENT = f"GeoSpark/{__version__} (+{REPO_URL})"


def data_dir() -> Path:
    """Root for all persistent state: audit, usage, memory, contexts, sessions, plugins.

    Set ``GEOSPARK_DATA_DIR`` to move everything at once (for example to a mounted Docker
    volume); defaults to ``~/.geospark``.
    """
    return Path(os.getenv("GEOSPARK_DATA_DIR") or Path.home() / ".geospark")
