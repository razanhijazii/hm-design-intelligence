# H&M Design & Demand Intelligence — Colab version

Everything runs from one Google Colab notebook and one Google Sheet. No server to keep alive.

```text
 Kaggle H&M sales ─┐
 Google Trends ────┼──► Colab notebook ──► Google Sheet ──► business.html (dashboard)
 Pantone palettes ─┤    (all the ML)         ▲   │
 Customer votes ───┘                         │   └──► vote.html ◄── Instagram link
                                             └────── votes ◄────────┘
```

| File | What it is |
|---|---|
| `HM_Design_Intelligence.ipynb` | The backend: data, models, charts, briefs, buy plan. Writes results to the Sheet. |
| `apps_script/Code.gs` | Small script attached to the Sheet: serves designs to the voting page, saves votes, serves results to the dashboard. |
| `web/vote.html` | Customer page (mobile-first). Opened from Instagram. |
| `web/business.html` | Business dashboard (plain tables, CSV export, live vote counts). |
| `web/config.js` | Where you paste the Apps Script URL once. |

## 1. Google Sheet + Apps Script (10 min)

1. Create a blank Google Sheet, e.g. *H&M Design Intelligence*.
2. **Extensions → Apps Script**. Delete the sample code, paste all of `apps_script/Code.gs`, save.
3. In the function menu pick **`setup`** → **Run** → allow the permissions. Open **Execution log**: it prints your **business access key**. Keep it.
4. **Deploy → New deployment** → type **Web app** → *Execute as:* **Me**, *Who has access:* **Anyone** → **Deploy**. Copy the **Web app URL** (ends in `/exec`).

> If you edit `Code.gs` later: **Deploy → Manage deployments → ✏️ → Version: New version → Deploy** (the URL stays the same).

## 2. Put the two pages online (GitHub Pages, free)

1. Paste the Web app URL into `web/config.js`:
   ```js
   window.STYLE_VOTE_CONFIG = { API_URL: "https://script.google.com/macros/s/XXXX/exec" };
   ```
2. In your `hm-design-intelligence` repo, create a `docs/` folder and upload `vote.html`, `business.html`, `config.js`.
3. Repo **Settings → Pages** → *Deploy from a branch* → `main` / `/docs` → Save.
4. After a minute:
   - Voting page: `https://razanhijazii.github.io/hm-design-intelligence/vote.html`
   - Dashboard: `https://razanhijazii.github.io/hm-design-intelligence/business.html` (asks for the access key)

## 3. Run the notebook in Colab

1. One-time Kaggle setup: sign in at kaggle.com, open the [competition rules](https://www.kaggle.com/competitions/h-and-m-personalized-fashion-recommendations/rules) and click **I Understand and Accept**. Then **Settings → API → Create New Token** (downloads `kaggle.json`).
2. Open [colab.research.google.com](https://colab.research.google.com) → **File → Upload notebook** → `HM_Design_Intelligence.ipynb` (or open it from GitHub once it's in the repo).
3. Optional but tidy: add Colab **Secrets** (🔑 on the left) `KAGGLE_USERNAME` and `KAGGLE_KEY` from `kaggle.json`. Otherwise the notebook asks you to upload `kaggle.json`.
4. In the settings cell, set `SHEET_URL` to your Sheet's URL.
5. **Runtime → Run all**. Approve the Google Drive and Google account prompts.
   - First run: ~15–20 min (downloads ~4 GB once, aggregates 31M transactions, caches to Drive).
   - Later runs: a few minutes.
6. At the end it builds **`HM_Design_Intelligence_Report.docx`** (every chart and table, each with a two-line explanation) in your Drive folder `hm_design_intelligence/outputs`, and Colab offers it as a download.
7. When it finishes, the Sheet has tabs `designs`, `trend_polls`, `briefs`, `buy_plan`, `trends`, `colours`, `vote_summary`, `model_report`, `run_info`, and the dashboard shows them.

## 4. Use it with Instagram

1. Dashboard → **Instagram links**: each design has its own vote link. Post the design, add the link to the story link sticker / bio.
2. To show the real post image on the voting page instead of the drawn silhouette, paste an image URL into the `image_url` column of the `designs` tab.
3. Votes appear on the dashboard's **Customer votes** tab immediately. **Rerun the notebook** to fold them into the scores (design approval, colour choice and trend polls all feed back in).

## Troubleshooting

| Problem | Fix |
|---|---|
| Kaggle `403` / download fails | Accept the competition rules (step 3.1) with the same account as the token. |
| Google Trends `429` / "retrying" | Google rate limit. Wait 5–10 min and rerun that cell; finished keywords are cached in Drive. |
| Dashboard says "Wrong or missing access key" | Use the key from the `setup` log. To change it: Apps Script → Project Settings → Script properties → `BUSINESS_KEY`. |
| Pages say "Couldn't reach" | Check `config.js` has the `/exec` URL and the deployment has access **Anyone**. |
| Colab runs out of memory | Runtime → Restart and run all (the chunked reader keeps peak memory under ~6 GB). |

## For the course write-up

The notebook's sections map to the ML content: EDA heatmaps (§5), time-series decomposition and damped trend projection (§6b), k-means trend-lifecycle clustering with silhouette selection (§6c), four demand models compared on a time-based holdout and time-series CV (§7b), permutation importance and partial dependence (§7c), a hit classifier with ROC/AUC and confusion matrix (§8), product style clustering with PCA (§9), Wilson-scored customer votes (§10), multi-criteria design scoring (§11), and newsvendor optimisation on Monte Carlo demand (§12). Limitations are listed in §15.
