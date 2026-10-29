"""Generate the synthetic demo data the engine runs on.

Writes three things to data/:
  trend_signals.csv  108 weeks of search / social / editorial signals per trend
  past_products.csv  a two-year history of past products with their attributes,
                     customer ratings and return rates
  weekly_sales.csv   16 weeks of unit sales per past product
  size_sales.csv     units sold per size per past product

Everything is seeded, so re-running produces identical files. Replace these
files with real exports (same columns) to run the engine on real data.

Run from the repo root:  python scripts/generate_synthetic_data.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.services import trends as trend_service  # noqa: E402

N_WEEKS = 108
N_PRODUCTS = 160
SALES_WEEKS = 16
rng = np.random.default_rng(config.RANDOM_SEED)


# --- 1. Trend signals -------------------------------------------------------

def logistic(t, centre, width, low, high):
    return low + (high - low) / (1 + math.exp(-(t - centre) / width))


def eased(t, centre, width, low, high, ease_from, ease_by):
    """Logistic rise, then a gentle decline after `ease_from` (a trend at its peak)."""
    value = logistic(t, centre, width, low, high)
    if t > ease_from:
        value -= ease_by * (t - ease_from) / (N_WEEKS - 1 - ease_from)
    return value


def bump(t, peak, sigma, low, height):
    return low + height * math.exp(-((t - peak) ** 2) / (2 * sigma**2))


TREND_SHAPES = {
    "trend-cherry-red": lambda t: logistic(t, 101, 6, 22, 84),
    "trend-chocolate-brown": lambda t: eased(t, 55, 7, 25, 80, 87, 6),
    "trend-powder-blue": lambda t: logistic(t, 104, 5, 28, 72),
    "trend-drop-waist": lambda t: logistic(t, 99, 7, 20, 80),
    "trend-barrel-leg": lambda t: eased(t, 45, 6, 22, 84, 82, 8),
    "trend-bubble-hem": lambda t: bump(t, 78, 14, 24, 52),
    "trend-exposed-lacing": lambda t: logistic(t, 102, 5, 18, 78),
    "trend-scarf-ties": lambda t: logistic(t, 97, 6, 24, 78),
    "trend-sheer-layers": lambda t: eased(t, 48, 7, 26, 80, 85, 7),
    "trend-crinkle-texture": lambda t: logistic(t, 100, 8, 30, 70),
}


def build_trend_signals() -> pd.DataFrame:
    weeks = trend_service.week_starts(N_WEEKS)
    rows = []
    for trend_id, shape in TREND_SHAPES.items():
        for i, week in enumerate(weeks):
            # Search lags true interest by a week; social leads by two;
            # editorial and runway coverage lead by about four.
            search = shape(i - 1) + rng.normal(0, 2.5)
            social = 40 * shape(i + 2) + rng.normal(0, 70)
            editorial = rng.poisson(max(shape(i + 4), 1) / 3)
            rows.append(
                {
                    "week": week.isoformat(),
                    "trend_id": trend_id,
                    "search_index": int(np.clip(round(search), 0, 100)),
                    "social_mentions": int(max(round(social), 0)),
                    "editorial_mentions": int(editorial),
                }
            )
    return pd.DataFrame(rows)


# --- 2. Product history -----------------------------------------------------

SILHOUETTES = {
    "dress": ["drop-waist", "bias-cut", "wrap", "column", "a-line", "bubble-hem"],
    "top": ["fitted", "relaxed", "cropped"],
    "jeans": ["barrel-leg", "straight-leg", "wide-leg", "skinny"],
    "skirt": ["drop-waist", "tube", "wrap", "bubble-hem", "bias-cut", "a-line"],
}
FABRICS = {
    "dress": ["cotton-jersey", "satin", "crinkle", "sheer", "lyocell", "poplin"],
    "top": ["poplin", "crinkle", "rib-knit", "sheer", "satin", "cotton-jersey"],
    "jeans": ["denim"],
    "skirt": ["satin", "crinkle", "cotton-jersey", "poplin", "sheer", "lyocell"],
}
DETAILS = {
    "dress": ["none", "exposed-lacing", "scarf-tie", "bow-strap", "sheer-panel", "statement-button", "ruching"],
    "top": ["none", "exposed-lacing", "scarf-tie", "sheer-panel", "statement-button", "ruching"],
    "jeans": ["none", "exposed-lacing", "contrast-stitch", "curved-seam", "statement-button"],
    "skirt": ["none", "exposed-lacing", "scarf-tie", "sheer-panel", "statement-button", "ruching"],
}
COLOURS = {
    "dress": ["black", "ecru", "cherry-red", "chocolate-brown", "powder-blue"],
    "top": ["black", "ecru", "cherry-red", "chocolate-brown", "powder-blue"],
    "jeans": ["mid-blue", "black", "ecru", "chocolate-brown"],
    "skirt": ["black", "ecru", "cherry-red", "chocolate-brown", "powder-blue"],
}
GARMENT_WEIGHTS = {"dress": 0.27, "top": 0.30, "jeans": 0.20, "skirt": 0.23}
BASE_UNITS = {"dress": 520, "top": 640, "jeans": 560, "skirt": 450}
STYLE_FACTOR = {"casual": 1.08, "classy": 1.0, "creative": 0.88}
SIZE_MIX = {
    "dress": [8, 23, 33, 24, 12],
    "top": [10, 26, 31, 22, 11],
    "jeans": [7, 21, 32, 26, 14],
    "skirt": [9, 25, 32, 23, 11],
}
SIZES = ["XS", "S", "M", "L", "XL"]
PRICE_BANDS = {"dress": (25, 45), "top": (15, 30), "jeans": (30, 45), "skirt": (20, 35)}


def season_factor(garment: str, week_of_year: int) -> float:
    if garment in ("dress", "skirt"):
        return 1 + 0.25 * math.sin(2 * math.pi * (week_of_year - 13) / 52)
    if garment == "top":
        return 1 + 0.12 * math.sin(2 * math.pi * (week_of_year - 13) / 52)
    return 1 + 0.15 * math.sin(2 * math.pi * (week_of_year - 26) / 52)


def lifecycle(h: int) -> float:
    raw = (h + 1) ** 0.7 * math.exp(-h / 7)
    peak = max((k + 1) ** 0.7 * math.exp(-k / 7) for k in range(SALES_WEEKS))
    return raw / peak


def pick(options: list[str], prefix: str, week_idx: int) -> str:
    """Choose an attribute, favouring ones with more interest at launch time."""
    scores = np.array([trend_service.attribute_series(f"{prefix}:{o}")[week_idx] for o in options])
    weights = (scores + 10) ** 1.5
    return str(rng.choice(options, p=weights / weights.sum()))


def build_history() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    weeks = trend_service.week_starts(N_WEEKS)
    garments = list(GARMENT_WEIGHTS)
    products, weekly, sizes = [], [], []

    for n in range(N_PRODUCTS):
        garment = str(rng.choice(garments, p=list(GARMENT_WEIGHTS.values())))
        launch = int(rng.integers(0, N_WEEKS - SALES_WEEKS))
        style = str(rng.choice(["casual", "classy", "creative"], p=[0.45, 0.35, 0.20]))
        attrs = {
            "silhouette": pick(SILHOUETTES[garment], "silhouette", launch),
            "colour": pick(COLOURS[garment], "colour", launch),
            "fabric": pick(FABRICS[garment], "fabric", launch),
            "detail": pick(DETAILS[garment], "detail", launch),
        }
        is_multiway = bool(rng.random() < 0.18)
        # Sustainable lines grow over the two years.
        is_sustainable = bool(rng.random() < 0.15 + 0.25 * launch / N_WEEKS)
        low, high = PRICE_BANDS[garment]
        price = float(round(rng.uniform(low, high) + (3 if is_sustainable else 0)) - 0.01)

        keys = [f"{k}:{v}" for k, v in attrs.items()]
        launch_interest = np.mean([trend_service.attribute_series(k)[launch] for k in keys])
        rating = np.clip(
            3.75 + 0.6 * (launch_interest - 50) / 50 + (0.18 if is_multiway else 0) + rng.normal(0, 0.12), 3.0, 4.9
        )
        return_rate = np.clip(0.21 - (0.05 if is_multiway else 0) - 0.04 * (rating - 4) + rng.normal(0, 0.02), 0.06, 0.4)
        product_id = f"P{n + 1:04d}"
        products.append(
            {
                "product_id": product_id,
                "launch_week": weeks[launch].isoformat(),
                "garment_type": garment,
                "style": style,
                **attrs,
                "is_multiway": is_multiway,
                "is_sustainable": is_sustainable,
                "price": price,
                "avg_rating": round(float(rating), 2),
                "return_rate": round(float(return_rate), 3),
            }
        )

        mid = sum(PRICE_BANDS[garment]) / 2
        total_units = 0
        for h in range(SALES_WEEKS):
            idx = launch + h
            interest = np.mean([trend_service.attribute_series(k)[idx] for k in keys])
            units = (
                BASE_UNITS[garment]
                * (mid / price) ** 0.8
                * STYLE_FACTOR[style]
                * (0.5 + interest / 100) ** 1.4
                * lifecycle(h)
                * season_factor(garment, weeks[idx].isocalendar()[1])
                * (1.12 if is_multiway else 1.0)
                * (1.04 if is_sustainable else 1.0)
                * rng.lognormal(0, 0.15)
            )
            units = int(round(units))
            total_units += units
            weekly.append(
                {"product_id": product_id, "week": weeks[idx].isoformat(), "weeks_since_launch": h, "units": units}
            )

        mix = np.array(SIZE_MIX[garment], dtype=float) * rng.lognormal(0, 0.08, size=5)
        split = np.round(total_units * mix / mix.sum()).astype(int)
        sizes.extend({"product_id": product_id, "size": s, "units": int(u)} for s, u in zip(SIZES, split))

    return pd.DataFrame(products), pd.DataFrame(weekly), pd.DataFrame(sizes)


def main() -> None:
    signals = build_trend_signals()
    signals.to_csv(config.TREND_SIGNALS_PATH, index=False)
    # The history is built from the same composite index the engine reads.
    trend_service.load_signals.cache_clear()
    trend_service.composite_index.cache_clear()

    products, weekly, sizes = build_history()
    products.to_csv(config.PRODUCTS_PATH, index=False)
    weekly.to_csv(config.WEEKLY_SALES_PATH, index=False)
    sizes.to_csv(config.SIZE_SALES_PATH, index=False)
    print(f"trend signals: {len(signals)} rows | products: {len(products)} | weekly sales: {len(weekly)} | size rows: {len(sizes)}")


if __name__ == "__main__":
    main()
