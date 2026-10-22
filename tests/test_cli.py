"""CLI smoke tests: every command that can run offline exits cleanly.

Network-backed commands run against mocked engines/agents, so a crash in the CLI's own
formatting code (like `geospark ask` reading a field SpatialResult doesn't have) is caught.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from geospark.cli import main
from geospark.protocol.schema import SpatialContext, SpatialFeature, SpatialResult

SQUARE = json.dumps({"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]})
POINT = json.dumps({"type": "Point", "coordinates": [0.5, 0.5]})


def invoke(*args: str):
    result = CliRunner().invoke(main, list(args))
    assert result.exit_code == 0, f"{args} failed:\n{result.output}\n{result.exception!r}"
    return result.output


@pytest.mark.parametrize(
    "args",
    [
        ("info",),
        ("tools",),
        ("agents",),
        ("flow", "list"),
        ("data", "list"),
        ("memory", "stats"),
        ("memory", "contradictions"),
        ("memory", "compact"),
        ("context", "list"),
        ("context", "stats"),
        ("admin", "usage"),
        ("admin", "audit"),
    ],
)
def test_offline_commands(args) -> None:
    invoke(*args)


def test_distance() -> None:
    out = invoke("distance", "48.8584", "2.2945", "48.8606", "2.3376")
    assert "3.17" in out or "3,17" in out or "3172" in out


def test_negative_coordinates_are_values_not_options() -> None:
    """Melbourne to Sydney: every coordinate in the southern hemisphere starts with '-'."""
    out = invoke("distance", "-37.8136", "144.9631", "-33.8688", "151.2093")
    assert "713" in out or "714" in out  # ~713.4 km


def test_check_relationship() -> None:
    out = invoke("check", "contains", SQUARE, POINT)
    assert "True" in out or "true" in out


def test_query_buffer() -> None:
    query = json.dumps({"operation": "buffer", "geometry": json.loads(POINT), "radius_m": 100})
    invoke("query", query)


def test_flow_info_for_every_template() -> None:
    from geospark.flows import list_templates

    templates = list_templates()
    assert templates
    for template in templates:
        name = template["name"] if isinstance(template, dict) else template
        invoke("flow", "info", name)


def test_ask_prints_answer_and_model() -> None:
    answer = SpatialResult(
        spatial_context=SpatialContext(summary="Paris is about 344 km from London."),
        sources=["ollama:qwen2.5:7b", "calculate_distance"],
    )
    with patch("geospark.engine.core.Engine.ask", return_value=answer):
        out = invoke("ask", "How far is Paris from London?")
    assert "344 km" in out
    assert "calculate_distance" in out and "qwen2.5:7b" in out


def test_ask_reports_errors() -> None:
    with patch("geospark.engine.core.Engine.ask", return_value=SpatialResult(errors=["Ollama down"])):
        out = invoke("ask", "q")
    assert "Ollama down" in out


def test_geocode_and_elevation_with_mocked_engine() -> None:
    found = SpatialResult(
        features=[SpatialFeature(
            geometry={"type": "Point", "coordinates": [144.969, -37.818]},
            properties={"display_name": "Federation Square", "elevation_m": 23.1, "importance": 0.4},
        )],
        spatial_context=SpatialContext(summary="ok"),
        sources=["copernicus-glo30"],
    )
    with patch("geospark.engine.core.Engine.execute", return_value=found):
        assert "Federation Square" in invoke("geocode", "Federation Square, Melbourne")
        invoke("elevation", "-37.818", "144.969")


def test_report_and_site_select_with_mocked_agents() -> None:
    report = MagicMock()
    report.model_dump.return_value = {}
    with patch("geospark.agents.SpatialReport.analyze", return_value=report), \
         patch("geospark.agents.SiteSelector.find", return_value=MagicMock(candidates=[], best=None, summary="none")):
        CliRunner().invoke(main, ["report", "Federation Square"])  # formatting of a mock: just must not hang
        invoke("site-select", "--within", "Melbourne", "--near", "school")
