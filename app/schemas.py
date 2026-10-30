"""API contracts.

These mirror the TypeScript types in the Lovable frontend (Trend, DesignBrief,
Forecast) field for field, serialised in camelCase, so the frontend can swap its
mock data for this API without changing any component.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

TrendCategory = Literal["colour", "silhouette", "detail", "fabric"]
TrendStatus = Literal["rising", "peaking", "fading"]
GarmentType = Literal["dress", "top", "jeans", "skirt"]
Style = Literal["casual", "classy", "creative"]
StockRisk = Literal["low", "medium", "high"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class Trend(ApiModel):
    id: str
    name: str
    category: TrendCategory
    momentum: int = Field(ge=-100, le=100)
    status: TrendStatus
    evidence: list[str]
    weekly_scores: list[int] = Field(min_length=12, max_length=12)


class Conversion(ApiModel):
    # "from" is a Python keyword, so the field is from_ and aliased explicitly.
    from_: str = Field(alias="from")
    to: str
    steps: list[str]


class DesignBrief(ApiModel):
    id: str
    title: str
    garment_type: GarmentType
    style: Style
    base_description: str
    signature_detail: str
    why_now: list[str]
    linked_trend_ids: list[str]
    brand_dna_fit: int = Field(ge=0, le=100)
    target_customer: str
    price_range: str
    is_multiway: bool
    conversions: Optional[list[Conversion]] = None
    is_sustainable: bool
    sustainability_notes: Optional[list[str]] = None
    confidence: int = Field(ge=0, le=100)


class WeeklyDemand(ApiModel):
    week: str
    units: int


class SizeShare(ApiModel):
    size: str
    percent: int


class DemandRange(ApiModel):
    """Simulated season demand: 10th, 50th and 90th percentile."""
    p10: int
    p50: int
    p90: int


class Newsvendor(ApiModel):
    """How the order quantity was set (all money values per unit, in $)."""
    critical_ratio: float          # Cu / (Cu + Co): the demand percentile ordered to
    underage_cost: float           # margin lost per missed sale
    overage_cost: float            # loss per unsold unit after markdown
    markdown_basis: str            # what set the markdown value: evergreen / rising / peaking / fading
    stockout_probability: float    # share of simulated seasons that sell out
    expected_sell_through: float   # expected share of the order sold at full price
    expected_leftover_units: int
    expected_profit: float
    simulations: int


class Forecast(ApiModel):
    brief_id: str
    weekly_demand: list[WeeklyDemand]
    recommended_units: int
    size_split: list[SizeShare]
    launch_window: str
    stock_risk: StockRisk
    risk_reason: str
    demand_range: Optional[DemandRange] = None
    newsvendor: Optional[Newsvendor] = None


class Overview(ApiModel):
    rising_trends: int
    active_briefs: int
    total_recommended_units: int
    average_confidence: int
    top_brief_ids: list[str]
    trend_momentum: list[dict]


class Meta(ApiModel):
    as_of: str
    lead_time_weeks: int
    data_provenance: str
    affiliation: str
    model: dict
