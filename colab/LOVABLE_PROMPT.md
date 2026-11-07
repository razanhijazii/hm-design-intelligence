Build a two-part web app called "Style Vote" for my fashion design-intelligence project. It is an independent concept project pitched to H&M (not affiliated with H&M — never use H&M's logo, fonts or branding; show the line "Independent concept project · not affiliated with or endorsed by H&M" in the footer of every page).

There is NO database in this app and NO login system. Do not add Supabase. All data comes from one Google Apps Script web app that sits on my Google Sheet. Put its URL in one constant, src/config.ts:

  export const API_URL = "PASTE_MY_APPS_SCRIPT_WEB_APP_URL_HERE";

## The API (already built — match it exactly)

1. GET  `${API_URL}?action=public`
   Returns JSON: { designs: Design[], trend_polls: TrendPoll[] }
   - Design: { design_id, garment ("dress"|"top"|"jeans"|"skirt"), name, description,
     colours (comma-separated colour names, e.g. "Cloud Dancer, Hibiscus, Princess Blue, Blue Indigo"),
     colour_hex (comma-separated hex codes in the same order),
     price_eur (number), multiway (text: name of the convertible feature, or empty),
     sustainable ("yes"|"no"), image_url (main photo URL or empty),
     image_urls (comma-separated photo URLs, one per colour in the same order as colours; may be empty) }
   - TrendPoll: { trend_id, question (e.g. "Barrel jeans: hot or not?"), keyword, status }

2. POST `${API_URL}`  — send a vote.
   IMPORTANT: send the body as a plain string with NO Content-Type header (or "text/plain;charset=utf-8").
   Do NOT send "application/json" — Apps Script cannot answer the CORS preflight and the request will fail.
     fetch(API_URL, { method: "POST", body: JSON.stringify(vote) })
   Design vote body: { voter_id, type: "design", item_id: design_id, rating: 1-5, colour: one of the design's colour names or "",
                       price_answer: "yes"|"maybe"|"no"|"", age_range: ""|"16-24"|"25-34"|"35-44"|"45-54"|"55+", source }
   Trend vote body:  { voter_id, type: "trend", item_id: trend_id, answer: "hot"|"not", age_range, source }
   Response: { ok: true } or { ok: false, error: "message" } — show the error message if ok is false.

3. GET  `${API_URL}?action=business&key=ACCESS_KEY`
   Returns { error } if the key is wrong, otherwise an object whose keys are tables (arrays of row objects):
   run_info (key, value), briefs, buy_plan, trends, colours, vote_summary, model_report, designs, trend_polls, live_votes.
   live_votes rows: { item_id, type ("design"|"trend"), n_votes, avg_rating, approval (0-1), would_buy (0-1), top_colour, hot_share (0-1), last_vote }.
   Render every table generically from its keys (columns can change between notebook runs), with friendly formatting rules below.

voter_id: generate once with crypto.randomUUID(), keep in localStorage under "sv_voter" (wrap localStorage in try/catch).
age_range: remembered in localStorage "sv_age". source: read the "src" URL parameter, default "instagram".

## Page 1 — Customer voting page, route "/"  (mobile-first, this is what shoppers see from Instagram)

Look: editorial fashion, calm and premium but warm. Off-white paper background, near-black ink, one serif display face (e.g. Fraunces) for design names and a clean sans (e.g. Inter) for everything else. Generous whitespace, large tap targets (min 48px), rounded 14–18px cards, no gradients, no emoji except the 🔥 on the "Hot" button. Support dark mode via prefers-color-scheme. Max content width ~460px, centred.

Flow:
- Load designs and trend polls from the public endpoint. If the URL has ?d=DESIGN_ID, show that design first (it's the one posted on Instagram), then the other designs, then up to 6 random trend polls.
- Header: wordmark "Style Vote" left, "3 of 18" step counter right, thin progress bar under it.
- Design card:
  - Large photo area (aspect ratio ~4:4.4). Show the photo for the selected colour from image_urls (same index as the colour); fall back to image_url; if there is no photo at all, draw a simple flat SVG silhouette of the garment type filled with the selected colour's hex.
  - Small pill tags over the photo: "Concept render" (when a photo is shown), "Convertible" (when multiway is not empty), "Sustainable material" (when sustainable is "yes").
  - Design name (serif, ~24px), price "€34.99", description in muted text.
  - Question 1 "How much would you wear it?": five equal buttons 1–5 with "Not for me" under 1 and "Need it" under 5. Selecting 4 fills buttons 1–4.
  - Question 2 "Which colour would you pick? (tap to preview)": round swatches with the colour name under each; tapping one selects it and swaps the photo to that colour.
  - Question 3 "Would you buy it at €34.99?": segmented Yes / Maybe / No.
  - Collapsible "Add your age range (optional)" with chips 16-24 … 55+, remembered.
  - Primary button "Send my vote" (disabled until a rating is chosen), then "Skip this one" as a secondary button.
  - After a successful vote, move to the next item with a short fade.
- Trend poll card: small label "Quick trend check", the trend name big (strip ": hot or not?" from the question), subtitle "In or out for next season?", two big buttons "🔥 Hot" and "Not for me", and "Skip".
- End card: "Thank you" + "Your votes go straight to the design team's dashboard and help decide what gets made, and in which colours." + button "Vote again from the start".
- Loading, empty ("Nothing to vote on yet") and error ("Can't load designs — check your connection and refresh") states.
- Footer: "Your votes are anonymous and help decide which designs get made, in which colours." + the not-affiliated line.

## Page 2 — Business dashboard, route "/business"  (functional, plain is fine)

- Access screen: one password field "Access key" + "Open dashboard". Store the key in localStorage "bd_key"; if the API returns { error }, clear it and show the error. Header buttons "Refresh" and "Change key". Show "Last notebook run: <run_info.updated_at>".
- Tabs: Overview · Design briefs · Buy plan · Customer votes · Trends · Colours · Models · Instagram links.
- Every table: sortable by clicking headers, a filter box, a "Download CSV" button, horizontal scroll on small screens.
- Overview: KPI tiles — number of briefs, total units in first order (sum of buy_plan.order_units), launch week (run_info), trends rising (trends with status "rising" / total), live customer votes (sum of live_votes.n_votes), briefs at high stock risk. Below: the run_info table.
- Design briefs (briefs table): show a colour swatch (colour_hex) before the colour name and "PANTONE <code>" when pantone is set; show a small thumbnail when the design has an image_url (look it up in designs by design_id); format price as €, hit_probability as %, scores with 0 decimals; render the "why" column (text separated by " | ") as a bullet list.
- Buy plan: order_units, p10, p50, p90 as integers; a small sparkline of weekly_forecast (comma-separated numbers); stock_risk as a coloured pill (low green / medium amber / high red); percentages for stockout_prob and expected_sell_through; € for expected_profit_eur.
- Customer votes: live_votes joined to designs (name) and trend_polls (question); show votes, avg rating, approval %, would buy %, top colour, hot %, last vote. Sorted by votes.
- Trends: status as coloured text (rising green / peaking amber / fading red), yoy_change_pct with a + sign.
- Colours: swatch from the hex column + Pantone name, TCX, palette, H&M colour group, sell index.
- Models: the model_report table as-is, numbers to 3 decimals.
- Instagram links: for every design with active = TRUE, show name, ID, image (or "none yet"), and its vote link `${window.location.origin}/?d=DESIGN_ID` with a Copy button. Above the table show the general link `${window.location.origin}/` with Copy, and the hint: "To show the real Instagram photo instead of the AI concept photo, paste an image URL into the image_url column of the designs tab in the Google Sheet."

Use React + Tailwind. Keep all API calls in one file src/api.ts. No other backend.
