"""check_dataset: the silent coordinate errors found in a file, or between two files.

Each case is built from the same survey marks in Melbourne with a known mistake, and the checker must
name that mistake, and only that one. Clean files must come back with no problem.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from pyproj import Geod

from geospark import geodesy
from geospark.io import check, layers

G = Geod(ellps="GRS80")
MARKS_GDA2020_MGA55 = [(321242.536, 5812468.239), (320498.198, 5814694.604), (322000.0, 5813000.0),
                       (319500.0, 5811800.0), (323100.0, 5815200.0)]


def _csv(path: Path, rows: list[tuple[float, float]], extra: dict[str, list] | None = None, xy=("x", "y")) -> Path:
    cols = ["id", *xy, *(extra or {})]
    lines = [",".join(cols)]
    for i, (x, y) in enumerate(rows):
        lines.append(",".join([str(i), repr(x), repr(y), *[str(v[i]) for v in (extra or {}).values()]]))
    path.write_text("\n".join(lines) + "\n")
    return path


def _codes(report) -> list[str]:
    return [f["code"] for f in report["findings"]]


# --- the bug this work found in GeoSpark itself --------------------------------------------------

def test_gda94_and_gda2020_files_of_the_same_marks_load_to_the_same_place(tmp_path) -> None:
    """They used to end up 1.55 m apart: PROJ's GDA94 -> WGS 84 default is a null transformation."""
    gda94 = geodesy.transform("EPSG:7855", "EPSG:28355", [list(p) for p in MARKS_GDA2020_MGA55]).coordinates
    a = layers.load_layer(_csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55), crs="EPSG:7855")
    b = layers.load_layer(_csv(tmp_path / "b.csv", [tuple(p) for p in gda94]), crs="EPSG:28355")
    worst = max(G.inv(p.x, p.y, q.x, q.y)[2] for p, q in zip(a.geometries, b.geometries, strict=True))
    assert worst < 0.005


# --- two files --------------------------------------------------------------------------------------

def test_a_gda94_layer_labelled_gda2020_is_named(tmp_path) -> None:
    gda94_values = geodesy.transform("EPSG:7855", "EPSG:28355", [list(p) for p in MARKS_GDA2020_MGA55]).coordinates
    a = _csv(tmp_path / "parcels.csv", MARKS_GDA2020_MGA55)
    b = _csv(tmp_path / "pipes.csv", [tuple(p) for p in gda94_values])  # GDA94 numbers...
    report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:7855")  # ...labelled GDA2020
    finding = next(f for f in report["findings"] if f["code"] == "gda94_labelled_as_gda2020")
    assert finding["evidence"]["gda94_layer"] == "pipes.csv"
    assert 1.4 < report["offset"]["size_m"] < 1.7
    assert report["verdict"] == "problem"


def test_correctly_labelled_layers_are_consistent(tmp_path) -> None:
    gda94_values = geodesy.transform("EPSG:7855", "EPSG:28355", [list(p) for p in MARKS_GDA2020_MGA55]).coordinates
    a = _csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55)
    b = _csv(tmp_path / "b.csv", [tuple(p) for p in gda94_values])
    report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:28355")
    assert _codes(report) == ["consistent"] and report["verdict"] == "no issues found"


def test_the_wrong_mga_zone_is_found_by_reading_the_numbers_in_the_neighbouring_zones(tmp_path) -> None:
    lonlat = geodesy.transform("EPSG:7855", "EPSG:7844", [list(p) for p in MARKS_GDA2020_MGA55]).coordinates
    zone54 = geodesy.transform("EPSG:7844", "EPSG:7854", lonlat).coordinates  # true zone-54 numbers...
    a = _csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55)
    b = _csv(tmp_path / "b.csv", [tuple(p) for p in zone54])
    report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:7855")  # ...labelled zone 55
    finding = next(f for f in report["findings"] if f["code"] == "layer_mislabelled")
    assert "MGA zone 54" in finding["evidence"]["fix"]


def test_coordinates_in_feet_are_found(tmp_path) -> None:
    a = _csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55)
    b = _csv(tmp_path / "b.csv", [(x / 0.3048, y / 0.3048) for x, y in MARKS_GDA2020_MGA55])
    report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:7855")
    finding = next(f for f in report["findings"] if f["code"] == "layer_mislabelled")
    assert "international feet" in finding["evidence"]["fix"]


def test_a_plate_motion_epoch_difference_is_named(tmp_path) -> None:
    lonlat = geodesy.transform("EPSG:7855", "EPSG:7843", [[*p, 0.0] for p in MARKS_GDA2020_MGA55]).coordinates
    itrf_2026 = geodesy.transform("EPSG:7843", "EPSG:7912", lonlat, epoch=2026.8).coordinates  # GNSS today...
    a = _csv(tmp_path / "a.csv", [tuple(p[:2]) for p in lonlat], xy=("lon", "lat"))
    b = _csv(tmp_path / "b.csv", [tuple(p[:2]) for p in itrf_2026], xy=("lon", "lat"))
    report = check.compare_layers(a, b, crs_a="EPSG:7844", crs_b="EPSG:7844")  # ...labelled GDA2020
    finding = next(f for f in report["findings"] if f["code"] == "epoch_difference")
    assert 6.0 < finding["evidence"]["years"] < 7.6


def test_ellipsoidal_heights_against_ahd_heights_are_named(tmp_path) -> None:
    a = _csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55, {"height": [35.0, 36.0, 37.0, 38.0, 39.0]})
    b = _csv(tmp_path / "b.csv", MARKS_GDA2020_MGA55, {"height": [39.74, 40.74, 41.74, 42.74, 43.74]})
    with patch.object(geodesy, "convert_height", return_value={"separation_m": 4.743}):
        report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:7855")
    finding = next(f for f in report["findings"] if f["code"] == "ellipsoidal_vs_ahd")
    assert finding["evidence"]["median_dz_m"] == pytest.approx(4.74, abs=0.01)


def test_an_offset_with_no_known_cause_is_reported_unexplained(tmp_path) -> None:
    a = _csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55)
    b = _csv(tmp_path / "b.csv", [(x + 3.0, y - 0.5) for x, y in MARKS_GDA2020_MGA55])
    report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:7855")
    assert "unexplained_offset" in _codes(report)
    assert "gda94_labelled_as_gda2020" not in _codes(report)


# --- one file -----------------------------------------------------------------------------------------

def test_a_clean_projected_file_has_no_problem(tmp_path) -> None:
    report = check.check_layer(_csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55), crs="EPSG:7855")
    assert report["verdict"] == "no issues found" and report["datum"].startswith("Geocentric Datum of Australia 2020")


def test_projected_numbers_labelled_as_degrees(tmp_path) -> None:
    report = check.check_layer(_csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55), crs="EPSG:7844")
    assert _codes(report) == ["projected_values_in_geographic_crs"]


def test_degree_numbers_labelled_as_projected(tmp_path) -> None:
    report = check.check_layer(_csv(tmp_path / "a.csv", [(144.97, -37.82), (144.96, -37.80), (144.95, -37.81)]),
                               crs="EPSG:7855")
    assert _codes(report) == ["degree_values_in_projected_crs"]


def test_swapped_latitude_and_longitude(tmp_path) -> None:
    rows = [(-37.82, 144.97), (-37.80, 144.96), (-37.81, 144.95)]
    report = check.check_layer(_csv(tmp_path / "a.csv", rows, xy=("lon", "lat")), crs="EPSG:7844")
    assert _codes(report) == ["lat_lon_swapped"]


def test_a_csv_says_its_crs_was_assumed_and_australian_wgs84_is_flagged(tmp_path) -> None:
    rows = [(144.97, -37.82), (144.96, -37.80), (144.95, -37.81)]
    report = check.check_layer(_csv(tmp_path / "a.csv", rows, xy=("longitude", "latitude")))
    assert {"crs_assumed", "australian_data_in_wgs84"} <= set(_codes(report))


def test_heights_without_a_reference_are_flagged(tmp_path) -> None:
    report = check.check_layer(_csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55, {"height": [1, 2, 3, 4, 5]}), crs="EPSG:7855")
    assert "height_reference_unstated" in _codes(report)
    named = check.check_layer(_csv(tmp_path / "b.csv", MARKS_GDA2020_MGA55, {"ahd": [1, 2, 3, 4, 5]}), crs="EPSG:7855")
    assert "height_reference_from_name" in _codes(named) and "height_reference_unstated" not in _codes(named)


def test_points_outside_the_crs_area_are_flagged(tmp_path) -> None:
    perth = [(115.86, -31.95), (115.85, -31.96), (115.87, -31.94)]
    lonlat = geodesy.transform("EPSG:7844", "EPSG:7855", [list(p) for p in perth]).coordinates  # Perth in zone 55
    report = check.check_layer(_csv(tmp_path / "a.csv", [tuple(p) for p in lonlat]), crs="EPSG:7855")
    assert "outside_area_of_use" in _codes(report)


def test_a_shapefile_without_a_prj_is_a_finding_not_an_exception(tmp_path) -> None:
    report = check.check_layer(_csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55))  # x/y columns, no crs
    assert _codes(report) == ["crs_missing"] and report["verdict"] == "problem"


def test_close_together_features_make_nearest_neighbour_pairing_uncertain(tmp_path) -> None:
    dense = [(321000.0 + 1.0 * i, 5812000.0) for i in range(6)]  # 1 m apart; layer B shifted 1.55 m
    gda94 = geodesy.transform("EPSG:7855", "EPSG:28355", [list(p) for p in dense]).coordinates
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("x,y\n" + "".join(f"{x},{y}\n" for x, y in dense))
    b.write_text("x,y\n" + "".join(f"{x},{y}\n" for x, y in gda94))
    report = check.compare_layers(a, b, crs_a="EPSG:7855", crs_b="EPSG:7855")
    assert "pairing_uncertain" in _codes(report)


def test_cli_exit_code_signals_a_problem(tmp_path) -> None:
    from click.testing import CliRunner

    from geospark.cli import main

    gda94 = geodesy.transform("EPSG:7855", "EPSG:28355", [list(p) for p in MARKS_GDA2020_MGA55]).coordinates
    a = _csv(tmp_path / "a.csv", MARKS_GDA2020_MGA55)
    b = _csv(tmp_path / "b.csv", [tuple(p) for p in gda94])
    bad = CliRunner().invoke(main, ["layer", "check", str(b), "--crs", "EPSG:7855", "--against", str(a),
                                    "--against-crs", "EPSG:7855"])
    assert bad.exit_code == 2 and "GDA94" in bad.output
    good = CliRunner().invoke(main, ["layer", "check", str(a), "--crs", "EPSG:7855"])
    assert good.exit_code == 0 and "no issues found" in good.output
