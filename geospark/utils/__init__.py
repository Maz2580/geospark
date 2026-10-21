"""GeoSpark Utilities."""

from __future__ import annotations

from geospark import __version__

REPO_URL = "https://github.com/Maz2580/geospark"

# Identifies GeoSpark to public services (Nominatim, Overpass) as their usage policies require.
USER_AGENT = f"GeoSpark/{__version__} (+{REPO_URL})"
