"""Brief engine: decide what to design, and why.

1. Enumerate every valid combination of a base piece, one signature detail, a
   colourway and a material from the design library.
2. Score each candidate on five pieces of evidence:
     trend      where its trends will be when it lands (projected index)
     brand      fit with the brand profile (style mix, price band, complexity,
                versatility, sustainability)
     customer   how past pieces with the same attributes sold and were rated
     novelty    how different it is from anything sold before
     demand     the model's 16-week demand forecast, relative to its category
   Candidates too close to a past product are dropped: briefs must be new.
3. Select a balanced set: 3 briefs per garment type, distinct base pieces,
   varied styles, no detail or colourway overused, then enforce the minimum
   number of multiway and sustainable briefs with the smallest score loss.
4. Write the brief: title, description, signature detail, data-backed
   "why now" reasons, conversions and sustainability notes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from app import config
from app.services import demand, history, trends

WEIGHTS = {"trend": 0.35, "brand": 0.20, "customer": 0.15, "novelty": 0.15, "demand": 0.15}
ATTRIBUTE_WEIGHTS = {"silhouette": 0.30, "detail": 0.30, "colour": 0.25, "fabric": 0.15}
STATUS_ADJUSTMENT = {"rising": 5.0, "peaking": 0.0, "fading": -30.0}
MAX_DETAIL_USES = 2
MAX_COLOUR_USES = 3
REPEAT_STYLE_PENALTY = 6.0
NEW_TREND_BONUS = 3.0

PLURAL = {"dress": "dresses", "top": "tops", "jeans": "jeans", "skirt": "skirts"}
LABELS = {
    "silhouette": {
        "drop-waist": "a drop-waist cut", "bias-cut": "a bias cut", "wrap": "a wrap shape",
        "column": "a column shape", "relaxed": "a relaxed fit", "fitted": "a fitted shape",
        "barrel-leg": "a barrel leg", "straight-leg": "a straight leg", "wide-leg": "a wide leg",
        "tube": "a tube shape", "bubble-hem": "a bubble hem", "a-line": "an A-line shape",
    },
    "fabric": {
        "cotton-jersey": "cotton jersey", "satin": "satin", "crinkle": "a crinkle texture",
        "sheer": "sheer fabric", "lyocell": "lyocell", "poplin": "poplin", "rib-knit": "rib knit", "denim": "denim",
    },
    "detail": {
        "exposed-lacing": "exposed lacing", "scarf-tie": "scarf ties", "bow-strap": "bow straps",
        "sheer-panel": "sheer panels", "statement-button": "a statement button",
        "contrast-stitch": "contrast stitching", "curved-seam": "curved seams", "ruching": "ruching",
    },
}


@dataclass
class Candidate:
    base: dict
    detail: dict
    colour: str
    material_key: str
    material: dict
    attrs: dict[str, str]          # unprefixed: {"silhouette": "drop-waist", ...}
    keys: list[str]                # prefixed attribute keys used for trends/demand
    price: float
    price_range: str
    scores: dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    max_shared: int = 0
    linked_trend_ids: list[str] = field(default_factory=list)

    @property
    def garment(self) -> str:
        return self.base["garmentType"]

    @property
    def style(self) -> str:
        return self.base["style"]

    @property
    def is_multiway(self) -> bool:
        return bool(self.base.get("conversions"))

    @property
    def is_sustainable(self) -> bool:
        return bool(self.material["sustainable"])

    @property
    def id(self) -> str:
        return f"{self.base['id']}--{self.detail['id'].removeprefix('detail-')}--{self.colour}"


@lru_cache(maxsize=1)
def load_library() -> dict:
    return json.loads(config.DESIGN_LIBRARY_PATH.read_text())


@lru_cache(maxsize=1)
def load_brand() -> dict:
    return json.loads(config.BRAND_DNA_PATH.read_text())


# --- Candidate generation ---------------------------------------------------

def _price(base: dict, material: dict) -> tuple[float, str]:
    """Price point from the brand band, material cost and construction, shown as
    an H&M-style .99 range a few dollars wide."""
    low, high = load_brand()["priceBands"][base["garmentType"]]
    point = low + 0.4 * (high - low) + material["costUplift"] + 3 * (base["complexity"] - 1)
    lower = 5 * math.floor((point - 1) / 5) - 1
    return float(point), f"${lower}–{lower + 5}"


def _detail_allowed(detail: dict, base: dict) -> bool:
    if base["garmentType"] not in detail["placements"]:
        return False
    if "allowedBases" in detail and base["id"] not in detail["allowedBases"]:
        return False
    return base["id"] not in detail.get("excludeBases", [])


def generate_candidates() -> list[Candidate]:
    lib = load_library()
    out = []
    for base in lib["bases"]:
        for detail in lib["details"]:
            if not _detail_allowed(detail, base):
                continue
            for colour in base["colours"]:
                for material_key in base["materials"]:
                    material = lib["materials"][material_key]
                    detail_value = detail["attribute"].split(":", 1)[1]
                    attrs = {
                        "silhouette": base["silhouette"],
                        "colour": colour,
                        "fabric": material["fabric"],
                        "detail": detail_value,
                    }
                    keys = [f"{k}:{v}" for k, v in attrs.items()] + list(base.get("extraAttributes", []))
                    price, price_range = _price(base, material)
                    out.append(Candidate(base, detail, colour, material_key, material, attrs, keys, price, price_range))
    return out


# --- Scoring ---------------------------------------------------------------

@lru_cache(maxsize=1)
def _trend_lookup() -> dict[str, trends.TrendSummary]:
    return {t.id: t for t in trends.summarise_trends()}


def _attribute_trend_score(key: str) -> float:
    trend_id = trends.attribute_to_trend().get(key)
    if trend_id is None:
        return float(trends.project_attribute(key, config.LEAD_TIME_WEEKS)[-1])
    summary = _trend_lookup()[trend_id]
    return summary.projected_index_at_launch + STATUS_ADJUSTMENT[summary.status]


def trend_score(c: Candidate) -> float:
    total, weight = 0.0, 0.0
    for column, w in ATTRIBUTE_WEIGHTS.items():
        total += w * _attribute_trend_score(f"{column}:{c.attrs[column]}")
        weight += w
    for extra in c.base.get("extraAttributes", []):
        total += 0.15 * _attribute_trend_score(extra)
        weight += 0.15
    return float(np.clip(total / weight, 0, 100))


def brand_fit(c: Candidate) -> float:
    brand = load_brand()
    mix = brand["styleMix"]
    style = 0.6 + 0.4 * mix[c.style] / max(mix.values())
    low, high = brand["priceBands"][c.garment]
    # Accessible pricing is part of the brand: lower in the band scores better,
    # and anything above the band is penalised hard.
    if c.price <= high:
        price = 1 - 0.5 * (c.price - low) / (high - low)
    else:
        price = max(0.0, 0.5 - (c.price - high) / 10)
    complexity = 1.0 if c.base["complexity"] <= 1 else (0.85 if c.base["complexity"] <= brand["maxComplexity"] else 0.4)
    versatility = 1.0 if c.is_multiway else 0.7
    sustain = 1.0 if c.is_sustainable else 1 - brand["sustainabilityWeight"]
    score = 0.35 * style + 0.25 * price + 0.15 * complexity + 0.15 * versatility + 0.10 * sustain
    return round(100 * score, 1)


def customer_score(c: Candidate) -> float:
    stats = history.attribute_stats()
    g_rating = history.global_rating()
    parts = []
    for column in history.ATTRIBUTE_COLUMNS:
        s = stats.get(f"{column}:{c.attrs[column]}")
        if s is None:
            parts.append(50.0)
            continue
        parts.append(50 + 120 * (s.sell_through_index - 1) + 40 * (s.rating - g_rating))
    return float(np.clip(np.mean(parts), 0, 100))


def score_candidates(candidates: list[Candidate]) -> list[Candidate]:
    attr_to_trend = trends.attribute_to_trend()
    kept: list[Candidate] = []
    for c in candidates:
        shared, _ = history.max_shared_attributes(c.garment, c.style, c.attrs)
        if shared > config.MAX_SHARED_ATTRIBUTES:
            continue  # too close to something already sold
        c.max_shared = shared
        c.linked_trend_ids = sorted({attr_to_trend[k] for k in c.keys if k in attr_to_trend})
        c.scores = {
            "trend": trend_score(c),
            "brand": brand_fit(c),
            "customer": customer_score(c),
            "novelty": 100 - 20 * shared,
        }
        kept.append(c)

    # Demand is compared with the median of its own garment type, since jeans
    # and tops sell at different volumes: 50 = median, +10 points per 10% above.
    raw = demand.quick_demand_batch([_profile(c) for c in kept])
    for garment in {c.garment for c in kept}:
        idx = [i for i, c in enumerate(kept) if c.garment == garment]
        median = float(np.median([raw[i] for i in idx]))
        for i in idx:
            kept[i].scores["demand"] = float(np.clip(50 + 100 * (raw[i] / median - 1), 0, 100))

    for c in kept:
        c.total = sum(WEIGHTS[k] * c.scores[k] for k in WEIGHTS)
    return kept


def _profile(c: Candidate) -> demand.DemandProfile:
    return demand.DemandProfile(
        garment_type=c.garment,
        style=c.style,
        price=c.price,
        is_multiway=c.is_multiway,
        is_sustainable=c.is_sustainable,
        attributes=[f"{col}:{c.attrs[col]}" for col in history.ATTRIBUTE_COLUMNS],
    )


# --- Selection -------------------------------------------------------------

def _valid(c: Candidate, chosen: list[Candidate], ignore: Candidate | None = None) -> bool:
    others = [x for x in chosen if x is not ignore]
    if sum(x.garment == c.garment for x in others) >= config.BRIEFS_PER_GARMENT:
        return False
    if any(x.base["id"] == c.base["id"] for x in others):
        return False
    if sum(x.detail["id"] == c.detail["id"] for x in others) >= MAX_DETAIL_USES:
        return False
    if sum(x.colour == c.colour for x in others) >= MAX_COLOUR_USES:
        return False
    return True


def _adjusted(c: Candidate, chosen: list[Candidate]) -> float:
    score = c.total
    if any(x.garment == c.garment and x.style == c.style for x in chosen):
        score -= REPEAT_STYLE_PENALTY
    covered = {t for x in chosen for t in x.linked_trend_ids}
    if set(c.linked_trend_ids) - covered:
        score += NEW_TREND_BONUS
    return score


def select(candidates: list[Candidate]) -> list[Candidate]:
    garments = sorted({c.garment for c in candidates})
    target = config.BRIEFS_PER_GARMENT * len(garments)
    chosen: list[Candidate] = []
    while len(chosen) < target:
        pool = [c for c in candidates if _valid(c, chosen)]
        if not pool:
            break
        chosen.append(max(pool, key=lambda c: _adjusted(c, chosen)))

    chosen = _enforce_multiway(chosen, candidates)
    chosen = _enforce_sustainable(chosen, candidates)
    return sorted(chosen, key=lambda c: -c.total)


def _enforce_multiway(chosen: list[Candidate], candidates: list[Candidate]) -> list[Candidate]:
    while sum(c.is_multiway for c in chosen) < config.MIN_MULTIWAY_BRIEFS:
        best_swap = None
        for out in [c for c in chosen if not c.is_multiway]:
            for cand in candidates:
                if cand.is_multiway and cand.garment == out.garment and _valid(cand, chosen, ignore=out):
                    loss = out.total - cand.total
                    if best_swap is None or loss < best_swap[0]:
                        best_swap = (loss, out, cand)
        if best_swap is None:
            break
        _, out, cand = best_swap
        chosen = [cand if c is out else c for c in chosen]
    return chosen


def _enforce_sustainable(chosen: list[Candidate], candidates: list[Candidate]) -> list[Candidate]:
    """Prefer switching an existing brief to a sustainable material of the same
    design; that changes the least about the recommendation."""
    while sum(c.is_sustainable for c in chosen) < config.MIN_SUSTAINABLE_BRIEFS:
        best_swap = None
        for out in [c for c in chosen if not c.is_sustainable]:
            for cand in candidates:
                same_design = cand.id == out.id
                if cand.is_sustainable and same_design:
                    loss = out.total - cand.total
                    if best_swap is None or loss < best_swap[0]:
                        best_swap = (loss, out, cand)
        if best_swap is None:
            break
        _, out, cand = best_swap
        chosen = [cand if c is out else c for c in chosen]
    return chosen


# --- Writing the brief -------------------------------------------------------

def attribute_phrase(key: str) -> str | None:
    """'colour:cherry-red' -> 'in cherry red'; 'detail:ruching' -> 'with ruching'."""
    column, value = key.split(":", 1)
    if column == "colour":
        label = load_library()["colours"].get(value)
        return f"in {label}" if label else None
    label = LABELS.get(column, {}).get(value)
    if label is None:
        return None
    return f"in {label}" if column == "fabric" else f"with {label}"


def _best_selling_attribute(c: Candidate) -> tuple[history.AttributeStats, str] | None:
    """The brief's attribute with the strongest sales record (enough products to trust)."""
    stats = history.attribute_stats()
    best = None
    for column in history.ATTRIBUTE_COLUMNS:
        key = f"{column}:{c.attrs[column]}"
        s, phrase = stats.get(key), attribute_phrase(key)
        if s and phrase and s.n >= 4 and s.sell_through_index > 1.02:
            if best is None or s.sell_through_index > best[0].sell_through_index:
                best = (s, phrase)
    return best


def _why_now(c: Candidate) -> list[str]:
    lookup = _trend_lookup()
    reasons = []
    # Rising trends first (they are the reason to act now), then by where they
    # will be at launch.
    order = {"rising": 0, "peaking": 1, "fading": 2}
    linked = sorted(
        (lookup[t] for t in c.linked_trend_ids),
        key=lambda t: (order[t.status], -t.projected_index_at_launch),
    )
    usable = [t for t in linked if t.status != "fading"]
    if usable:
        lead = usable[0]
        reasons.append(
            f"{lead.name}: {lead.status} (momentum {lead.momentum:+d}), projected at about "
            f"{round(lead.projected_index_at_launch)}/100 when this lands."
        )
        others = [f"{t.name.lower()} ({t.status}, {t.momentum:+d})" for t in usable[1:3]]
        if others:
            reasons.append("Also draws on " + " and ".join(others) + ".")
    else:
        _, evergreen = trends.load_catalogue()
        steady = [k for k in c.keys if k in evergreen and k.split(":")[1] != "none"]
        phrases = [attribute_phrase(k) for k in steady[:2]]
        phrases = [p.removeprefix("in ").removeprefix("with ") for p in phrases if p]
        if phrases:
            avg = round(float(np.mean([evergreen[k] for k in steady])))
            reasons.append(
                f"A core piece rather than a trend bet: built on evergreen attributes ({' and '.join(phrases)}) "
                f"with steady interest around {avg}/100."
            )

    if c.scores.get("demand", 50) >= 55:
        lift = round(c.scores["demand"] - 50)
        reasons.append(f"The demand model puts it about {lift}% above the median {c.garment} candidate.")

    best = _best_selling_attribute(c)
    if best:
        s, phrase = best
        reasons.append(
            f"Past pieces {phrase} sold {s.sell_through_index:.2f}× their category average "
            f"and were rated {s.rating:.1f}/5 ({s.n} products)."
        )

    if c.is_multiway:
        m = history.flag_uplift()["is_multiway"]
        reasons.append(
            f"Convertible pieces in the history sold {m['sell_through_ratio']:.2f}× their category average, "
            f"with {m['return_rate_points']:.0f} percentage points fewer returns."
        )
    if len(reasons) < 3:
        reasons.append(
            f"Fits the {c.style} core of the range at {c.price_range}, inside the {c.garment} price band "
            f"(brand fit {round(c.scores['brand'])}/100)."
        )
    reasons.append(
        f"New to the range: no past {c.garment if c.garment != 'jeans' else 'pair of jeans'} shares more than "
        f"{c.max_shared} of its 5 core attributes."
    )
    return reasons


def _sustainability_notes(c: Candidate) -> list[str] | None:
    if not c.is_sustainable:
        return None
    notes = [c.material["note"]]
    if c.is_multiway:
        notes.append("Made to be worn several ways, so one purchase covers more outfits and stays in rotation longer.")
    if c.material["costUplift"]:
        notes.append(f"Adds about ${c.material['costUplift']} to the price point; the price range already includes it.")
    return notes


def _confidence(c: Candidate, cv: float) -> int:
    lookup = _trend_lookup()
    linked = [lookup[t] for t in c.linked_trend_ids]
    if linked:
        agreement = float(np.mean([1.0 if t.status == "rising" else 0.6 if t.status == "peaking" else 0.1 for t in linked]))
    else:
        agreement = 0.5
    support = min(1.0, history.similar_history_count(c.garment, c.attrs) / 12)
    precision = 1 - min(cv / 0.3, 1.0)
    return int(round(np.clip(35 + 30 * agreement + 20 * precision + 15 * support, 0, 100)))


def write_brief(c: Candidate, forecast: demand.DemandForecast) -> dict:
    placement = c.detail["placements"][c.garment]
    colour_label = load_library()["colours"][c.colour]
    description = c.base["description"].format(material=c.material["label"]) + f" Lead colourway: {colour_label}."
    return {
        "id": c.id,
        "title": f"{c.base['name']} {placement['suffix']}",
        "garmentType": c.garment,
        "style": c.style,
        "baseDescription": description,
        "signatureDetail": placement["text"],
        "whyNow": _why_now(c),
        "linkedTrendIds": c.linked_trend_ids,
        "brandDnaFit": int(round(c.scores["brand"])),
        "targetCustomer": c.base["targetCustomer"],
        "priceRange": c.price_range,
        "isMultiway": c.is_multiway,
        "conversions": c.base.get("conversions") if c.is_multiway else None,
        "isSustainable": c.is_sustainable,
        "sustainabilityNotes": _sustainability_notes(c),
        "confidence": _confidence(c, forecast.cv),
    }


def profile_for(c: Candidate) -> demand.DemandProfile:
    return _profile(c)
