"""Past product performance: what customers bought, loved and kept.

Used for two things: training the demand model, and the "why" behind briefs
(which attributes sold above their category average and were rated highly).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from app import config

ATTRIBUTE_COLUMNS = ("silhouette", "colour", "fabric", "detail")
SHRINKAGE = 5  # pseudo-observations pulling small groups toward the average


@dataclass(frozen=True)
class AttributeStats:
    n: int
    sell_through_index: float  # units vs the garment-type average (1.0 = average)
    rating: float


@lru_cache(maxsize=1)
def load_products() -> pd.DataFrame:
    return pd.read_csv(config.PRODUCTS_PATH, parse_dates=["launch_week"])


@lru_cache(maxsize=1)
def load_weekly_sales() -> pd.DataFrame:
    return pd.read_csv(config.WEEKLY_SALES_PATH, parse_dates=["week"])


@lru_cache(maxsize=1)
def load_size_sales() -> pd.DataFrame:
    return pd.read_csv(config.SIZE_SALES_PATH)


@lru_cache(maxsize=1)
def product_performance() -> pd.DataFrame:
    """One row per past product with total units and a sell-through index."""
    products = load_products().copy()
    totals = load_weekly_sales().groupby("product_id")["units"].sum().rename("total_units")
    products = products.merge(totals, on="product_id")
    type_mean = products.groupby("garment_type")["total_units"].transform("mean")
    products["sell_through_index"] = products["total_units"] / type_mean
    return products


@lru_cache(maxsize=1)
def attribute_stats() -> dict[str, AttributeStats]:
    """Shrunk performance per attribute key, e.g. 'colour:chocolate-brown'."""
    perf = product_performance()
    global_rating = float(perf["avg_rating"].mean())
    stats: dict[str, AttributeStats] = {}
    for column in ATTRIBUTE_COLUMNS:
        for value, group in perf.groupby(column):
            n = len(group)
            sti = (group["sell_through_index"].sum() + SHRINKAGE * 1.0) / (n + SHRINKAGE)
            rating = (group["avg_rating"].sum() + SHRINKAGE * global_rating) / (n + SHRINKAGE)
            stats[f"{column}:{value}"] = AttributeStats(n=n, sell_through_index=float(sti), rating=float(rating))
    return stats


@lru_cache(maxsize=1)
def global_rating() -> float:
    return float(product_performance()["avg_rating"].mean())


@lru_cache(maxsize=1)
def flag_uplift() -> dict[str, dict[str, float]]:
    """Sell-through and return-rate difference for multiway and sustainable pieces."""
    perf = product_performance()
    out = {}
    for flag in ("is_multiway", "is_sustainable"):
        yes, no = perf[perf[flag]], perf[~perf[flag]]
        out[flag] = {
            "sell_through_ratio": float(yes["sell_through_index"].mean() / no["sell_through_index"].mean()),
            "return_rate_points": float((no["return_rate"].mean() - yes["return_rate"].mean()) * 100),
            "n": int(len(yes)),
        }
    return out


@lru_cache(maxsize=4)
def size_split(garment_type: str) -> list[tuple[str, int]]:
    """Share of units by size for a garment type, as whole percents summing to 100."""
    sizes = load_size_sales().merge(load_products()[["product_id", "garment_type"]], on="product_id")
    sizes = sizes[sizes["garment_type"] == garment_type]
    order = ["XS", "S", "M", "L", "XL"]
    totals = sizes.groupby("size")["units"].sum().reindex(order).fillna(0)
    shares = totals / totals.sum() * 100
    floored = np.floor(shares).astype(int)
    # Largest-remainder rounding so the percents add up to exactly 100.
    remainder = 100 - int(floored.sum())
    for size in (shares - floored).sort_values(ascending=False).index[:remainder]:
        floored[size] += 1
    return [(size, int(floored[size])) for size in order]


def max_shared_attributes(garment_type: str, style: str, attrs: dict[str, str]) -> tuple[int, str | None]:
    """Most core attributes (silhouette, colour, fabric, detail, style) a candidate
    shares with any past product of the same garment type, and which product."""
    products = load_products()
    same_type = products[products["garment_type"] == garment_type]
    if same_type.empty:
        return 0, None
    shared = (same_type["style"] == style).astype(int)
    for column in ATTRIBUTE_COLUMNS:
        shared = shared + (same_type[column] == attrs[column]).astype(int)
    idx = int(shared.to_numpy().argmax())
    return int(shared.iloc[idx]), str(same_type.iloc[idx]["product_id"])


def similar_history_count(garment_type: str, attrs: dict[str, str], min_shared: int = 2) -> int:
    """How many past products share at least `min_shared` attributes: the data
    support behind a brief's forecast."""
    products = load_products()
    same_type = products[products["garment_type"] == garment_type]
    shared = sum((same_type[c] == attrs[c]).astype(int) for c in ATTRIBUTE_COLUMNS)
    return int((shared >= min_shared).sum())
