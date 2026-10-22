"""The themed API reference page and the grouping of endpoints by topic."""

from __future__ import annotations

from fastapi.testclient import TestClient

from geospark.api import OPENAPI_TAGS, app


def test_docs_page_is_the_themed_reference() -> None:
    page = TestClient(app).get("/docs")
    assert page.status_code == 200
    assert "API reference" in page.text and "/openapi.json" in page.text


def test_every_documented_endpoint_has_a_known_group() -> None:
    spec = TestClient(app).get("/openapi.json").json()
    known = {t["name"] for t in OPENAPI_TAGS}
    assert [t["name"] for t in spec["tags"]] == [t["name"] for t in OPENAPI_TAGS]
    for path, item in spec["paths"].items():
        for op in item.values():
            assert op.get("tags") and set(op["tags"]) <= known, path
    assert spec["paths"]["/api/v1/isochrone"]["post"]["tags"] == ["Routing"]


def test_main_requests_have_real_examples() -> None:
    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]
    assert schemas["DistanceRequest"]["example"]["lat_a"] == -37.818
    assert schemas["IsochroneRequest"]["example"]["minutes"] == [10, 20]
