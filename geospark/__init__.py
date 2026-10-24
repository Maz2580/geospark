"""
GeoSpark: The Open-Source Geospatial Intelligence Protocol & Engine.

Give any AI model a spatial mind. Open source. Run anywhere.
"""

__version__ = "0.9.0"

import os as _os
from pathlib import Path as _Path

# PROJ reads this once, when it starts: set it before anything imports pyproj, so the official
# transformation grids GeoSpark downloads (see geospark.geodesy) are cached under GeoSpark's data
# directory instead of the user's system folders.
_os.environ.setdefault(
    "PROJ_USER_WRITABLE_DIRECTORY",
    str(_Path(_os.getenv("GEOSPARK_DATA_DIR") or _Path.home() / ".geospark") / "proj"),
)
# PROJ never downloads by itself: its on-demand download works only on the thread that enabled it,
# and the API answers on worker threads. geospark.geodesy fetches whole official grid files instead.
_os.environ.setdefault("PROJ_NETWORK", "OFF")

from geospark.engine.core import Engine

__all__ = ["Engine", "__version__"]
