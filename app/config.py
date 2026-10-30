"""Central configuration: paths, planning dates and model settings."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"

BRAND_DNA_PATH = DATA_DIR / "brand_dna.json"
DESIGN_LIBRARY_PATH = DATA_DIR / "design_library.json"
TREND_CATALOGUE_PATH = DATA_DIR / "trend_catalogue.json"
TREND_SIGNALS_PATH = DATA_DIR / "trend_signals.csv"
PRODUCTS_PATH = DATA_DIR / "past_products.csv"
WEEKLY_SALES_PATH = DATA_DIR / "weekly_sales.csv"
SIZE_SALES_PATH = DATA_DIR / "size_sales.csv"
MODEL_PATH = MODEL_DIR / "demand_model.joblib"

# The date the analysis is run "as of". Fixed so every output is reproducible;
# override with AS_OF=YYYY-MM-DD when the data is refreshed.
AS_OF = date.fromisoformat(os.getenv("AS_OF", "2026-10-26"))

# Design-to-store lead time. Briefs are planned for launches inside this window,
# so trends are judged on where they will be when the product lands, not today.
LEAD_TIME_WEEKS = int(os.getenv("LEAD_TIME_WEEKS", "12"))
LAUNCH_SEARCH_WEEKS = int(os.getenv("LAUNCH_SEARCH_WEEKS", "14"))
# Each week a launch waits past the lead time, the trend read gets older and less
# certain, so later launch weeks are discounted by this much per week.
LATE_LAUNCH_DISCOUNT = float(os.getenv("LATE_LAUNCH_DISCOUNT", "0.015"))

FORECAST_WEEKS = 16
RANDOM_SEED = 42

BRIEFS_PER_GARMENT = 3
MIN_MULTIWAY_BRIEFS = 5
MIN_SUSTAINABLE_BRIEFS = 4
# A brief may share at most this many of its 5 core attributes with any past
# product, so recommendations are new combinations rather than re-runs.
MAX_SHARED_ATTRIBUTES = 3


def cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
