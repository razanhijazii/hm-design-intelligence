"""FastAPI app. Endpoints match the Lovable frontend's service layer:

getTrends()        -> GET /trends
getBriefs()        -> GET /briefs   (optional filters)
getBriefById(id)   -> GET /briefs/{id}
getForecasts()     -> GET /forecasts
                      GET /forecasts/{brief_id}
                      GET /overview
                      GET /meta, /health
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from app import config, pipeline
from app.schemas import DesignBrief, Forecast, GarmentType, Overview, Style, Trend, TrendCategory, TrendStatus

logger = logging.getLogger("hm_design_intelligence")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Build once at startup; every request then reads the same snapshot.
    pipeline.snapshot()
    yield


app = FastAPI(
    title="H&M Design & Demand Intelligence",
    version="1.0.0",
    description="Tells designers what to design, why, and how much to make. Independent concept project; synthetic demo data.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins(),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": "H&M Design & Demand Intelligence", "docs": "/docs"}


@app.get("/health")
def health() -> dict:
    snap = pipeline.snapshot()
    return {"status": "healthy", "trends": len(snap.trends), "briefs": len(snap.briefs)}


@app.get("/meta")
def meta() -> dict:
    return pipeline.meta()


@app.get("/overview", response_model=Overview)
def overview() -> Overview:
    return pipeline.snapshot().overview


@app.get("/trends", response_model=list[Trend])
def list_trends(
    category: Optional[TrendCategory] = None,
    status: Optional[TrendStatus] = None,
) -> list[Trend]:
    items = pipeline.snapshot().trends
    if category:
        items = [t for t in items if t.category == category]
    if status:
        items = [t for t in items if t.status == status]
    return items


@app.get("/briefs", response_model=list[DesignBrief], response_model_exclude_none=False)
def list_briefs(
    garment_type: Optional[GarmentType] = Query(None, alias="garmentType"),
    style: Optional[Style] = None,
    multiway: Optional[bool] = None,
    sustainable: Optional[bool] = None,
    min_confidence: int = Query(0, alias="minConfidence", ge=0, le=100),
    trend_id: Optional[str] = Query(None, alias="trendId"),
) -> list[DesignBrief]:
    items = pipeline.snapshot().briefs
    if garment_type:
        items = [b for b in items if b.garment_type == garment_type]
    if style:
        items = [b for b in items if b.style == style]
    if multiway is not None:
        items = [b for b in items if b.is_multiway == multiway]
    if sustainable is not None:
        items = [b for b in items if b.is_sustainable == sustainable]
    if trend_id:
        items = [b for b in items if trend_id in b.linked_trend_ids]
    return [b for b in items if b.confidence >= min_confidence]


@app.get("/briefs/{brief_id}", response_model=DesignBrief)
def get_brief(brief_id: str) -> DesignBrief:
    for brief in pipeline.snapshot().briefs:
        if brief.id == brief_id:
            return brief
    raise HTTPException(status_code=404, detail=f"No brief with id {brief_id!r}")


@app.get("/forecasts", response_model=list[Forecast])
def list_forecasts() -> list[Forecast]:
    return pipeline.snapshot().forecasts


@app.get("/forecasts/{brief_id}", response_model=Forecast)
def get_forecast(brief_id: str) -> Forecast:
    for fc in pipeline.snapshot().forecasts:
        if fc.brief_id == brief_id:
            return fc
    raise HTTPException(status_code=404, detail=f"No forecast for brief {brief_id!r}")
