"""Runs the full engine once and assembles everything the API serves.

trend signals -> trend summaries
design library + trends + brand DNA + sales history -> scored candidates
-> balanced selection of design briefs -> demand forecast per brief
-> simulated demand distribution -> newsvendor order quantity
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from app import config
from app.schemas import DesignBrief, Forecast, Overview, Trend
from app.services import briefs as brief_engine
from app.services import demand, history, inventory, trends

logger = logging.getLogger(__name__)

TREND_RISK = {"rising": 0.15, "peaking": 0.55, "fading": 1.0}


@dataclass
class Snapshot:
    trends: list[Trend]
    briefs: list[DesignBrief]
    forecasts: list[Forecast]
    overview: Overview
    candidates_considered: int


def _trend_sales_line(trend_def: trends.TrendDefinition) -> str | None:
    stats = history.attribute_stats()
    for key in trend_def.attributes:
        s, phrase = stats.get(key), brief_engine.attribute_phrase(key)
        if s and phrase and s.n >= 4:
            return (
                f"In the sales history, pieces {phrase} sold {s.sell_through_index:.2f}× their category "
                f"average and were rated {s.rating:.1f}/5 ({s.n} products)."
            )
    return None


def build_trends() -> list[Trend]:
    definitions = {t.id: t for t in trends.load_catalogue()[0]}
    out = []
    for s in trends.summarise_trends():
        evidence = list(s.evidence)
        sales_line = _trend_sales_line(definitions[s.id])
        if sales_line:
            evidence.append(sales_line)
        out.append(
            Trend(id=s.id, name=s.name, category=s.category, momentum=s.momentum, status=s.status,
                  evidence=evidence, weekly_scores=s.weekly_scores)
        )
    return out


def _risk(candidate: brief_engine.Candidate, nv: inventory.NewsvendorResult) -> tuple[str, str]:
    """Stock risk from how wide simulated demand is and what the trends are doing,
    with an explanation a buyer can act on."""
    lookup = {t.id: t for t in trends.summarise_trends()}
    linked = [lookup[t] for t in candidate.linked_trend_ids]
    trend_risk = float(np.mean([TREND_RISK[t.status] for t in linked])) if linked else 0.35
    spread = (nv.p90 - nv.p10) / max(nv.p50, 1)  # 80% range relative to the median
    score = 0.5 * trend_risk + 0.5 * min(spread, 1.0)
    level = "low" if score < 0.4 else "medium" if score < 0.6 else "high"

    sim = (
        f"Across {nv.simulations:,} simulated seasons, demand ran from {nv.p10:,} to {nv.p90:,} units "
        f"(80% range). Ordering {nv.order_quantity:,} covers demand in {round(nv.critical_ratio * 100)}% of them, "
        f"with about {nv.expected_leftover:,} units expected left for markdown."
    )
    fading = [t for t in linked if t.status == "fading"]
    peaking = [t for t in linked if t.status == "peaking"]
    if fading:
        advice = (
            f" {fading[0].name} is fading, so unsold stock would need deep markdowns: the order is set "
            "conservatively. Re-order on early sell-through rather than buying more up front."
        )
    elif peaking:
        advice = (
            f" {peaking[0].name} is at a plateau and leftover stock would clear at a deeper markdown, which "
            "pulls the order below the upper end of demand. Keep a re-order option open."
        )
    elif linked:
        advice = " The linked trends are still building into launch, so the downside is mainly forecast error."
    else:
        advice = (
            " No tracked trend drives this piece, so leftover stock can carry over to next season. That is why "
            "the order sits higher in the demand range."
        )
    return level, sim + advice


def _launch_window(fc: demand.DemandForecast) -> str:
    end = fc.weeks[-1]
    start = fc.launch_week
    return f"Launch w/c {start.day} {start:%b %Y}; selling window to {end:%B %Y}"


def build() -> Snapshot:
    trend_models = build_trends()
    candidates = brief_engine.score_candidates(brief_engine.generate_candidates())
    selected = brief_engine.select(candidates)

    brief_models, forecast_models = [], []
    trend_lookup = {t.id: t for t in trends.summarise_trends()}
    for c in selected:
        fc = demand.forecast(brief_engine.profile_for(c))
        brief_models.append(DesignBrief.model_validate(brief_engine.write_brief(c, fc)))
        statuses = [trend_lookup[t].status for t in c.linked_trend_ids]
        nv = inventory.newsvendor(
            fc.tree_paths, c.price, inventory.worst_status(statuses), demand.residual_sigma(), seed_key=c.id
        )
        level, reason = _risk(c, nv)
        forecast_models.append(
            Forecast(
                brief_id=c.id,
                weekly_demand=[{"week": w.isoformat(), "units": u} for w, u in zip(fc.weeks, fc.units)],
                recommended_units=nv.order_quantity,
                size_split=[{"size": s, "percent": p} for s, p in history.size_split(c.garment)],
                launch_window=_launch_window(fc),
                stock_risk=level,
                risk_reason=reason,
                demand_range={"p10": nv.p10, "p50": nv.p50, "p90": nv.p90},
                newsvendor={
                    "critical_ratio": nv.critical_ratio,
                    "underage_cost": nv.underage_cost,
                    "overage_cost": nv.overage_cost,
                    "markdown_basis": nv.markdown_basis,
                    "stockout_probability": nv.stockout_probability,
                    "expected_sell_through": nv.expected_sell_through,
                    "expected_leftover_units": nv.expected_leftover,
                    "expected_profit": nv.expected_profit,
                    "simulations": nv.simulations,
                },
            )
        )

    overview = Overview(
        rising_trends=sum(t.status == "rising" for t in trend_models),
        active_briefs=len(brief_models),
        total_recommended_units=sum(f.recommended_units for f in forecast_models),
        average_confidence=int(round(np.mean([b.confidence for b in brief_models]))) if brief_models else 0,
        top_brief_ids=[b.id for b in brief_models[:3]],
        trend_momentum=[
            {"id": t.id, "name": t.name, "momentum": t.momentum, "status": t.status}
            for t in sorted(trend_models, key=lambda t: -t.momentum)
        ],
    )
    logger.info("Built %d briefs from %d candidates", len(brief_models), len(candidates))
    return Snapshot(trend_models, brief_models, forecast_models, overview, len(candidates))


@lru_cache(maxsize=1)
def snapshot() -> Snapshot:
    return build()


def meta() -> dict:
    return {
        "asOf": config.AS_OF.isoformat(),
        "leadTimeWeeks": config.LEAD_TIME_WEEKS,
        "dataProvenance": (
            "Synthetic demo data generated by scripts/generate_synthetic_data.py. Replace the CSVs in data/ "
            "with real exports (same columns) to run the engine on real signals and sales."
        ),
        "affiliation": "Independent concept project. Not affiliated with or endorsed by H&M.",
        "candidatesConsidered": snapshot().candidates_considered,
        "model": demand.model_info(),
    }
