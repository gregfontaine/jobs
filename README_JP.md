# AI Exposure of the Japan Job Market

Interactive treemap visualizing AI exposure risk across ~500 Japanese occupations.

**Live demo (once deployed):** `site/index_jp.html`

---

## Data sources

| Data | Source | Notes |
|------|--------|-------|
| Occupation profiles | [Jobtag](https://shigoto.mhlw.go.jp/) (MHLW) | ~500 occupations, Japanese text |
| Median wages | [e-Stat](https://www.e-stat.go.jp/) — 賃金構造基本統計調査 | 129 JSOC occupation groups |
| Employment counts | e-Stat — 労働力調査 / 国勢調査 | JSOC small classification |
| AI exposure scores | OpenRouter → Gemini Flash | LLM-scored on 0–10 scale |

> **Outlook feature intentionally omitted:** Japan has no occupation-level
> 10-year employment projection source equivalent to the US BLS OOH. The
> ハローワーク active job opening ratio is a useful proxy but is a current
> demand signal, not a forward projection. Rather than display misleading data,
> the outlook field is absent from the Japan version.

---

## Setup

```bash
# 1. Install dependencies (same environment as the US pipeline)
uv sync
uv run playwright install chromium

# 2. Create .env with your API keys
cp .env.example .env   # then edit
# Required:
#   OPENROUTER_API_KEY=sk-or-...
#   ESTAT_API_KEY=...      # free registration at https://api.e-stat.go.jp/
```

### Getting an e-Stat API key

1. Visit https://api.e-stat.go.jp/
2. Click "利用者登録" (User registration) — free
3. Confirm email and log in
4. Go to マイページ → APIキー → キー発行
5. Copy the key into `.env` as `ESTAT_API_KEY=...`

### Verifying e-Stat dataset IDs

The IDs in `estat_client.py` are starting points. To verify or update:

1. Visit https://www.e-stat.go.jp/
2. Search: `賃金構造基本統計調査 職業` → find the latest year's table
3. The URL will contain `statsDataId=XXXXXXXXX` — update `WAGE_STATS_DATA_ID`
4. Search: `労働力調査 詳細集計 職業別就業者` → update `EMPLOYMENT_STATS_DATA_ID`

---

## Pipeline — run in order

```bash
# Step 1 — Discover all occupations on Jobtag (~500)
uv run python scrape_occupations_jp.py
# → occupations_jp.json

# Step 2 — Download each occupation's detail page
uv run python scrape_jp.py
# → html_jp/<slug>.html  (takes ~15–20 min for ~500 pages)
# Resume-safe: re-run and it skips already-cached pages

# Step 3 — Fetch wage + employment data from e-Stat API
uv run python estat_client.py
# → estat_wages.json, estat_employment.json

# Step 4 — Convert HTML → Markdown (for LLM scoring)
uv run python process_jp.py
# → pages_jp/<slug>.md
# First run: add --diagnostic to inspect parsed output

# Step 5 — Build the statistics CSV (merge Jobtag + e-Stat)
uv run python make_csv_jp.py
# → occupations_jp.csv
# Review match_quality column — add manual overrides to jsoc_map.json if needed

# Step 6 — Score AI exposure with LLM
uv run python score_jp.py
# → scores_jp.json  (resumes if interrupted)
# Test first: uv run python score_jp.py --start 0 --end 20

# Step 7 — Build the site data file
uv run python build_site_data_jp.py
# → site/data_jp.json

# Step 8 — Serve locally
cd site && python -m http.server 8000
# Open: http://localhost:8000/index_jp.html
```

---

## Improving e-Stat matching quality

After running `make_csv_jp.py`, check the match quality breakdown printed to
the console. Occupations with `match_quality=none` have no wage or employment
data. You can add manual overrides by creating `jsoc_map.json`:

```json
{
  "occ-12345": { "pay_jpy": 6000000, "num_jobs": 85000 },
  "occ-67890": { "pay_jpy": 4500000, "num_jobs": 230000 }
}
```

The slugs come from `occupations_jp.json`. Pay is median annual JPY
(正規雇用 full-time workers). Job count is the total employed in Japan.

---

## Troubleshooting

**`scrape_occupations_jp.py` finds 0 occupations**
- Jobtag may have updated its DOM structure (common for government SPAs)
- Run with `headless=False` (default) and inspect the browser window
- Open DevTools and find the CSS selectors for occupation links
- Update the selectors in `scrape_occupations_jp.py`

**`parse_detail_jp.py` produces empty/thin markdown**
- Run `uv run python process_jp.py --diagnostic` to print DOM structure
- Identify the correct section heading CSS selectors and update `SECTION_KEYWORDS`
  or the selector logic in `parse_detail_jp.py`

**e-Stat API returns error**
- Verify your API key is correct in `.env`
- Check if the `statsDataId` values need updating (datasets are re-published annually)
- Inspect `estat_wages_raw.json` / `estat_employment_raw.json` for the actual
  response schema and update the parser in `estat_client.py` accordingly

---

## Frontend notes

The Japan frontend (`site/index_jp.html`) differs from the US version (`site/index.html`) in:

| Feature | US version | Japan version |
|---------|-----------|---------------|
| Title | AI Exposure of the **US** Job Market | AI Exposure of the **Japan** Job Market |
| Pay currency | USD ($) | JPY (¥) formatted in 万円 |
| Pay bands | <$35K … $100K+ | <¥3M … ¥10M+ |
| Occupation count | 342 | ~500 |
| Education tiers | No degree/HS … Doctoral | 中学・高卒 … 大学院卒 |
| Outlook field | % change 2024–34 | **Removed** |
| Wages stat | $ trillions | ¥ 兆 (trillions of yen) |
| Data source link | BLS OOH | Jobtag / e-Stat |
| Click action | Opens BLS page | Opens Jobtag page |
