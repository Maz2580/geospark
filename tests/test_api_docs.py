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


def test_pages_link_versioned_assets_so_deploys_are_not_mixed_with_cached_files() -> None:
    import re

    from geospark.api import _ASSET_VERSION

    client = TestClient(app)
    for page in ("/", "/playground", "/guide", "/docs", "/status"):
        response = client.get(page)
        assert response.headers["cache-control"] == "no-cache"
        links = re.findall(r"""["'](/assets/[^"']+)["']""", response.text)
        assert links and all(link.endswith(f"?v={_ASSET_VERSION}") for link in links), (page, links)
    assert client.get(f"/assets/styles.css?v={_ASSET_VERSION}").status_code == 200
