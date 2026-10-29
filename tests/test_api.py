import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health_and_meta(client):
    assert client.get("/health").json()["status"] == "healthy"
    meta = client.get("/meta").json()
    assert "Synthetic" in meta["dataProvenance"]
    assert meta["model"]["algorithm"] == "RandomForestRegressor"


def test_trends_are_camel_case(client):
    trends = client.get("/trends").json()
    assert len(trends) == 10
    assert set(trends[0]) == {"id", "name", "category", "momentum", "status", "evidence", "weeklyScores"}
    rising = client.get("/trends", params={"status": "rising"}).json()
    assert rising and all(t["status"] == "rising" for t in rising)


def test_briefs_match_frontend_contract(client):
    briefs = client.get("/briefs").json()
    assert len(briefs) == 12
    expected = {
        "id", "title", "garmentType", "style", "baseDescription", "signatureDetail", "whyNow",
        "linkedTrendIds", "brandDnaFit", "targetCustomer", "priceRange", "isMultiway", "conversions",
        "isSustainable", "sustainabilityNotes", "confidence",
    }
    assert set(briefs[0]) == expected
    multiway = [b for b in briefs if b["isMultiway"]]
    assert set(multiway[0]["conversions"][0]) == {"from", "to", "steps"}


def test_brief_filters(client):
    jeans = client.get("/briefs", params={"garmentType": "jeans"}).json()
    assert len(jeans) == 3 and all(b["garmentType"] == "jeans" for b in jeans)
    mw = client.get("/briefs", params={"multiway": "true"}).json()
    assert mw and all(b["isMultiway"] for b in mw)


def test_brief_and_forecast_by_id(client):
    brief = client.get("/briefs").json()[0]
    assert client.get(f"/briefs/{brief['id']}").json()["id"] == brief["id"]
    fc = client.get(f"/forecasts/{brief['id']}").json()
    assert fc["briefId"] == brief["id"] and len(fc["weeklyDemand"]) == 16
    assert client.get("/briefs/nope").status_code == 404
    assert client.get("/forecasts/nope").status_code == 404


def test_overview(client):
    ov = client.get("/overview").json()
    assert ov["activeBriefs"] == 12 and len(ov["topBriefIds"]) == 3
