"""How many to make: a newsvendor model on simulated demand.

A fashion buy is a one-shot order under uncertain demand: order too few and you
lose full-price sales, order too many and the rest is marked down. The
newsvendor model sets the order quantity at the point where those two costs
balance:

    underage cost  Cu = price - unit cost              (margin lost per missed sale)
    overage cost   Co = unit cost + handling - markdown value   (loss per unsold unit)
    critical ratio CR = Cu / (Cu + Co)
    order quantity Q  = the CR-quantile of the demand distribution

The demand distribution is simulated, not assumed. Each of N simulated seasons
combines three sources of uncertainty:

  1. model uncertainty: one of the random forest's trees is drawn at random,
     giving a full 16-week demand path (the trees disagree where data is thin);
  2. trend uncertainty: one season-wide shock, larger for trends that are
     peaking or fading, because the trend may not land where it is projected;
  3. weekly noise: week-to-week variation, sized from the model's own residuals
     on held-out launches.

Markdown value depends on what happens to the trend after the season. An
evergreen piece can be carried over, so unsold stock keeps more of its value; a
piece tied to a fading trend has to be cleared deeply. So trend-led pieces get a
lower critical ratio and a more cautious order.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from app import config

STATUS_ORDER = {"rising": 0, "peaking": 1, "fading": 2}


@dataclass
class NewsvendorResult:
    order_quantity: int
    critical_ratio: float
    underage_cost: float
    overage_cost: float
    p10: int
    p50: int
    p90: int
    mean_demand: float
    stockout_probability: float
    expected_sell_through: float
    expected_leftover: int
    expected_profit: float
    simulations: int
    markdown_basis: str


@lru_cache(maxsize=1)
def economics() -> dict:
    brand = json.loads(config.BRAND_DNA_PATH.read_text())
    return brand["inventoryEconomics"]


def worst_status(statuses: list[str]) -> str | None:
    return max(statuses, key=lambda s: STATUS_ORDER[s]) if statuses else None


def unit_economics(price: float, trend_status: str | None) -> tuple[float, float, float, str]:
    """Underage cost, overage cost, critical ratio and what set the markdown value."""
    econ = economics()
    basis = trend_status or "evergreen"
    unit_cost = econ["unitCostShare"] * price
    handling = econ["handlingCostShare"] * price
    markdown_value = econ["markdownRecoveryShare"][basis] * price
    cu = price - unit_cost
    co = unit_cost + handling - markdown_value
    return cu, co, cu / (cu + co), basis


def simulate_demand(
    tree_paths: np.ndarray,
    trend_status: str | None,
    residual_sigma: float,
    seed_key: str,
    n: int | None = None,
) -> np.ndarray:
    """Total season demand in each of n simulated seasons.

    tree_paths: (n_trees, n_weeks) weekly demand predicted by each tree.
    """
    econ = economics()
    n = n or econ["simulations"]
    rng = np.random.default_rng(zlib.crc32(seed_key.encode()) + config.RANDOM_SEED)
    trees = rng.integers(0, tree_paths.shape[0], size=n)
    paths = tree_paths[trees]

    # Mean-one lognormal shocks, so the simulation is centred on the forecast.
    trend_sigma = econ["trendShockSigma"][trend_status or "evergreen"]
    trend_shock = rng.lognormal(-trend_sigma**2 / 2, trend_sigma, size=(n, 1))
    weekly_noise = rng.lognormal(-residual_sigma**2 / 2, residual_sigma, size=paths.shape)
    return (paths * trend_shock * weekly_noise).sum(axis=1)


def newsvendor(
    tree_paths: np.ndarray,
    price: float,
    trend_status: str | None,
    residual_sigma: float,
    seed_key: str,
) -> NewsvendorResult:
    cu, co, cr, basis = unit_economics(price, trend_status)
    demand = simulate_demand(tree_paths, trend_status, residual_sigma, seed_key)

    q = float(np.quantile(demand, cr))
    q = float(50 * round(q / 50))  # buy in packs of 50
    sold = np.minimum(demand, q)
    leftover = q - sold
    profit = cu * sold - co * leftover

    p10, p50, p90 = (int(round(v, -1)) for v in np.quantile(demand, [0.1, 0.5, 0.9]))
    return NewsvendorResult(
        order_quantity=int(q),
        critical_ratio=round(cr, 3),
        underage_cost=round(cu, 2),
        overage_cost=round(co, 2),
        p10=p10,
        p50=p50,
        p90=p90,
        mean_demand=float(demand.mean()),
        stockout_probability=round(float((demand > q).mean()), 3),
        expected_sell_through=round(float(sold.mean() / q), 3) if q else 0.0,
        expected_leftover=int(round(leftover.mean(), -1)),
        expected_profit=round(float(profit.mean()), 0),
        simulations=len(demand),
        markdown_basis=basis,
    )


def order_quantity_curve(
    tree_paths: np.ndarray, price: float, trend_status: str | None, residual_sigma: float, seed_key: str,
    quantities: np.ndarray,
) -> np.ndarray:
    """Expected profit at each candidate order quantity (used in tests and analysis)."""
    cu, co, _, _ = unit_economics(price, trend_status)
    demand = simulate_demand(tree_paths, trend_status, residual_sigma, seed_key)
    sold = np.minimum(demand[None, :], quantities[:, None])
    return (cu * sold - co * (quantities[:, None] - sold)).mean(axis=1)
