"""Trend signals: turn raw weekly source data into momentum, status and evidence.

Each tracked trend has three weekly sources (search interest, social mentions,
editorial/runway mentions). They are normalised and blended into one composite
interest index (0-100). Attributes that are not tied to a tracked trend
(e.g. black, straight-leg) use a stable evergreen baseline instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app import config

SOURCE_WEIGHTS = {"search_index": 0.45, "social_mentions": 0.35, "editorial_mentions": 0.20}
PROJECTION_DAMPING = 0.85
SLOPE_WINDOW = 8
SMOOTHING_SPAN = 4


@dataclass(frozen=True)
class TrendDefinition:
    id: str
    name: str
    category: str
    attributes: tuple[str, ...]


@dataclass
class TrendSummary:
    id: str
    name: str
    category: str
    momentum: int
    status: str
    evidence: list[str]
    weekly_scores: list[int]
    current_index: float
    projected_index_at_launch: float


def week_starts(n_weeks: int, as_of: date = config.AS_OF) -> list[date]:
    """The n Monday week-starts ending on the as-of week."""
    return [as_of - timedelta(weeks=n_weeks - 1 - i) for i in range(n_weeks)]


@lru_cache(maxsize=4)
def load_catalogue(path: Path = config.TREND_CATALOGUE_PATH) -> tuple[list[TrendDefinition], dict[str, float]]:
    raw = json.loads(path.read_text())
    trends = [
        TrendDefinition(t["id"], t["name"], t["category"], tuple(t["attributes"]))
        for t in raw["trends"]
    ]
    return trends, dict(raw["evergreen"])


def attribute_to_trend() -> dict[str, str]:
    trends, _ = load_catalogue()
    return {attr: t.id for t in trends for attr in t.attributes}


@lru_cache(maxsize=4)
def load_signals(path: Path = config.TREND_SIGNALS_PATH) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["week"])
    return df.sort_values(["trend_id", "week"]).reset_index(drop=True)


@lru_cache(maxsize=4)
def composite_index() -> pd.DataFrame:
    """Weekly composite interest index per trend (rows: weeks, columns: trend ids)."""
    df = load_signals().copy()
    blended = np.zeros(len(df))
    for column, weight in SOURCE_WEIGHTS.items():
        scale = df[column].max()
        blended += weight * (df[column] / scale * 100.0)
    df["composite"] = np.clip(blended, 0, 100)
    return df.pivot(index="week", columns="trend_id", values="composite").sort_index()


def attribute_series(attribute: str) -> np.ndarray:
    """Interest index over the full history for one design attribute."""
    _, evergreen = load_catalogue()
    weeks = composite_index().index
    trend_id = attribute_to_trend().get(attribute)
    if trend_id is not None:
        return composite_index()[trend_id].to_numpy()
    return np.full(len(weeks), float(evergreen.get(attribute, 50.0)))


def smooth(series: np.ndarray) -> np.ndarray:
    """Exponentially weighted moving average, to keep weekly noise out of slopes."""
    return pd.Series(series).ewm(span=SMOOTHING_SPAN, adjust=False).mean().to_numpy()


def project(series: np.ndarray, horizon: int) -> np.ndarray:
    """Damped linear extrapolation of the recent smoothed slope, `horizon` weeks ahead.

    Momentum is assumed to fade (damping 0.85/week), so a rising trend flattens
    out rather than climbing forever, and a fading one bottoms out.
    """
    smoothed = smooth(series)
    recent = smoothed[-SLOPE_WINDOW:]
    slope = float(np.polyfit(np.arange(len(recent)), recent, 1)[0])
    last = float(smoothed[-1])
    steps = np.cumsum(PROJECTION_DAMPING ** np.arange(1, horizon + 1))
    return np.clip(last + slope * steps, 5.0, 100.0)


def project_attribute(attribute: str, horizon: int) -> np.ndarray:
    _, evergreen = load_catalogue()
    if attribute in attribute_to_trend():
        return project(attribute_series(attribute), horizon)
    return np.full(horizon, float(evergreen.get(attribute, 50.0)))


def _pct_change(recent: float, prior: float) -> float:
    return 0.0 if prior <= 0 else (recent - prior) / prior * 100.0


def _social_lead_weeks(search: np.ndarray, social: np.ndarray, max_lag: int = 4) -> int:
    """Lag (in weeks) at which social mentions best anticipate search interest."""
    s = (search - search.mean()) / (search.std() or 1.0)
    m = (social - social.mean()) / (social.std() or 1.0)
    best_lag, best_corr = 0, -2.0
    for lag in range(0, max_lag + 1):
        a = m[: len(m) - lag] if lag else m
        b = s[lag:]
        corr = float(np.corrcoef(a, b)[0, 1])
        if corr > best_corr + 1e-9:
            best_lag, best_corr = lag, corr
    return best_lag


def classify(series: np.ndarray) -> tuple[int, str]:
    """Momentum (-100..100) and status from the composite series."""
    recent = series[-4:].mean()
    prior = series[-12:-4].mean()
    momentum = int(np.clip(round(_pct_change(recent, prior) * 1.2), -100, 100))
    smoothed = smooth(series)
    slope = float(np.polyfit(np.arange(6), smoothed[-6:], 1)[0])
    peak_52 = smoothed[-52:].max()

    if momentum <= -12 or (recent < 0.75 * peak_52 and slope < 0):
        status = "fading"
    elif momentum >= 12 and slope > 0:
        status = "rising"
    else:
        status = "peaking"
    return momentum, status


def _fmt_pct(value: float) -> str:
    return f"{'+' if value >= 0 else '−'}{abs(round(value))}%"


def summarise_trends(launch_horizon: int = config.LEAD_TIME_WEEKS) -> list[TrendSummary]:
    trends, _ = load_catalogue()
    signals = load_signals()
    composite = composite_index()
    summaries: list[TrendSummary] = []

    for trend in trends:
        series = composite[trend.id].to_numpy()
        raw = signals[signals["trend_id"] == trend.id]
        search = raw["search_index"].to_numpy(dtype=float)
        social = raw["social_mentions"].to_numpy(dtype=float)
        editorial = raw["editorial_mentions"].to_numpy(dtype=float)

        momentum, status = classify(series)
        projected = float(project(series, launch_horizon)[-1])
        current = float(series[-4:].mean())

        search_change = _pct_change(search[-4:].mean(), search[-12:-4].mean())
        social_change = _pct_change(social[-4:].mean(), social[-12:-4].mean())
        lead = _social_lead_weeks(search[-52:], social[-52:])
        ed_recent, ed_prior = int(editorial[-4:].sum()), int(editorial[-8:-4].sum())

        evidence = [
            f"Search interest {_fmt_pct(search_change)} over the last 4 weeks vs the 8 weeks before (now {round(search[-1])}/100).",
            f"Social mentions {_fmt_pct(social_change)} over the same period"
            + (f"; social has been leading search by about {lead} week{'s' if lead != 1 else ''}." if lead > 0 else "."),
            f"{ed_recent} editorial and runway mentions in the last 4 weeks, vs {ed_prior} in the 4 weeks before.",
        ]
        peak_idx = int(np.argmax(series))
        peak_week = composite.index[peak_idx]
        if status == "rising":
            evidence.append(
                f"Projected to keep building through the {launch_horizon}-week design-to-store lead time "
                f"(index {round(current)} now, about {round(projected)} at launch)."
            )
        elif status == "peaking":
            direction = "hold" if abs(projected - current) < 4 else ("edge up" if projected > current else "ease")
            evidence.append(
                f"At a plateau near its two-year high of {round(series.max())}; projected to {direction} "
                f"by launch (about {round(projected)})."
            )
        else:
            evidence.append(
                f"Down {round(100 - current / series.max() * 100)}% from its peak in {peak_week:%B %Y}; "
                f"projected at about {round(projected)} by launch."
            )

        summaries.append(
            TrendSummary(
                id=trend.id,
                name=trend.name,
                category=trend.category,
                momentum=momentum,
                status=status,
                evidence=evidence,
                weekly_scores=[int(round(v)) for v in series[-12:]],
                current_index=current,
                projected_index_at_launch=projected,
            )
        )
    return summaries
