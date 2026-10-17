"""Tests for elevation: Copernicus GLO-30 first, Open Elevation as fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from geospark.protocol.schema import Point, SpatialOperation, SpatialQuery
from geospark.tools.terrain import copernicus
from geospark.tools.terrain.elevation import ElevationTool


@pytest.fixture(autouse=True)
def _clear_cache():
    copernicus._cache.clear()
    yield
    copernicus._cache.clear()


def _query(lat: float, lon: float) -> SpatialQuery:
    return SpatialQuery(operation=SpatialOperation.ELEVATION, geometry=Point.from_latlon(lat, lon))


class TestTileNames:
    def test_southern_and_eastern_hemispheres(self):
        # Wollumbin: tile named by its south-west corner, 29S 153E
        assert copernicus.tile_url(-28.3978, 153.2716).endswith(
            "Copernicus_DSM_COG_10_S29_00_E153_00_DEM/Copernicus_DSM_COG_10_S29_00_E153_00_DEM.tif"
        )

    def test_northern_and_western_hemispheres(self):
        assert "N51_00_W001_00" in copernicus.tile_url(51.5, -0.1)

    def test_rejects_impossible_coordinates(self):
        with pytest.raises(ValueError):
            copernicus.read_height(95, 10)


class TestCopernicusReads:
    def test_height_is_cached(self):
        with patch.object(copernicus, "_read_uncached", return_value=2225.9) as read:
            assert copernicus.read_height(-36.4558, 148.2635) == 2225.9
            assert copernicus.read_height(-36.4558, 148.2635) == 2225.9
        assert read.call_count == 1

    def test_sea_raises_no_land_tile(self):
        with (
            patch.object(copernicus, "_read_uncached", return_value=None),
            pytest.raises(copernicus.NoLandTileError),
        ):
            copernicus.read_height(-30.0, 156.0)


class TestElevationTool:
    def test_uses_copernicus_with_attribution(self):
        with (
            patch.object(copernicus, "available", return_value=True),
            patch.object(copernicus, "read_height", return_value=1068.5),
        ):
            result = ElevationTool().execute(_query(-28.3978, 153.2716))
        props = result.features[0].properties
        assert props["elevation_m"] == 1068.5
        assert result.sources == ["copernicus-dem"]
        assert props["vertical_datum"] == "EGM2008"
        assert "Copernicus WorldDEM-30" in props["attribution"]

    def test_falls_back_to_open_elevation_at_sea(self):
        response = MagicMock()
        response.json.return_value = {"results": [{"elevation": 0}]}
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        with (
            patch.object(copernicus, "available", return_value=True),
            patch.object(copernicus, "read_height", side_effect=copernicus.NoLandTileError("sea")),
            patch("geospark.tools.terrain.elevation.httpx.Client", return_value=client),
        ):
            result = ElevationTool().execute(_query(-30.0, 156.0))
        props = result.features[0].properties
        assert result.sources == ["open-elevation-api"]
        assert "open sea" in props["fallback_note"]

    def test_falls_back_when_rasterio_is_missing(self):
        response = MagicMock()
        response.json.return_value = {"results": [{"elevation": 959}]}
        client = MagicMock()
        client.__enter__.return_value.get.return_value = response
        with (
            patch.object(copernicus, "available", return_value=False),
            patch("geospark.tools.terrain.elevation.httpx.Client", return_value=client),
        ):
            result = ElevationTool().execute(_query(-28.3978, 153.2716))
        assert result.sources == ["open-elevation-api"]
        assert "fallback_note" not in result.features[0].properties
