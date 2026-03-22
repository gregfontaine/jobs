# AI Exposure of the Japan Job Market

Bilingual (Japanese/English) interactive visualization of AI exposure across 556 Japanese occupations. Includes a treemap view, a sortable list/ranking view, search, deep-linkable occupation modals, and sidebar analytics.

**Live site:** `site/index_jp.html` — serve locally or deploy to any static host.

---

## Features

- **Treemap view** — area = employment, color = AI exposure (0–10 scale)
- **List/ranking view** — sortable table by exposure, pay, jobs, or category; category filter
- **Search** — finds occupations by Japanese or English name; dropdown in treemap, inline filter in list view
- **Occupation modal** — click any tile or row for full details: pay, jobs, education, AI rationale, Jobtag link, and shareable URL
- **Deep linking** — shareable hash-based URLs (`#/ja/{slug}` or `#/en/{slug}`), browser Back/Forward support
- **Bilingual** — full JP/EN toggle for all UI text, occupation titles, descriptions, and AI rationales
- **Sidebar analytics** — total employment, weighted average exposure, histogram, tier breakdown, exposure by pay band and education level

---

## Data sources & methodology

| Data | Source | Notes |
|------|--------|-------|
| Occupation profiles | [Jobtag](https://shigoto.mhlw.go.jp/) (MHLW) | 556 occupations with descriptions, education requirements |
| Median wages | Jobtag — sourced from 2024 Wage Structure Survey (賃金構造基本統計調査) | Median annual pay for full-time workers |
| Employment counts | 2020 Census (国勢調査) via Jobtag | JSOC classification-level counts |
| AI exposure scores | [OpenRouter](https://openrouter.ai/) → NVIDIA Nemotron | LLM-scored on 0–10 scale with English rationale |
| Translations | OpenRouter → Google Gemini Flash | 556 English titles, descriptions, and Japanese rationales |

### Salary data

Salary figures are **median annual pay** from Japan's 2024 Wage Structure Survey (賃金構造基本統計調査), as reported on Jobtag. These represent full-time (正規雇用) workers.

Six occupations — public servants, executives, and Diet members — use manual estimates from official sources because Jobtag does not report their salaries through the standard survey.

### Employment data

Job counts come from the **2020 Census (国勢調査)** and total **~59.8 million workers**, covering about 88% of Japan's ~68 million workforce. The remaining ~12% falls into Census categories not mapped to any of the 556 occupations listed.

**Important caveat on individual occupation counts:** The Census reports worker counts at a classification level broader than individual occupations. When multiple Jobtag occupations share the same Census classification, the worker pool is **split equally** among them. For example, Jobtag reports 389,760 workers for the software development classification, but 9 distinct occupations fall under it (システムエンジニア, プログラマー, UX/UIデザイナー, ブロックチェーン・エンジニア, etc.), so each gets ~43,300. In reality, プログラマー is almost certainly larger than ブロックチェーン・エンジニア, but the Census doesn't break it down further.

**Category-level totals are accurate; individual splits within a shared group are approximations.**

### Keep in mind

Both salary and worker count figures should be interpreted with these caveats in mind, particularly for:
- **Fast-growing fields** (e.g. AI engineering, data science) — the 2020 Census may undercount roles that have grown significantly since then
- **Declining fields** (e.g. print media, interpreters) — Census counts may overstate current employment

### Outlook

The outlook/projection feature from [Andrej Karpathy's US version](https://github.com/karpathy/jobs) has been removed. Japan has no occupation-level 10-year employment projection source equivalent to the US BLS Occupational Outlook Handbook. Rather than display misleading data, the field is absent from the Japan version.

---

## Setup

```bash
# 1. Install dependencies
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

---

## Pipeline — run in order

```bash
# Step 1 — Discover all occupations on Jobtag (~556)
uv run python scrape_occupations_jp.py
# → occupations_jp.json

# Step 2 — Download each occupation's detail page
uv run python scrape_jp.py
# → html_jp/<slug>.html  (takes ~15–20 min)
# Resume-safe: re-run and it skips already-cached pages

# Step 3 — Extract per-occupation salary and worker data from Jobtag HTML
uv run python extract_jobtag_stats.py
# → jobtag_stats.json

# Step 4 — Convert HTML → Markdown (for LLM scoring)
uv run python process_jp.py
# → pages_jp/<slug>.md

# Step 5 — Build the statistics CSV
uv run python make_csv_jp.py
# → occupations_jp.csv
# Uses occupations_updated.csv as primary source (curated Jobtag v7 data),
# falls back to jobtag_stats.json for any missing occupations

# Step 6 — Score AI exposure with LLM
uv run python score_jp.py
# → scores_jp.json  (resumes if interrupted)
# Test first: uv run python score_jp.py --start 0 --end 20

# Step 7 — Translate descriptions and rationales
uv run python translate_jp.py
# → translations_jp.json  (resumes if interrupted)

# Step 8 — Translate occupation titles to English
uv run python translate_titles_jp.py
# → updates translations_jp.json with title_en field

# Step 9 — Build the site data file
uv run python build_site_data_jp.py
# → site/data_jp.json

# Step 10 — Serve locally
cd site && python -m http.server 8000
# Open: http://localhost:8000/index_jp.html
```

---

## Curated salary & employment data

The primary source for salary and employment data is `occupations_updated.csv`, a manually curated file with Jobtag v7 data for all 556 occupations. This was created to resolve cases where automated e-Stat matching produced clustered or inaccurate values (e.g. multiple software occupations all showing the same salary because they share a Census classification).

`make_csv_jp.py` loads this file as the primary source and falls back to `jobtag_stats.json` (extracted from scraped HTML) for any occupations not covered.

---

## Frontend

The site (`site/index_jp.html`) is a single-file vanilla JS application with inline CSS and JS — no build step, no dependencies.

| Feature | Description |
|---------|-------------|
| Treemap | Canvas-based squarified treemap, area = jobs, color = AI exposure |
| List view | Sortable table with rank, title, exposure, pay, jobs, category |
| Search | Pill-shaped input; dropdown in treemap mode, inline filter in list mode |
| Modal | Persistent detail view on click; shows all fields + AI rationale |
| Deep links | Hash-based URLs (`#/ja/occ-123`, `#/en/occ-123`); share button with clipboard/native share |
| Bilingual | JP/EN toggle; titles, descriptions, rationales, and all UI text switch language |
| Sidebar | Total employment, weighted avg exposure, histogram, tier breakdown, pay/education charts |

### Differences from the US version

| Feature | US version | Japan version |
|---------|-----------|---------------|
| Pay currency | USD ($) | JPY (¥) formatted in 万円 |
| Pay bands | <$35K … $100K+ | <¥3M … ¥10M+ |
| Occupation count | ~800 | 556 |
| Education tiers | No degree/HS … Doctoral | 中学・高卒 … 大学院卒 |
| Outlook field | % change 2024–34 | Removed |
| Wages stat | $ trillions | ¥ 兆 (trillions of yen) |
| Data source | BLS OOH | Jobtag / e-Stat / Census |
| Click action | Opens BLS page | Opens detail modal |
| View modes | Treemap only | Treemap + sortable list |
| Search | — | Full search with dropdown |
| Deep linking | — | Shareable hash-based URLs |
| Bilingual | English only | Japanese + English |

---

## Troubleshooting

**`scrape_occupations_jp.py` finds 0 occupations**
- Jobtag may have updated its DOM structure
- Run with `headless=False` (default) and inspect the browser window
- Update the CSS selectors in `scrape_occupations_jp.py`

**`parse_detail_jp.py` produces empty/thin markdown**
- Run `uv run python process_jp.py --diagnostic` to inspect parsed output
- Update section heading selectors in `parse_detail_jp.py`

**e-Stat API returns error**
- Verify your API key in `.env`
- Check if `statsDataId` values need updating (datasets are re-published annually)
- Inspect raw response files and update the parser in `estat_client.py`

---

## Acceptance tests

```bash
uv run python test_pipeline_jp.py
```

Runs 23 tests across salary, employment, education, and AI exposure for representative occupations (medical, tech, legal, education, trades, service, clerical). All values are range-checked against known data.

---

> Icon was designed by my daughter who made me promise to use it (-_-;)
