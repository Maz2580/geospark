"""Sun position, sunrise and shadows; terrain horizons and lines of sight.

Sun values are checked against fixed references (NREL SPA via pvlib, worked once and frozen here);
the terrain functions run on synthetic DEMs, so every expected angle and clearance is known exactly.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import numpy as np
import pytest

from geospark import sun, visibility

# --- sun ------------------------------------------------------------------------------------------


def test_position_matches_nrel_spa() -> None:
    # NREL SPA (pvlib 0.16.1, pressure 101325 Pa, 12 °C): apparent elevation 67.99°, azimuth 54.78°
    p = sun.sun_position(-37.818, 144.969, "2026-12-21T12:00:00+11:00")
    assert p["elevation_deg"] == pytest.approx(67.995, abs=0.02)
    assert p["azimuth_deg"] == pytest.approx(54.779, abs=0.03)


def test_melbourne_summer_solstice_times() -> None:
    t = sun.sun_times(-37.818, 144.969, "2026-12-21", tz="Australia/Melbourne")
    assert t["sunrise"].startswith("2026-12-21T05:54") and t["sunset"].startswith("2026-12-21T20:41")
    assert t["solar_noon_elevation_deg"] == pytest.approx(90 - 37.818 + 23.43, abs=0.05)


def test_polar_day_and_night() -> None:
    assert sun.sun_times(78.2, 15.6, "2026-06-21")["note"].startswith("polar day")
    night = sun.sun_times(78.2, 15.6, "2026-12-21")
    assert night["day_length_h"] == 0.0 and night["sunrise"] is None


def test_shadow_length_and_direction() -> None:
    s = sun.shadow(-37.818, 144.969, "2026-06-21T12:00:00+10:00", object_height_m=10)
    assert s["shadow_length_m"] == pytest.approx(10 / math.tan(math.radians(s["elevation_deg"])), abs=1e-3)
    # Southern-hemisphere midday: the Sun is to the north, so the shadow points roughly south
    assert 150 < s["shadow_direction_deg"] < 210


def test_times_need_an_offset_or_a_zone() -> None:
    with pytest.raises(sun.SunError, match="UTC offset"):
        sun.sun_position(-37.8, 144.9, "2026-06-21T12:00:00")
    assert sun.sun_position(-37.8, 144.9, "2026-06-21T12:00:00", tz="Australia/Melbourne")["time"].endswith("+10:00")
    with pytest.raises(sun.SunError, match="Unknown time zone"):
        sun.sun_times(-37.8, 144.9, "2026-06-21", tz="Mars/Olympus")


def test_terrain_shortens_the_day() -> None:
    flat = {"azimuths_deg": [float(a) for a in range(0, 360, 5)], "horizon_elevation_deg": [0.0] * 72,
            "ground_elevation_m": 300.0, "provenance": [{}], "warnings": []}
    walled = {**flat, "horizon_elevation_deg": [20.0] * 72}
    with patch.object(visibility, "horizon", return_value=flat):
        open_sky = sun.sunlight_hours(-36.73, 146.96, "2026-06-21", tz="Australia/Melbourne")
    with patch.object(visibility, "horizon", return_value=walled):
        valley = sun.sunlight_hours(-36.73, 146.96, "2026-06-21", tz="Australia/Melbourne")
    assert open_sky["terrain_hours"] == pytest.approx(open_sky["flat_horizon_hours"], abs=0.1)
    # Midwinter noon at 36.7° S is about 30°: a 20° wall leaves only the middle of the day
    assert 0 < valley["terrain_hours"] < open_sky["terrain_hours"] - 4


# --- terrain, on synthetic DEMs ---------------------------------------------------------------------


class _Plane:
    """A DEM: flat at 100 m, with an optional ridge of height `ridge` along a meridian east of the origin."""

    def __init__(self, lon0: float, ridge_lon: float | None = None, ridge: float = 0.0, width: float = 0.0006) -> None:
        self.lon0, self.ridge_lon, self.ridge, self.width = lon0, ridge_lon, ridge, width
        self.sea_samples = 0

    def heights(self, lon: np.ndarray, lat: np.ndarray, factor: int = 1) -> np.ndarray:
        h = np.full(np.shape(lon), 100.0)
        if self.ridge_lon is not None:
            h[np.abs(np.asarray(lon) - self.ridge_lon) < self.width] += self.ridge
        return h


def _with(dem: _Plane):
    return patch.object(visibility, "_Dem", return_value=dem)


def test_flat_ground_horizon_is_the_curvature_dip() -> None:
    with _with(_Plane(145.0)):
        h = visibility.horizon(-37.0, 145.0, observer_height_m=10, max_distance_m=20_000, step_deg=10)
    # Over flat ground the horizon is the geometric one: dip 2 sqrt(h (1 - k) / 2R), at sqrt(2R h / (1 - k))
    c = (1 - visibility.REFRACTION_K) / (2 * visibility.EARTH_RADIUS_M)
    assert max(h["horizon_elevation_deg"]) == pytest.approx(-math.degrees(2 * math.sqrt(10 * c)), abs=0.002)
    assert all(abs(d - math.sqrt(10 / c)) < 300 for d in h["obstruction_distance_m"])


def test_a_ridge_raises_the_horizon_where_expected() -> None:
    lat, lon = -37.0, 145.0
    ridge_lon = lon + 2000 / (111_320 * math.cos(math.radians(lat)))  # 2 km east
    with _with(_Plane(lon, ridge_lon, ridge=200)):
        h = visibility.horizon(lat, lon, observer_height_m=0, max_distance_m=10_000, step_deg=10)
    east = h["horizon_elevation_deg"][h["azimuths_deg"].index(90.0)]
    expected = math.degrees(math.atan2(200 - 2000**2 * (1 - visibility.REFRACTION_K) / (2 * visibility.EARTH_RADIUS_M), 2000))
    assert east == pytest.approx(expected, abs=0.2)
    assert h["horizon_elevation_deg"][h["azimuths_deg"].index(270.0)] <= 0  # nothing to the west
    assert h["highest"]["azimuth_deg"] == 90.0


def test_line_of_sight_over_and_into_a_ridge() -> None:
    lat, lon = -37.0, 145.0
    k = 111_320 * math.cos(math.radians(lat))
    ridge_lon = lon + 2000 / k
    end = lon + 4000 / k
    with _with(_Plane(lon, ridge_lon, ridge=50)):
        blocked = visibility.line_of_sight(lat, lon, lat, end, 2, 2)
        clear = visibility.line_of_sight(lat, lon, lat, end, 60, 60, frequency_mhz=900)
    assert not blocked["visible"] and blocked["min_clearance_m"] < 0
    assert blocked["min_clearance_at"]["distance_from_a_m"] == pytest.approx(2000, abs=60)
    assert clear["visible"] and clear["min_clearance_m"] == pytest.approx(10, abs=1)
    # First Fresnel radius at mid-path for 900 MHz over 4 km: sqrt(λ d1 d2 / D) ≈ 18.3 m; 10 m clear is < 60%
    assert clear["fresnel"]["f1_radius_there_m"] == pytest.approx(18.3, abs=0.6)
    assert clear["fresnel"]["sixty_percent_clear"] is False


def test_long_links_account_for_the_earth_bulge() -> None:
    with _with(_Plane(145.0)):
        out = visibility.line_of_sight(-37.0, 145.0, -37.0, 145.0 + 60_000 / 88_900, 10, 10)
    # 60 km over flat ground: the bulge at mid-path is 30 km² (1 - k) / 2R ≈ 61 m, far above 10 m masts
    assert not out["visible"] and out["min_clearance_m"] == pytest.approx(10 - 61.4, abs=2)


def test_inputs_are_validated() -> None:
    with pytest.raises(visibility.VisibilityError, match="divide 360"):
        visibility.horizon(-37.0, 145.0, step_deg=7)
    with pytest.raises(visibility.VisibilityError, match="less than 60 m"):
        visibility.line_of_sight(-37.0, 145.0, -37.0, 145.0001)
    with pytest.raises(visibility.VisibilityError, match="84°"):
        visibility.horizon(85.0, 10.0)


def test_caveats_name_the_surface_model() -> None:
    with _with(_Plane(145.0)):
        h = visibility.horizon(-37.0, 145.0, step_deg=10, max_distance_m=1000)
    assert any("surface model" in w for w in h["warnings"])
    assert h["provenance"][0]["source"] == "Copernicus DEM GLO-30"
