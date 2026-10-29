from collections import Counter
from datetime import date, timedelta

import numpy as np
import pytest

from app import config, pipeline
from app.services import briefs as brief_engine
from app.services import demand, history, trends


@pytest.fixture(scope="module")
def snap():
    return pipeline.snapshot()


# --- Trends -----------------------------------------------------------------

def test_trend_contract(snap):
    assert len(snap.trends) == 10
    for t in snap.trends:
        assert -100 <= t.momentum <= 100
        assert len(t.weekly_scores) == 12
        assert all(0 <= s <= 100 for s in t.weekly_scores)
        assert len(t.evidence) >= 3


def test_trend_statuses_follow_the_signals(snap):
    by_id = {t.id: t for t in snap.trends}
    assert by_id["trend-bubble-hem"].status == "fading"
    assert by_id["trend-exposed-lacing"].status == "rising"
    assert by_id["trend-barrel-leg"].status == "peaking"


def test_projection_is_damped_and_bounded():
    rising = np.linspace(20, 90, 30)
    projected = trends.project(rising, 52)
    assert projected.max() <= 100
    # Damping: the second half of the horizon adds far less than the first.
    assert projected[25] - projected[0] > projected[-1] - projected[26]


# --- Briefs -----------------------------------------------------------------

def test_brief_mix(snap):
    assert len(snap.briefs) == 12
    per_type = Counter(b.garment_type for b in snap.briefs)
    assert per_type == {"dress": 3, "top": 3, "jeans": 3, "skirt": 3}
    assert sum(b.is_multiway for b in snap.briefs) >= config.MIN_MULTIWAY_BRIEFS
    assert sum(b.is_sustainable for b in snap.briefs) >= config.MIN_SUSTAINABLE_BRIEFS
    assert len({b.id for b in snap.briefs}) == 12


def test_brief_fields_are_complete(snap):
    trend_ids = {t.id for t in snap.trends}
    for b in snap.briefs:
        assert b.title and b.base_description and b.signature_detail and b.target_customer
        assert len(b.why_now) >= 3
        assert set(b.linked_trend_ids) <= trend_ids
        assert 0 <= b.brand_dna_fit <= 100 and 0 <= b.confidence <= 100
        assert b.price_range.startswith("$")
        if b.is_multiway:
            assert b.conversions and all(c.steps for c in b.conversions)
        else:
            assert b.conversions is None
        if b.is_sustainable:
            assert b.sustainability_notes
        else:
            assert b.sustainability_notes is None


def test_briefs_are_new_not_copies():
    candidates = brief_engine.score_candidates(brief_engine.generate_candidates())
    for c in brief_engine.select(candidates):
        shared, _ = history.max_shared_attributes(c.garment, c.style, c.attrs)
        assert shared <= config.MAX_SHARED_ATTRIBUTES


def test_one_signature_detail_and_varied_bases(snap):
    bases = [b.id.split("--")[0] for b in snap.briefs]
    assert len(set(bases)) == len(bases)
    details = Counter(b.id.split("--")[1] for b in snap.briefs)
    assert max(details.values()) <= brief_engine.MAX_DETAIL_USES


def test_fading_trend_is_not_recommended(snap):
    assert not any("trend-bubble-hem" in b.linked_trend_ids for b in snap.briefs)


def test_prices_stay_in_brand_band(snap):
    bands = brief_engine.load_brand()["priceBands"]
    for b in snap.briefs:
        low, high = (int(x) for x in b.price_range.strip("$").split("–"))
        band_low, band_high = bands[b.garment_type]
        assert band_low - 1 <= low and high <= band_high + 5


# --- Forecasts --------------------------------------------------------------

def test_forecast_contract(snap):
    assert [f.brief_id for f in snap.forecasts] == [b.id for b in snap.briefs]
    earliest_launch = config.AS_OF + timedelta(weeks=config.LEAD_TIME_WEEKS)
    for f in snap.forecasts:
        assert len(f.weekly_demand) == config.FORECAST_WEEKS
        assert date.fromisoformat(f.weekly_demand[0].week) >= earliest_launch
        assert sum(s.percent for s in f.size_split) == 100
        total = sum(w.units for w in f.weekly_demand)
        assert abs(f.recommended_units - total * (1 + config.SAFETY_STOCK)) <= 25
        assert f.stock_risk in {"low", "medium", "high"} and f.risk_reason


def test_demand_model_learns_something():
    metrics = demand.load_model()["metrics"]
    assert metrics["holdout_r2"] > 0.3


def test_rising_trend_raises_demand():
    base = dict(garment_type="dress", style="casual", price=32.0, is_multiway=False, is_sustainable=False)
    rising = demand.DemandProfile(**base, attributes=["silhouette:drop-waist", "colour:cherry-red", "fabric:cotton-jersey", "detail:exposed-lacing"])
    fading = demand.DemandProfile(**base, attributes=["silhouette:bubble-hem", "colour:black", "fabric:cotton-jersey", "detail:none"])
    assert demand.quick_demand(rising) > demand.quick_demand(fading)


def test_build_is_deterministic(snap):
    again = pipeline.build()
    assert [b.model_dump() for b in again.briefs] == [b.model_dump() for b in snap.briefs]
    assert [f.model_dump() for f in again.forecasts] == [f.model_dump() for f in snap.forecasts]
