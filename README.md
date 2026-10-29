# H&M Design & Demand Intelligence

A decision tool for fashion design and merchandising teams. Instead of generating garment images, it tells designers **what to design, why, and how much to make**:

- **Trend signals:** which colours, silhouettes, details and fabrics are rising, peaking or fading, and where each will be when a product actually lands in store.
- **Design briefs:** 12 recommended pieces (3 each of dresses, tops, jeans and skirts). Each is a simple, sleek base with **one** signature detail, and comes with the data-backed reasons behind it.
- **Multiway and sustainable pieces:** convertible designs with step-by-step conversions, and sustainable material choices with their trade-offs.
- **Demand and stock planning:** a 16-week demand forecast per brief, recommended quantity with safety stock, size split, launch week and stock risk.

> Independent concept project, not affiliated with or endorsed by H&M. All data in `data/` is **synthetic** demo data (see [Data](#data)). The brand profile is an assumption paraphrased from H&M's public positioning.

It is the backend for the Lovable frontend, and builds on the Hermès project's backend (same RandomForest + 15% safety stock demand approach), reworked for a high-street brand.

## How it works

```text
trend_signals.csv ──> trends ──> momentum, status, evidence, projection to launch
                                          │
design_library.json ─┐                    ▼
brand_dna.json ──────┼──> brief engine: enumerate ~530 candidates
past_products.csv ───┘      score: trend 35% · brand fit 20% · customer love 15%
weekly_sales.csv ──> demand model ─┐      novelty 15% · demand 15%
                                   │    drop anything too close to a past product
                                   │    select a balanced set of 12
                                   ▼
                     forecast per brief: best launch week, 16-week demand,
                     units + 15% safety stock, size split, stock risk
```

**1. Trends** (`app/services/trends.py`). Each trend has three weekly sources: search interest, social mentions and editorial/runway mentions. They're blended into one 0–100 index. Momentum compares the last 4 weeks with the 8 before. The status (rising / peaking / fading) also uses the smoothed slope and the distance from the 52-week peak. Each trend is projected forward with a damped slope over the **12-week design-to-store lead time**, so briefs are judged on where a trend will be at launch, not today.

**2. Candidates** (`data/design_library.json`). Curated building blocks: 18 base pieces, 8 signature details, 17 materials and 6 colourways. The engine combines them, respecting which details work on which pieces, into roughly 530 valid candidates.

**3. Scoring** (`app/services/briefs.py`). Every candidate gets five scores:

| Score | What it measures |
|---|---|
| Trend | Projected interest at launch for its silhouette, detail, colour and fabric. Rising trends get a bonus; fading ones get a heavy penalty. |
| Brand fit | Style mix, position in the category price band, construction complexity, versatility, sustainability (all set in `brand_dna.json`). |
| Customer love | How past pieces with the same attributes sold vs their category average, and how they were rated. |
| Novelty | Candidates sharing more than 3 of 5 core attributes with any past product are dropped: briefs must be new, not re-runs. |
| Demand | The demand model's 16-week forecast vs the median candidate of the same garment type. |

**4. Selection.** A greedy pass builds a balanced set: 3 per garment type, no repeated base piece, styles varied, no detail used more than twice, no colourway more than three times. It then enforces at least 5 multiway and 4 sustainable briefs with the smallest possible loss in score. For sustainability it switches an existing brief's material rather than changing the design.

**5. Forecast** (`app/services/demand.py`). A `RandomForestRegressor` trained on the sales history predicts weekly units from garment type, style, price, multiway/sustainable flags, trend interest, weeks since launch and season. For each brief it tries 14 launch weeks after the lead time and picks the best one (later weeks are discounted 1.5% per week, since the trend read gets older). It then adds 15% safety stock. Stock risk combines the forecast spread across trees with the status of the brief's linked trends.

**What it found in this data:** six trends are rising, three are at a plateau, and the bubble hem is fading. The engine never recommends a bubble-hem piece. Convertible pieces historically sold about 1.1× their category average with fewer returns, so 7 of the 12 briefs are multiway. Sustainable lines also sold slightly better, so most briefs use sustainable materials. Lower `sustainabilityWeight` in `brand_dna.json` to see that change.

## API

| Endpoint | Returns |
|---|---|
| `GET /trends` | `Trend[]`, filter with `?category=` and `?status=` |
| `GET /briefs` | `DesignBrief[]`, filter with `?garmentType= &style= &multiway= &sustainable= &minConfidence= &trendId=` |
| `GET /briefs/{id}` | one `DesignBrief` |
| `GET /forecasts` | `Forecast[]` |
| `GET /forecasts/{briefId}` | one `Forecast` |
| `GET /overview` | headline stats, top 3 briefs, momentum for the chart |
| `GET /meta` | as-of date, data provenance, model metrics |
| `GET /health` | service status |

Interactive docs at `/docs` once running. Field names are camelCase and match the frontend's TypeScript types exactly (`frontend_data/src/data/types.ts`).

## Run it locally

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/train_demand_model.py      # optional; trains on first start otherwise
uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs
python -m pytest -q
```

## Connect the Lovable frontend

1. Run `python scripts/export_frontend_data.py`. It writes `frontend_data/src/data/*.ts` (types plus the engine's real output) and `frontend_data/src/services/api.ts`.
2. Replace the mock files in the Lovable project with these (same paths). The frontend now shows the engine's actual briefs instead of invented ones.
3. Once the API is deployed, set `VITE_API_URL` in the frontend to the API's URL. `api.ts` then fetches live data; with it unset, it uses the bundled files.

## Deploy (Render)

`render.yaml` is included: connect the repo on Render as a Blueprint. The build installs the requirements and trains the model; the service starts with uvicorn. The model file is not committed. It is rebuilt at deploy time, so it always matches the installed scikit-learn version.

## Data

`scripts/generate_synthetic_data.py` (seeded, so reproducible) creates:

| File | Contents |
|---|---|
| `trend_signals.csv` | 108 weeks × 10 trends: `search_index`, `social_mentions`, `editorial_mentions` |
| `past_products.csv` | 160 past products: garment type, style, silhouette, colour, fabric, detail, multiway/sustainable flags, price, rating, return rate |
| `weekly_sales.csv` | 16 weeks of unit sales per product |
| `size_sales.csv` | units per size per product |

The history is generated from the same trend index the engine reads, with realistic effects: price sensitivity, seasonality, product lifecycle, a multiway uplift and noise. The model has to recover those effects; its holdout score on the most recent 20% of launches is reported at `/meta`. Unit volumes represent a modelled test market, not H&M's real scale.

**To use real data,** replace the CSVs with real exports using the same columns, for example search interest from the Google Trends BigQuery adapter in the Hermès backend and sales from a retailer dataset, then rerun. Nothing else changes.

## Project layout

```text
app/
  main.py              FastAPI endpoints
  pipeline.py          runs the engine once, builds the snapshot the API serves
  schemas.py           API contracts (mirror the frontend types)
  config.py            dates, lead time, quotas, paths
  services/
    trends.py          signals → momentum, status, evidence, projection
    history.py         past sales → attribute performance, size split, novelty
    demand.py          RandomForest demand model and launch-week forecast
    briefs.py          candidate generation, scoring, selection, brief writing
data/                  brand profile, design library, trend catalogue, synthetic CSVs
scripts/               data generation, model training, frontend export
tests/                 engine and API tests
frontend_data/         generated TypeScript for the Lovable app
```

## Limitations

- The data is synthetic, so the numbers show how the method works, not real H&M demand.
- Trend projection is a damped linear extrapolation. It's transparent, but it won't anticipate a sudden new trend.
- Forecast spread comes from disagreement between the model's trees, which understates real-world uncertainty. Treat stock risk as relative, not absolute.
- The design library is curated by hand. The engine chooses and justifies combinations but doesn't invent new garment types.
