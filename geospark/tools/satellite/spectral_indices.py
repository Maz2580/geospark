"""
Spectral Indices Tool.

Calculates multiple vegetation, water, and urban spectral indices
from satellite imagery bands.
"""

from __future__ import annotations

from typing import Any

import httpx

from geospark.protocol.schema import (
    SpatialQuery,
    SpatialResult,
    SpatialContext,
    SpatialFeature,
    SpatialOperation,
)
from geospark.tools.base import BaseTool


# Index definitions: formula, description, and required bands
SPECTRAL_INDEX_FORMULAS: dict[str, dict[str, Any]] = {
    "ndvi": {
        "name": "Normalized Difference Vegetation Index",
        "formula": "(NIR - Red) / (NIR + Red)",
        "bands": {"nir": "B08", "red": "B04"},
        "range": [-1.0, 1.0],
        "description": "Vegetation health and density. >0.3 = healthy vegetation.",
    },
    "evi": {
        "name": "Enhanced Vegetation Index",
        "formula": "2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)",
        "bands": {"nir": "B08", "red": "B04", "blue": "B02"},
        "range": [-1.0, 1.0],
        "description": "Improved vegetation index, corrects for atmospheric and soil effects.",
    },
    "savi": {
        "name": "Soil-Adjusted Vegetation Index",
        "formula": "((NIR - Red) / (NIR + Red + L)) * (1 + L), L=0.5",
        "bands": {"nir": "B08", "red": "B04"},
        "range": [-1.0, 1.0],
        "description": "Vegetation index adjusted for soil brightness. Use in sparse vegetation areas.",
    },
    "ndwi": {
        "name": "Normalized Difference Water Index",
        "formula": "(Green - NIR) / (Green + NIR)",
        "bands": {"green": "B03", "nir": "B08"},
        "range": [-1.0, 1.0],
        "description": "Water body detection. >0 = water features.",
    },
    "mndwi": {
        "name": "Modified Normalized Difference Water Index",
        "formula": "(Green - SWIR) / (Green + SWIR)",
        "bands": {"green": "B03", "swir": "B11"},
        "range": [-1.0, 1.0],
        "description": "Enhanced water detection, reduces urban false positives.",
    },
    "ndbi": {
        "name": "Normalized Difference Built-up Index",
        "formula": "(SWIR - NIR) / (SWIR + NIR)",
        "bands": {"swir": "B11", "nir": "B08"},
        "range": [-1.0, 1.0],
        "description": "Urban/built-up area detection. >0 = built-up areas.",
    },
}


class SpectralIndicesTool(BaseTool):
    """Calculate spectral indices from satellite imagery bands.

    Supports NDVI, EVI, SAVI, NDWI, MNDWI, and NDBI. Each index uses
    specific Sentinel-2 bands and returns values typically in [-1, 1].
    """

    name = "spectral_indices"
    description = (
        "Calculate spectral indices (NDVI, EVI, SAVI, NDWI, MNDWI, NDBI) "
        "from satellite imagery. Use when analyzing vegetation, water, or "
        "urban areas. Returns index metadata and formula info. "
        "Do NOT use for raw band download."
    )
    supported_operations = [
        SpatialOperation.NDVI.value,
        SpatialOperation.EVI.value,
        SpatialOperation.SAVI.value,
        SpatialOperation.NDWI.value,
        SpatialOperation.MNDWI.value,
        SpatialOperation.NDBI.value,
    ]

    STAC_API = "https://earth-search.aws.element84.com/v1"
    COLLECTION = "sentinel-2-l2a"

    def execute(self, query: SpatialQuery) -> SpatialResult:
        """Execute spectral index query.

        Routes to the appropriate index based on query operation or
        metadata['index'] field.

        Args:
            query: Spatial query with geometry and operation type.

        Returns:
            SpatialResult with scene metadata and index info.
        """
        index_name = self._resolve_index(query)
        if index_name not in SPECTRAL_INDEX_FORMULAS:
            return SpatialResult(
                errors=[
                    f"Unknown index: {index_name}. "
                    f"Available: {list(SPECTRAL_INDEX_FORMULAS.keys())}"
                ]
            )
        return self._search_for_index(query, index_name)

    def _resolve_index(self, query: SpatialQuery) -> str:
        """Determine which spectral index to calculate."""
        # Check metadata first for explicit index request
        if query.metadata and "index" in query.metadata:
            return query.metadata["index"].lower()
        # Fall back to operation name
        return query.operation.value if hasattr(query.operation, "value") else str(query.operation)

    def _search_for_index(self, query: SpatialQuery, index_name: str) -> SpatialResult:
        """Search STAC and return index-ready metadata."""
        formula_info = SPECTRAL_INDEX_FORMULAS[index_name]
        search_body = self._build_stac_search(query)

        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(f"{self.STAC_API}/search", json=search_body)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            return SpatialResult(errors=[f"STAC search failed: {e}"])

        stac_features = data.get("features", [])
        features = []
        for item in stac_features:
            props = item.get("properties", {})
            features.append(
                SpatialFeature(
                    id=item.get("id"),
                    geometry=item.get("geometry", {}),
                    properties={
                        "datetime": props.get("datetime", ""),
                        "cloud_cover": props.get("eo:cloud_cover"),
                        "index": index_name,
                        "index_name": formula_info["name"],
                        "formula": formula_info["formula"],
                        "required_bands": formula_info["bands"],
                        "value_range": formula_info["range"],
                    },
                )
            )

        return SpatialResult(
            features=features,
            spatial_context=SpatialContext(
                total_features=len(features),
                summary=(
                    f"Found {len(features)} scenes for {formula_info['name']}. "
                    f"Formula: {formula_info['formula']}. "
                    f"{formula_info['description']}"
                ),
            ),
            sources=["element84-earth-search", "sentinel-2-l2a"],
        )

    def _build_stac_search(self, query: SpatialQuery) -> dict[str, Any]:
        """Build a STAC API search request body."""
        body: dict[str, Any] = {
            "collections": [self.COLLECTION],
            "limit": min(query.limit, 10),
        }
        if query.geometry:
            body["intersects"] = query.geometry.model_dump()
        elif query.bbox:
            body["bbox"] = list(query.bbox.to_tuple())
        return body

    # --- Static computation methods (require numpy) ---

    @staticmethod
    def calculate_ndvi(nir: Any, red: Any) -> Any:
        """NDVI = (NIR - Red) / (NIR + Red)."""
        import numpy as np
        nir, red = nir.astype(np.float64), red.astype(np.float64)
        denom = nir + red
        return np.where(denom == 0, 0.0, (nir - red) / denom)

    @staticmethod
    def calculate_evi(nir: Any, red: Any, blue: Any) -> Any:
        """EVI = 2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)."""
        import numpy as np
        nir, red, blue = (a.astype(np.float64) for a in (nir, red, blue))
        denom = nir + 6.0 * red - 7.5 * blue + 1.0
        return np.where(denom == 0, 0.0, 2.5 * (nir - red) / denom)

    @staticmethod
    def calculate_savi(nir: Any, red: Any, soil_factor: float = 0.5) -> Any:
        """SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)."""
        import numpy as np
        nir, red = nir.astype(np.float64), red.astype(np.float64)
        denom = nir + red + soil_factor
        return np.where(denom == 0, 0.0, ((nir - red) / denom) * (1.0 + soil_factor))

    @staticmethod
    def calculate_ndwi(green: Any, nir: Any) -> Any:
        """NDWI = (Green - NIR) / (Green + NIR)."""
        import numpy as np
        green, nir = green.astype(np.float64), nir.astype(np.float64)
        denom = green + nir
        return np.where(denom == 0, 0.0, (green - nir) / denom)

    @staticmethod
    def calculate_mndwi(green: Any, swir: Any) -> Any:
        """MNDWI = (Green - SWIR) / (Green + SWIR)."""
        import numpy as np
        green, swir = green.astype(np.float64), swir.astype(np.float64)
        denom = green + swir
        return np.where(denom == 0, 0.0, (green - swir) / denom)

    @staticmethod
    def calculate_ndbi(swir: Any, nir: Any) -> Any:
        """NDBI = (SWIR - NIR) / (SWIR + NIR)."""
        import numpy as np
        swir, nir = swir.astype(np.float64), nir.astype(np.float64)
        denom = swir + nir
        return np.where(denom == 0, 0.0, (swir - nir) / denom)
