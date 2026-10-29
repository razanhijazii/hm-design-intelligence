"""Runs the full engine once and assembles everything the API serves.

trend signals -> trend summaries
design library + trends + brand DNA + sales history -> scored candidates
-> balanced selection of design briefs -> demand forecast per brief
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from app import config
from app.schemas import DesignBrief, Forecast, Overview, Trend
from app.services import briefs as brief_engine
from app.services import demand, history, trends

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


def _risk(candidate: brief_engine.Candidate, fc: demand.DemandForecast) -> tuple[str, str]:
    lookup = {t.id: t for t in trends.summarise_trends()}
    linked = [lookup[t] for t in candidate.linked_trend_ids]
    trend_risk = max((TREND_RISK[t.status] for t in linked), default=0.35)
    spread = min(fc.cv / 0.3, 1.0)
    score = 0.5 * trend_risk + 0.5 * spread
    level = "low" if score < 0.33 else "medium" if score < 0.55 else "high"
    band = f"±{round(fc.cv * 100)}%"

    fading = [t for t in linked if t.status == "fading"]
    peaking = [t for t in linked if t.status == "peaking"]
    if fading:
        t = fading[0]
        reason = (
            f"{t.name} is fading and projected at about {round(t.projected_index_at_launch)}/100 by launch, so "
            "demand could drop faster than forecast. Start with a smaller first order and re-order on sell-through."
        )
    elif peaking and level != "low":
        t = peaking[0]
        reason = (
            f"{t.name} is at a plateau, so demand could soften during the selling window. Keep a re-order "
            f"option open rather than buying the full quantity up front (forecast range {band})."
        )
    elif linked:
        reason = (
            f"Linked trends are still building into launch and the forecast range is narrow ({band}), "
            "so committing to the recommended quantity is reasonable."
        )
    else:
        reason = (
            f"No tracked trend drives this piece, so demand rests on evergreen attributes and past sales "
            f"(forecast range {band}). A steady seller rather than a spike."
        )
    return level, reason


def _launch_window(fc: demand.DemandForecast) -> str:
    end = fc.weeks[-1]
    start = fc.launch_week
    return f"Launch w/c {start.day} {start:%b %Y}; selling window to {end:%B %Y}"


def build() -> Snapshot:
    trend_models = build_trends()
    candidates = brief_engine.score_candidates(brief_engine.generate_candidates())
    selected = brief_engine.select(candidates)

    brief_models, forecast_models = [], []
    for c in selected:
        fc = demand.forecast(brief_engine.profile_for(c))
        brief_models.append(DesignBrief.model_validate(brief_engine.write_brief(c, fc)))
        level, reason = _risk(c, fc)
        forecast_models.append(
            Forecast(
                brief_id=c.id,
                weekly_demand=[{"week": w.isoformat(), "units": u} for w, u in zip(fc.weeks, fc.units)],
                recommended_units=fc.recommended_units,
                size_split=[{"size": s, "percent": p} for s, p in history.size_split(c.garment)],
                launch_window=_launch_window(fc),
                stock_risk=level,
                risk_reason=reason,
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
