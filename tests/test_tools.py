"""Tests for GeoSpark Phase 2A tools.

Tests cover instantiation, schema, spectral index math, URL construction,
and mocked HTTP responses. All tests run offline (no network calls).
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from geospark.protocol.schema import (
    Point,
    SpatialQuery,
    SpatialOperation,
)
from geospark.tools.satellite.ndvi import NDVITool
from geospark.tools.satellite.spectral_indices import (
    SpectralIndicesTool,
    SPECTRAL_INDEX_FORMULAS,
)
from geospark.tools.geocoding.reverse import ReverseGeocoder
from geospark.tools.routing.osrm import OSRMRouteTool
from geospark.tools.registry import ToolRegistry, TOOL_CLASSES


# ---- Instantiation & Schema Tests ----


class TestNDVIToolMeta:
    """Test NDVITool metadata and instantiation."""

    def test_instantiation(self):
        tool = NDVITool()
        assert tool is not None

    def test_name(self):
        assert NDVITool().name == "ndvi"

    def test_description_not_empty(self):
        assert len(NDVITool().description) > 10

    def test_supported_operations(self):
        ops = NDVITool().supported_operations
        assert "ndvi" in ops
        assert "band_math" in ops

    def test_supports_method(self):
        tool = NDVITool()
        assert tool.supports("ndvi")
        assert tool.supports("band_math")
        assert not tool.supports("geocode")

    def test_schema_has_name(self):
        schema = NDVITool().get_schema()
        assert schema["name"] == "ndvi"


class TestSpectralIndicesToolMeta:
    """Test SpectralIndicesTool metadata and instantiation."""

    def test_instantiation(self):
        tool = SpectralIndicesTool()
        assert tool is not None

    def test_name(self):
        assert SpectralIndicesTool().name == "spectral_indices"

    def test_supported_operations(self):
        ops = SpectralIndicesTool().supported_operations
        for idx in ("ndvi", "evi", "savi", "ndwi", "mndwi", "ndbi"):
            assert idx in ops

    def test_formulas_dict_complete(self):
        """Every supported index must have a formula entry."""
        for idx in ("ndvi", "evi", "savi", "ndwi", "mndwi", "ndbi"):
            assert idx in SPECTRAL_INDEX_FORMULAS
            info = SPECTRAL_INDEX_FORMULAS[idx]
            assert "formula" in info
            assert "bands" in info
            assert "description" in info


class TestReverseGeocoderMeta:
    """Test ReverseGeocoder metadata and instantiation."""

    def test_instantiation(self):
        tool = ReverseGeocoder()
        assert tool is not None

    def test_name(self):
        assert ReverseGeocoder().name == "reverse_geocoder"

    def test_supported_operations(self):
        assert "reverse_geocode" in ReverseGeocoder().supported_operations

    def test_schema_has_name(self):
        schema = ReverseGeocoder().get_schema()
        assert schema["name"] == "reverse_geocoder"


class TestOSRMRouteToolMeta:
    """Test OSRMRouteTool metadata and instantiation."""

    def test_instantiation(self):
        tool = OSRMRouteTool()
        assert tool is not None

    def test_name(self):
        assert OSRMRouteTool().name == "router"

    def test_supported_operations(self):
        ops = OSRMRouteTool().supported_operations
        assert "route" in ops
        assert "isochrone" in ops

    def test_schema_has_name(self):
        schema = OSRMRouteTool().get_schema()
        assert schema["name"] == "router"


# ---- Registry Tests ----


class TestRegistryNewTools:
    """Test that new tools are registered and loadable."""

    def test_new_tools_in_registry(self):
        for key in ("ndvi", "spectral_indices", "reverse_geocoder", "router"):
            assert key in TOOL_CLASSES

    def test_load_ndvi(self):
        registry = ToolRegistry()
        registry.load_tool("ndvi")
        tool = registry.get_tool("ndvi")
        assert tool is not None
        assert tool.name == "ndvi"

    def test_load_spectral_indices(self):
        registry = ToolRegistry()
        registry.load_tool("spectral_indices")
        tool = registry.get_tool("spectral_indices")
        assert tool is not None

    def test_load_reverse_geocoder(self):
        registry = ToolRegistry()
        registry.load_tool("reverse_geocoder")
        tool = registry.get_tool("reverse_geocoder")
        assert tool is not None

    def test_load_router(self):
        registry = ToolRegistry()
        registry.load_tool("router")
        tool = registry.get_tool("router")
        assert tool is not None

    def test_operation_map(self):
        registry = ToolRegistry()
        registry.load_tool("router")
        assert registry.get_tool_for_operation("route") is not None


# ---- Spectral Index Math Tests ----


class TestSpectralMath:
    """Test spectral index calculations with known arrays."""

    def test_ndvi_basic(self):
        nir = np.array([0.5, 0.8, 0.0])
        red = np.array([0.1, 0.1, 0.0])
        result = SpectralIndicesTool.calculate_ndvi(nir, red)
        # First two have valid denominators; third is 0/0 → 0
        np.testing.assert_allclose(result[0], (0.5 - 0.1) / (0.5 + 0.1), atol=1e-10)
        np.testing.assert_allclose(result[1], (0.8 - 0.1) / (0.8 + 0.1), atol=1e-10)
        assert result[2] == 0.0

    def test_ndvi_zero_denominator(self):
        nir = np.array([0.0])
        red = np.array([0.0])
        result = SpectralIndicesTool.calculate_ndvi(nir, red)
        assert result[0] == 0.0

    def test_ndvi_tool_static_method(self):
        """NDVITool's _calculate_ndvi_from_arrays should match."""
        nir = np.array([0.6, 0.9])
        red = np.array([0.2, 0.3])
        result = NDVITool._calculate_ndvi_from_arrays(nir, red)
        expected = (nir - red) / (nir + red)
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_ndvi_clipping(self):
        """NDVI should be clipped to [-1, 1]."""
        nir = np.array([1.0, 0.0])
        red = np.array([0.0, 1.0])
        result = NDVITool._calculate_ndvi_from_arrays(nir, red)
        assert np.all(result >= -1.0)
        assert np.all(result <= 1.0)

    def test_evi_basic(self):
        nir = np.array([0.5])
        red = np.array([0.1])
        blue = np.array([0.05])
        result = SpectralIndicesTool.calculate_evi(nir, red, blue)
        denom = nir + 6.0 * red - 7.5 * blue + 1.0
        expected = 2.5 * (nir - red) / denom
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_savi_basic(self):
        nir = np.array([0.6])
        red = np.array([0.2])
        result = SpectralIndicesTool.calculate_savi(nir, red, soil_factor=0.5)
        expected = ((0.6 - 0.2) / (0.6 + 0.2 + 0.5)) * 1.5
        np.testing.assert_allclose(result, [expected], atol=1e-10)

    def test_ndwi_basic(self):
        green = np.array([0.3])
        nir = np.array([0.7])
        result = SpectralIndicesTool.calculate_ndwi(green, nir)
        expected = (0.3 - 0.7) / (0.3 + 0.7)
        np.testing.assert_allclose(result, [expected], atol=1e-10)

    def test_mndwi_basic(self):
        green = np.array([0.4])
        swir = np.array([0.1])
        result = SpectralIndicesTool.calculate_mndwi(green, swir)
        expected = (0.4 - 0.1) / (0.4 + 0.1)
        np.testing.assert_allclose(result, [expected], atol=1e-10)

    def test_ndbi_basic(self):
        swir = np.array([0.5])
        nir = np.array([0.3])
        result = SpectralIndicesTool.calculate_ndbi(swir, nir)
        expected = (0.5 - 0.3) / (0.5 + 0.3)
        np.testing.assert_allclose(result, [expected], atol=1e-10)


# ---- Reverse Geocoder URL Tests ----


class TestReverseGeocoderURL:
    """Test Nominatim URL/parameter construction."""

    def test_build_params_basic(self):
        tool = ReverseGeocoder()
        query = SpatialQuery(
            operation=SpatialOperation.REVERSE_GEOCODE,
            geometry=Point.from_latlon(48.8566, 2.3522),
        )
        params = tool._build_params(48.8566, 2.3522, query)
        assert params["lat"] == 48.8566
        assert params["lon"] == 2.3522
        assert params["format"] == "geojson"
        assert params["addressdetails"] == 1

    def test_build_params_with_zoom(self):
        tool = ReverseGeocoder()
        query = SpatialQuery(
            operation=SpatialOperation.REVERSE_GEOCODE,
            geometry=Point.from_latlon(48.8566, 2.3522),
            metadata={"zoom": 10},
        )
        params = tool._build_params(48.8566, 2.3522, query)
        assert params["zoom"] == 10

    def test_execute_no_geometry_returns_error(self):
        tool = ReverseGeocoder()
        query = SpatialQuery(operation=SpatialOperation.REVERSE_GEOCODE)
        result = tool.execute(query)
        assert len(result.errors) > 0
        assert "Point geometry" in result.errors[0]

    @patch("geospark.tools.geocoding.reverse.httpx.Client")
    def test_execute_mocked(self, mock_client_cls):
        """Test full execute with mocked HTTP response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [2.3522, 48.8566]},
                    "properties": {
                        "display_name": "Paris, France",
                        "address": {
                            "city": "Paris",
                            "country": "France",
                        },
                        "type": "city",
                        "category": "place",
                        "place_id": 12345,
                    },
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        tool = ReverseGeocoder()
        query = SpatialQuery(
            operation=SpatialOperation.REVERSE_GEOCODE,
            geometry=Point.from_latlon(48.8566, 2.3522),
        )
        result = tool.execute(query)
        assert len(result.errors) == 0
        assert len(result.features) == 1
        assert result.features[0].properties["display_name"] == "Paris, France"
        assert result.features[0].properties["address"]["city"] == "Paris"


# ---- OSRM URL & Route Tests ----


class TestOSRMRouteURL:
    """Test OSRM URL construction and response parsing."""

    def test_build_route_url(self):
        tool = OSRMRouteTool()
        url = tool._build_route_url([13.388860, 52.517037], [13.397634, 52.529407])
        assert "router.project-osrm.org" in url
        assert "13.38886,52.517037;13.397634,52.529407" in url
        assert "overview=full" in url
        assert "geometries=geojson" in url

    def test_extract_points_missing_metadata(self):
        tool = OSRMRouteTool()
        query = SpatialQuery(operation=SpatialOperation.ROUTE)
        origin, dest, error = tool._extract_points(query)
        assert error is not None
        assert origin is None

    def test_extract_points_valid(self):
        tool = OSRMRouteTool()
        query = SpatialQuery(
            operation=SpatialOperation.ROUTE,
            metadata={
                "origin": [13.388860, 52.517037],
                "destination": [13.397634, 52.529407],
            },
        )
        origin, dest, error = tool._extract_points(query)
        assert error is None
        assert origin == [13.388860, 52.517037]
        assert dest == [13.397634, 52.529407]

    @patch("geospark.tools.routing.osrm.httpx.Client")
    def test_execute_route_mocked(self, mock_client_cls):
        """Test full route execution with mocked OSRM response."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [13.38886, 52.517037],
                            [13.39, 52.52],
                            [13.397634, 52.529407],
                        ],
                    },
                    "distance": 1884.8,
                    "duration": 251.4,
                    "legs": [
                        {
                            "steps": [
                                {
                                    "maneuver": {"type": "depart"},
                                    "name": "Friedrichstraße",
                                    "distance": 500,
                                    "duration": 60,
                                },
                                {
                                    "maneuver": {"type": "turn"},
                                    "name": "Torstraße",
                                    "distance": 1384.8,
                                    "duration": 191.4,
                                },
                            ]
                        }
                    ],
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        tool = OSRMRouteTool()
        query = SpatialQuery(
            operation=SpatialOperation.ROUTE,
            metadata={
                "origin": [13.388860, 52.517037],
                "destination": [13.397634, 52.529407],
            },
        )
        result = tool.execute(query)
        assert len(result.errors) == 0
        assert len(result.features) == 1
        props = result.features[0].properties
        assert props["distance_m"] == 1884.8
        assert props["duration_s"] == 251.4
        assert props["distance_km"] == 1.88
        assert props["steps_count"] == 2
        assert "1.9 km" in result.spatial_context.summary

    def test_execute_missing_destination(self):
        tool = OSRMRouteTool()
        query = SpatialQuery(
            operation=SpatialOperation.ROUTE,
            metadata={"origin": [13.388860, 52.517037]},
        )
        result = tool.execute(query)
        assert len(result.errors) > 0

    def test_isochrone_stub(self):
        tool = OSRMRouteTool()
        query = SpatialQuery(operation=SpatialOperation.ISOCHRONE)
        result = tool.execute(query)
        assert "Isochrone" in result.spatial_context.summary


# ---- NDVI Execute (Mocked) ----


class TestNDVIExecute:
    """Test NDVITool execute with mocked STAC responses."""

    @patch("geospark.tools.satellite.ndvi.httpx.Client")
    def test_execute_mocked(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "S2A_TEST_001",
                    "geometry": {"type": "Point", "coordinates": [2.35, 48.86]},
                    "properties": {
                        "datetime": "2024-06-15T10:30:00Z",
                        "eo:cloud_cover": 5.2,
                        "platform": "sentinel-2a",
                    },
                    "assets": {"nir": {}, "red": {}},
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        tool = NDVITool()
        query = SpatialQuery(
            operation=SpatialOperation.NDVI,
            geometry=Point.from_latlon(48.86, 2.35),
        )
        result = tool.execute(query)
        assert len(result.errors) == 0
        assert len(result.features) == 1
        assert result.features[0].properties["ndvi_formula"] == "(B08 - B04) / (B08 + B04)"
        assert "NDVI" in result.spatial_context.summary

    def test_unsupported_operation(self):
        tool = NDVITool()
        query = SpatialQuery(operation=SpatialOperation.GEOCODE)
        result = tool.execute(query)
        assert len(result.errors) > 0


# ---- Spectral Indices Execute (Mocked) ----


class TestSpectralIndicesExecute:
    """Test SpectralIndicesTool execute routing."""

    @patch("geospark.tools.satellite.spectral_indices.httpx.Client")
    def test_execute_ndwi_mocked(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "type": "FeatureCollection",
            "features": [
                {
                    "id": "S2A_WATER_001",
                    "geometry": {"type": "Point", "coordinates": [12.0, 45.0]},
                    "properties": {
                        "datetime": "2024-07-01T09:00:00Z",
                        "eo:cloud_cover": 2.0,
                    },
                    "assets": {},
                }
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        tool = SpectralIndicesTool()
        query = SpatialQuery(
            operation=SpatialOperation.NDWI,
            geometry=Point.from_latlon(45.0, 12.0),
        )
        result = tool.execute(query)
        assert len(result.errors) == 0
        assert result.features[0].properties["index"] == "ndwi"
        assert "Water" in result.features[0].properties["index_name"]

    def test_unknown_index_error(self):
        tool = SpectralIndicesTool()
        query = SpatialQuery(
            operation=SpatialOperation.NDVI,
            metadata={"index": "fake_index"},
        )
        result = tool.execute(query)
        assert len(result.errors) > 0
        assert "Unknown index" in result.errors[0]
