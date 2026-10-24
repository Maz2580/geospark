"""check_dataset on point clouds and rasters: the vertical errors that LiDAR and DEM deliveries carry.

Each case is a small LiDAR tile or DEM in Melbourne (GDA2020 / MGA zone 55) with a known mistake,
checked against survey marks whose AHD heights are right. The checker must name that mistake, and
only that one.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

terrio = pytest.importorskip("terrio")

from geospark import geodesy  # noqa: E402
from geospark.io import check, surface  # noqa: E402

X0, Y0 = 321000.0, 5812200.0
MARKS = [(321050.0, 5812250.0), (321120.0, 5812300.0), (321200.0, 5812420.0), (321260.0, 5812500.0),
         (321333.0, 5812550.0), (321380.0, 5812580.0)]
SEPARATION = {"separation_m": 4.743, "geoid_model": "AUSGeoid2020"}  # AUSGeoid2020 in Melbourne


def _ground(x: np.ndarray) -> np.ndarray:
    return 30.0 + (x - X0) * 0.01  # AHD, a gentle slope


def _laz(path: Path, z_of=_ground, crs: str | None = "EPSG:7855+5711", classify: bool = True) -> Path:
    rng = np.random.default_rng(1)
    x, y = rng.uniform(X0, X0 + 400, 30_000), rng.uniform(Y0, Y0 + 400, 30_000)
    arrays = {"x": x, "y": y, "z": z_of(x)}
    if classify:
        arrays["classification"] = np.full(x.size, 2, np.uint8)
    pc = terrio.PointCloud.from_dict(arrays, crs=crs) if crs else terrio.PointCloud.from_dict(arrays)
    pc.write(str(path))
    return path


def _dem(path: Path, offset: float = 0.0, crs: str = "EPSG:7855") -> Path:
    cell = 5.0
    cols = np.arange(80) * cell + X0 + cell / 2
    grid = np.tile(_ground(cols) + offset, (80, 1)).astype("float32")
    terrio.Raster.from_array(grid, (X0, cell, 0.0, Y0 + 400, 0.0, -cell), crs=crs, nodata=-9999.0).write(str(path))
    return path


def _marks(path: Path, crs_values=None) -> Path:
    rows = ["id,x,y,ahd"]
    for i, ((x, _y), (vx, vy)) in enumerate(zip(MARKS, crs_values or MARKS, strict=True)):
        rows.append(f"{i},{vx},{vy},{_ground(np.array(x)):.3f}")
    path.write_text("\n".join(rows) + "\n")
    return path


def _codes(report) -> list[str]:
    return [f["code"] for f in report["findings"]]


# --- against survey marks ---------------------------------------------------------------------------

def test_lidar_in_ahd_agrees_with_ahd_marks(tmp_path) -> None:
    report = check.compare_layers(_marks(tmp_path / "marks.csv"), _laz(tmp_path / "tile.laz"), crs_a="EPSG:7855")
    assert report["verdict"] == "no issues found" and report["pairs"] == 6
    assert "heights_consistent" in _codes(report)
    assert report["paired_by"] == "ground points within 1 m of each mark"


def test_ellipsoidal_lidar_labelled_ahd_is_named(tmp_path) -> None:
    tile = _laz(tmp_path / "tile.laz", lambda x: _ground(x) + 4.743)
    with patch.object(geodesy, "convert_height", return_value=SEPARATION):
        report = check.compare_layers(_marks(tmp_path / "marks.csv"), tile, crs_a="EPSG:7855")
    finding = next(f for f in report["findings"] if f["code"] == "ellipsoidal_vs_ahd")
    assert finding["evidence"]["median_dz_m"] == pytest.approx(4.743, abs=0.02)
    assert "tile.laz has ellipsoidal" in finding["message"] and report["verdict"] == "problem"


def test_lidar_heights_in_feet_labelled_metres_are_named(tmp_path) -> None:
    tile = _laz(tmp_path / "tile.laz", lambda x: _ground(x) / 0.3048)
    report = check.compare_layers(_marks(tmp_path / "marks.csv"), tile, crs_a="EPSG:7855")
    assert _codes(report) == ["height_units_wrong"]


def test_gda94_marks_are_converted_officially_before_lookup(tmp_path) -> None:
    gda94 = geodesy.transform("EPSG:7855", "EPSG:28355", [list(p) for p in MARKS]).coordinates
    marks = _marks(tmp_path / "marks.csv", [tuple(p) for p in gda94])
    report = check.compare_layers(marks, _laz(tmp_path / "tile.laz"), crs_a="EPSG:28355")
    assert "heights_consistent" in _codes(report) and report["verdict"] == "no issues found"


def test_undeclared_heights_that_match_the_marks_are_inferred_not_asserted(tmp_path) -> None:
    report = check.compare_layers(_marks(tmp_path / "marks.csv"), _laz(tmp_path / "tile.laz", crs="EPSG:7855"),
                                  crs_a="EPSG:7855")
    assert _codes(report) == ["heights_consistent", "height_reference_inferred"]
    assert report["verdict"] == "check the caveats"


def test_marks_outside_the_tile_are_not_compared(tmp_path) -> None:
    far = [(x + 5000, y) for x, y in MARKS]
    report = check.compare_layers(_marks(tmp_path / "marks.csv", far), _laz(tmp_path / "tile.laz"), crs_a="EPSG:7855")
    assert "no_overlap" in _codes(report) and report["verdict"] == "problem"


def test_dem_against_marks(tmp_path) -> None:
    marks = _marks(tmp_path / "marks.csv")
    clean = check.compare_layers(marks, _dem(tmp_path / "dem.tif"), crs_a="EPSG:7855")
    assert "heights_consistent" in _codes(clean) and clean["paired_by"] == "the raster cell at each mark"
    with patch.object(geodesy, "convert_height", return_value=SEPARATION):
        wrong = check.compare_layers(marks, _dem(tmp_path / "dem_ellip.tif", offset=4.743), crs_a="EPSG:7855")
    assert "ellipsoidal_vs_ahd" in _codes(wrong)


def test_two_surfaces_are_not_compared(tmp_path) -> None:
    report = check.compare_layers(_laz(tmp_path / "a.laz"), _dem(tmp_path / "b.tif"))
    assert _codes(report) == ["not_compared"]


# --- one file ---------------------------------------------------------------------------------------

def test_a_clean_tile_reports_its_vertical_crs(tmp_path) -> None:
    report = check.check_layer(_laz(tmp_path / "tile.laz"))
    assert report["kind"] == "pointcloud" and report["features"] == 30_000
    assert report["vertical_crs"] == "AHD height" and report["verdict"] == "no issues found"


def test_a_tile_without_a_vertical_crs_says_so(tmp_path) -> None:
    report = check.check_layer(_laz(tmp_path / "tile.laz", crs="EPSG:7855"))
    assert "height_reference_unstated" in _codes(report) and report["verdict"] == "check the caveats"


def test_a_tile_without_any_crs_is_a_problem(tmp_path) -> None:
    report = check.check_layer(_laz(tmp_path / "tile.laz", crs=None))
    assert _codes(report) == ["crs_missing"]
    assert check.check_layer(tmp_path / "tile.laz", crs="EPSG:7855+5711")["vertical_crs"] == "AHD height"


def test_a_tile_labelled_with_the_wrong_crs_is_flagged(tmp_path) -> None:
    """Melbourne numbers labelled Oregon Lambert + NAVD88: a compound CRS has no area of use of its own."""
    report = check.check_layer(_laz(tmp_path / "tile.laz", crs="EPSG:2992+6360"))
    assert "outside_area_of_use" in _codes(report) and report["verdict"] == "problem"


def test_us_survey_feet_are_reported(tmp_path) -> None:
    report = check.check_layer(_laz(tmp_path / "tile.laz", crs="EPSG:7855+6360"))  # NAVD88 height (ftUS)
    finding = next(f for f in report["findings"] if f["code"] == "height_units")
    assert finding["evidence"]["metres_per_unit"] == pytest.approx(1200 / 3937)


def test_unclassified_points_are_noted(tmp_path) -> None:
    report = check.check_layer(_laz(tmp_path / "tile.laz", classify=False))
    assert "no_ground_class" in _codes(report)


def test_a_dem_is_read(tmp_path) -> None:
    report = check.check_layer(_dem(tmp_path / "dem.tif"))
    assert report["kind"] == "raster" and report["features"] == 6400
    assert "height_reference_unstated" in _codes(report)


def test_without_terrio_the_message_says_how_to_install(tmp_path) -> None:
    path = tmp_path / "tile.laz"
    path.write_bytes(b"")
    with patch.dict("sys.modules", {"terrio": None}):
        report = check.check_layer(path)
    assert _codes(report) == ["unreadable"] and "geospark-ai[pointcloud]" in report["findings"][0]["message"]


def test_kind_from_name() -> None:
    assert surface.kind("https://host/a.copc.laz") == "pointcloud" and surface.kind("dem.TIF") == "raster"
    assert surface.kind("marks.csv") is None
