import numpy as np
import pytest

from app import pipeline
from app.services import inventory


@pytest.fixture(scope="module")
def paths():
    # 300 "trees", 16 weeks, centred on 500 units/week with some disagreement.
    rng = np.random.default_rng(0)
    return rng.normal(500, 60, size=(300, 16)).clip(min=50)


def test_critical_ratio_formula():
    cu, co, cr, basis = inventory.unit_economics(30.0, "rising")
    econ = inventory.economics()
    assert cu == pytest.approx(30 * (1 - econ["unitCostShare"]))
    expected_co = 30 * (econ["unitCostShare"] + econ["handlingCostShare"] - econ["markdownRecoveryShare"]["rising"])
    assert co == pytest.approx(expected_co)
    assert cr == pytest.approx(cu / (cu + co))
    assert basis == "rising"


def test_trend_led_pieces_order_more_cautiously():
    ratios = {s: inventory.unit_economics(30.0, s)[2] for s in (None, "rising", "peaking", "fading")}
    assert ratios[None] > ratios["rising"] > ratios["peaking"] > ratios["fading"]


def test_simulation_is_centred_and_reproducible(paths):
    a = inventory.simulate_demand(paths, "rising", 0.2, "brief-a")
    b = inventory.simulate_demand(paths, "rising", 0.2, "brief-a")
    assert np.array_equal(a, b)
    assert a.mean() == pytest.approx(paths.sum(axis=1).mean(), rel=0.03)


def test_more_trend_uncertainty_widens_demand(paths):
    calm = inventory.simulate_demand(paths, None, 0.2, "x")
    risky = inventory.simulate_demand(paths, "fading", 0.2, "x")
    assert np.std(risky) > np.std(calm)


def test_order_quantity_maximises_expected_profit(paths):
    result = inventory.newsvendor(paths, 30.0, "peaking", 0.2, "brief-q")
    grid = np.arange(result.order_quantity - 2000, result.order_quantity + 2001, 50, dtype=float)
    profit = inventory.order_quantity_curve(paths, 30.0, "peaking", 0.2, "brief-q", grid)
    best = grid[int(np.argmax(profit))]
    # The critical-ratio quantile is the profit-maximising order, up to pack rounding.
    assert abs(best - result.order_quantity) <= 100


def test_stockout_probability_matches_critical_ratio(paths):
    result = inventory.newsvendor(paths, 30.0, "rising", 0.2, "brief-s")
    assert result.stockout_probability == pytest.approx(1 - result.critical_ratio, abs=0.02)


def test_evergreen_briefs_order_higher_in_their_range():
    snap = pipeline.snapshot()

    def position(f):
        r = f.demand_range
        return (f.recommended_units - r.p10) / (r.p90 - r.p10)

    evergreen = [position(f) for f in snap.forecasts if f.newsvendor.markdown_basis == "evergreen"]
    trend_led = [position(f) for f in snap.forecasts if f.newsvendor.markdown_basis != "evergreen"]
    assert evergreen and trend_led
    assert min(evergreen) > max(trend_led) - 0.05
