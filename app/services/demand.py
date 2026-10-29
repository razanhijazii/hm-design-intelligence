"""Demand model: weekly unit sales from product attributes, trend interest and season.

A RandomForestRegressor is trained on the past-product history. To forecast a
new brief, the linked trends are projected forward over the design-to-store lead
time, the model predicts week-by-week demand for several candidate launch weeks,
and the launch week with the highest total demand is recommended (later weeks
are discounted slightly, since the trend read gets older). Safety stock
(15%, as in the Hermès model) is added on top of the forecast.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_percentage_error, r2_score

from app import config
from app.services import history, trends

logger = logging.getLogger(__name__)

GARMENTS = ["dress", "top", "jeans", "skirt"]
STYLES = ["casual", "classy", "creative"]
FEATURES = (
    [f"garment_{g}" for g in GARMENTS]
    + [f"style_{s}" for s in STYLES]
    + ["price", "is_multiway", "is_sustainable", "trend_interest", "weeks_since_launch", "season_sin", "season_cos"]
)


@dataclass
class DemandProfile:
    garment_type: str
    style: str
    price: float
    is_multiway: bool
    is_sustainable: bool
    attributes: list[str]  # prefixed keys, e.g. "colour:cherry-red"


@dataclass
class DemandForecast:
    launch_week: date
    weeks: list[date]
    units: list[int]
    total_units: int
    recommended_units: int
    cv: float  # forecast spread across trees, as a fraction of the total


def _season(week_start: date) -> tuple[float, float]:
    w = week_start.isocalendar()[1]
    return math.sin(2 * math.pi * w / 52), math.cos(2 * math.pi * w / 52)


def _row(garment, style, price, multiway, sustainable, interest, h, week_start) -> list[float]:
    s, c = _season(week_start)
    return (
        [1.0 if garment == g else 0.0 for g in GARMENTS]
        + [1.0 if style == st else 0.0 for st in STYLES]
        + [price, float(multiway), float(sustainable), interest, float(h), s, c]
    )


def training_frame() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Features, target and launch-week order (for a time-based split)."""
    products = history.load_products().set_index("product_id")
    weekly = history.load_weekly_sales()
    weeks = trends.composite_index().index
    week_pos = {ts.date(): i for i, ts in enumerate(weeks)}

    series_cache: dict[str, np.ndarray] = {}

    def interest(product, week_idx: int) -> float:
        vals = []
        for col in history.ATTRIBUTE_COLUMNS:
            key = f"{col}:{product[col]}"
            if key not in series_cache:
                series_cache[key] = trends.attribute_series(key)
            vals.append(series_cache[key][week_idx])
        return float(np.mean(vals))

    X, y, launch = [], [], []
    for row in weekly.itertuples(index=False):
        p = products.loc[row.product_id]
        wk = row.week.date()
        X.append(
            _row(p["garment_type"], p["style"], p["price"], p["is_multiway"], p["is_sustainable"],
                 interest(p, week_pos[wk]), row.weeks_since_launch, wk)
        )
        y.append(row.units)
        launch.append(p["launch_week"].toordinal())
    return np.array(X), np.array(y, dtype=float), np.array(launch)


def train() -> dict:
    X, y, launch = training_frame()
    # Hold out the most recent 20% of launches, so the score reflects
    # forecasting products the model has not seen yet.
    cutoff = np.quantile(launch, 0.8)
    train_mask = launch <= cutoff
    params = dict(n_estimators=300, min_samples_leaf=3, random_state=config.RANDOM_SEED, n_jobs=-1)

    holdout = RandomForestRegressor(**params).fit(X[train_mask], y[train_mask])
    pred = holdout.predict(X[~train_mask])
    metrics = {
        "holdout_r2": round(float(r2_score(y[~train_mask], pred)), 3),
        "holdout_mape": round(float(mean_absolute_percentage_error(y[~train_mask], pred)), 3),
        "train_rows": int(train_mask.sum()),
        "holdout_rows": int((~train_mask).sum()),
    }
    model = RandomForestRegressor(**params).fit(X, y)
    bundle = {
        "model": model,
        "features": FEATURES,
        "metrics": metrics,
        "sklearn_version": sklearn.__version__,
        "algorithm": "RandomForestRegressor",
    }
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, config.MODEL_PATH)
    return bundle


@lru_cache(maxsize=1)
def load_model() -> dict:
    """Load the trained model, retraining if it is missing or was built with a
    different scikit-learn version or feature set."""
    if config.MODEL_PATH.exists():
        try:
            bundle = joblib.load(config.MODEL_PATH)
            if bundle.get("features") == FEATURES and bundle.get("sklearn_version") == sklearn.__version__:
                return bundle
            logger.info("Model artifact is stale; retraining")
        except Exception:  # noqa: BLE001 - any unreadable artifact is retrained
            logger.exception("Could not load model artifact; retraining")
    return train()


def _tree_predictions(model: RandomForestRegressor, X: np.ndarray) -> np.ndarray:
    return np.stack([tree.predict(X) for tree in model.estimators_])


def _profile_rows(profile: DemandProfile, offset: int, projections: dict[str, np.ndarray]) -> np.ndarray:
    rows = []
    for h in range(config.FORECAST_WEEKS):
        horizon = offset + h
        interest = float(np.mean([projections[a][horizon] for a in profile.attributes]))
        week_start = config.AS_OF + timedelta(weeks=horizon + 1)
        rows.append(_row(profile.garment_type, profile.style, profile.price, profile.is_multiway,
                         profile.is_sustainable, interest, h, week_start))
    return np.array(rows)


@lru_cache(maxsize=256)
def _projection(attribute: str) -> np.ndarray:
    horizon = config.LEAD_TIME_WEEKS + config.LAUNCH_SEARCH_WEEKS + config.FORECAST_WEEKS + 1
    return trends.project_attribute(attribute, horizon)


def _projections(attributes: list[str]) -> dict[str, np.ndarray]:
    return {a: _projection(a) for a in attributes}


def quick_demand_batch(profiles: list[DemandProfile]) -> list[float]:
    """Total 16-week demand at the earliest possible launch, for many profiles in
    one model call (used to rank candidates)."""
    if not profiles:
        return []
    model = load_model()["model"]
    offset = config.LEAD_TIME_WEEKS - 1
    rows = np.vstack([_profile_rows(p, offset, _projections(p.attributes)) for p in profiles])
    preds = model.predict(rows).reshape(len(profiles), config.FORECAST_WEEKS)
    return [float(v) for v in preds.sum(axis=1)]


def quick_demand(profile: DemandProfile) -> float:
    return quick_demand_batch([profile])[0]


def forecast(profile: DemandProfile) -> DemandForecast:
    model = load_model()["model"]
    projections = _projections(profile.attributes)

    best = None
    for offset in range(config.LEAD_TIME_WEEKS - 1, config.LEAD_TIME_WEEKS - 1 + config.LAUNCH_SEARCH_WEEKS):
        rows = _profile_rows(profile, offset, projections)
        per_tree = _tree_predictions(model, rows)
        total = float(per_tree.mean(axis=0).sum())
        weeks_late = offset - (config.LEAD_TIME_WEEKS - 1)
        score = total * (1 - config.LATE_LAUNCH_DISCOUNT * weeks_late)
        if best is None or score > best[0]:
            best = (score, offset, per_tree)

    _, offset, per_tree = best
    weekly = per_tree.mean(axis=0)
    tree_totals = per_tree.sum(axis=1)
    cv = float(tree_totals.std() / tree_totals.mean())
    launch = config.AS_OF + timedelta(weeks=offset + 1)
    units = [int(5 * round(u / 5)) for u in weekly]
    return DemandForecast(
        launch_week=launch,
        weeks=[launch + timedelta(weeks=h) for h in range(config.FORECAST_WEEKS)],
        units=units,
        total_units=int(sum(units)),
        recommended_units=int(50 * round(sum(units) * (1 + config.SAFETY_STOCK) / 50)),
        cv=cv,
    )


def model_info() -> dict:
    bundle = load_model()
    return {
        "algorithm": bundle["algorithm"],
        "features": bundle["features"],
        "metrics": bundle["metrics"],
        "safetyStock": config.SAFETY_STOCK,
        "sklearnVersion": bundle["sklearn_version"],
    }


def frame_for_debug(profile: DemandProfile) -> pd.DataFrame:  # pragma: no cover - notebook helper
    rows = _profile_rows(profile, config.LEAD_TIME_WEEKS - 1, _projections(profile.attributes))
    return pd.DataFrame(rows, columns=FEATURES)
