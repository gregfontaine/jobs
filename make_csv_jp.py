"""
Build occupations_jp.csv from Jobtag HTML pages + e-Stat API data.

For each occupation in occupations_jp.json:
  - Extracts education requirements from the scraped Jobtag HTML
  - Matches to e-Stat wage data  (estat_wages.json)      → pay_jpy
  - Matches to e-Stat employment data (estat_employment.json) → num_jobs

Matching strategy (occupation name → e-Stat occupation):
  1. Exact name match
  2. Substring match (Jobtag name contains e-Stat name, or vice versa)
  3. Category-level fallback: average pay / proportional employment for the
     JSOC major group that the Jobtag occupation belongs to
  4. Still no match → pay_jpy and num_jobs left blank (handled gracefully
     in build_site_data_jp.py and the frontend)

Matching is logged so you can review quality and add manual overrides in
jsoc_map.json (see bottom of this file for format).

Usage:
    uv run python make_csv_jp.py
"""

import csv
import io
import json
import os
import re
import sys

from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# ── Text helpers ─────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    """Normalize Japanese text for fuzzy matching (strip spaces, punctuation)."""
    text = re.sub(r"[\s・・。、「」【】（）()・\-\/]+", "", text)
    # Normalize full-width to half-width digits
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    return text.lower()


# ── Education extraction from Jobtag HTML ─────────────────────────────────

EDU_SECTION_KEYWORDS = [
    "必要な資格", "資格・免許", "学歴", "教育", "取得資格", "資格要件", "免許",
]

# Canonical education tiers in display order
EDU_TIERS = [
    "大学院卒",       # Graduate (Master's / Doctoral)
    "大学卒",         # University graduate (Bachelor's)
    "短大卒",         # Junior college graduate (Associate's)
    "専門学校卒",     # Vocational school graduate
    "高卒",           # High school graduate
    "中学卒",         # Middle school graduate
    "学歴不問",       # No requirement
]

# Map Jobtag bar-chart labels → canonical tier
EDU_LABEL_MAP = {
    "高卒未満":   "中学卒",
    "中学卒":     "中学卒",
    "高卒":       "高卒",
    "専門学校卒": "専門学校卒",
    "短大卒":     "短大卒",
    "高専卒":     "短大卒",
    "大卒":       "大学卒",
    "大学卒":     "大学卒",
}
# Labels containing these substrings → 大学院卒
_GRAD_KEYWORDS = ("修士", "博士")


def extract_education(html_path: str) -> str:
    """Parse a Jobtag HTML file and return the most common education tier.

    Reads the education bar chart (inside #nav-tabContent-experienceEducations)
    and returns the tier with the highest percentage, skipping "わからない".
    """
    try:
        with open(html_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except Exception:
        return ""

    # Scope to the education chart container only (not training/experience charts)
    edu_container = soup.select_one("#nav-tabContent-experienceEducations")
    if not edu_container:
        return ""

    best_tier = ""
    best_pct = -1.0

    for row in edu_container.select("div.row-job-ex"):
        # Label is in the col-lg-2 div
        label_div = row.select_one("div.col-lg-2")
        if not label_div:
            continue
        label = label_div.get_text(strip=True)

        # Skip "わからない" (don't know)
        if "わからない" in label:
            continue

        # Percentage is in aria-valuenow of the progress bar
        bar = row.select_one("div.progress-bar[aria-valuenow]")
        if not bar:
            continue
        try:
            pct = float(bar["aria-valuenow"])
        except (ValueError, KeyError):
            continue

        # Map label to canonical tier
        tier = EDU_LABEL_MAP.get(label, "")
        if not tier:
            # Check for graduate-level labels (修士課程卒(...), 博士課程卒)
            if any(kw in label for kw in _GRAD_KEYWORDS):
                tier = "大学院卒"
        if not tier:
            continue

        if pct > best_pct:
            best_pct = pct
            best_tier = tier

    return best_tier


# ── e-Stat matching ──────────────────────────────────────────────────────────

def build_estat_index(records: list[dict], name_key: str) -> dict:
    """
    Build { normalized_name: record } index for fast lookup.
    Also stores by occupation_code for exact-code matching.
    """
    index = {}
    for r in records:
        name_norm = normalize(r[name_key])
        if name_norm:
            index[name_norm] = r
    return index


def match_estat_wage_by_name(
    title: str,
    wage_index: dict,
) -> dict | None:
    """Try to find an e-Stat wage record by name (exact then substring)."""
    title_norm = normalize(title)

    # Exact name match
    match = wage_index.get(title_norm)
    if match:
        return match

    # Substring match
    for norm_key, rec in wage_index.items():
        if norm_key in title_norm or title_norm in norm_key:
            return rec

    return None


def match_occupation(
    title: str,
    category_ja: str,
    wage_index: dict,
    emp_index:  dict,
    wage_records:  list[dict],
    emp_records:   list[dict],
    manual_map:    dict,
    slug:          str,
    category_occupation_counts: dict | None = None,
    estat_wage_by_code: dict | None = None,
    category_code: str | None = None,
) -> tuple[int | None, int | None, str]:
    """
    Return (pay_jpy, num_jobs, match_quality) for one Jobtag occupation.
    match_quality: "exact" | "substring" | "estat_code" | "category" | "none"
    """
    title_norm = normalize(title)

    # ── 0. Manual override ───────────────────────────────────────────────
    if slug in manual_map:
        override = manual_map[slug]
        pay  = override.get("pay_jpy")
        jobs = override.get("num_jobs")
        if pay or jobs:
            return pay, jobs, "manual"

    # ── 1. Exact name match ──────────────────────────────────────────────
    wage_match = wage_index.get(title_norm)
    emp_match  = emp_index.get(title_norm)

    if wage_match and emp_match:
        return wage_match["median_pay_jpy"], emp_match["employment"], "exact"

    # ── 2. Substring match (wages only) ─────────────────────────────────
    # Employment is NOT substring-matched: e-Stat employment data is at the
    # 中分類 group level, so matching e.g. "技術者" (3.89M engineers total) to
    # "3Dプリンター技術者" would assign 3.89M jobs to one specific occupation.
    # Wages can be substring-matched because salary for a group is a reasonable
    # proxy for occupations within it; employment cannot.
    if not wage_match:
        for norm_key, rec in wage_index.items():
            if norm_key in title_norm or title_norm in norm_key:
                wage_match = rec
                break

    if wage_match:
        pay = wage_match["median_pay_jpy"]
        return pay, None, "substring"

    # ── 3. e-Stat code match (category_code → occupation_code) ───────────
    if estat_wage_by_code and category_code and category_code in estat_wage_by_code:
        pay = estat_wage_by_code[category_code]
        return pay, None, "estat_code"

    # ── 4. Category-level fallback ───────────────────────────────────────
    # Find e-Stat records whose occupation name contains the JSOC major group
    # keyword from the Jobtag category.
    cat_keywords = _jsoc_keywords_for_category(category_ja)
    cat_wages  = [r for r in wage_records
                  if any(kw in r["occupation_name"] for kw in cat_keywords)]
    cat_emps   = [r for r in emp_records
                  if any(kw in r["occupation_name"] for kw in cat_keywords)]

    pay  = int(sum(r["median_pay_jpy"] for r in cat_wages) / len(cat_wages)) if cat_wages else None

    # Distribute category-level employment count evenly across occupations in category.
    # Use max() not sum() because employment data includes both 大分類 totals and 中分類
    # sub-groups — summing them would double-count. The 大分類 record is the largest.
    jobs = None
    if cat_emps and category_occupation_counts:
        total_cat_emp = max(r["employment"] for r in cat_emps)
        n_occs = category_occupation_counts.get(category_ja, 1)
        jobs = int(total_cat_emp / n_occs)

    if pay is not None:
        return pay, jobs, "category"

    return None, None, "none"


def _jsoc_keywords_for_category(category_ja: str) -> list[str]:
    """Return Japanese keywords to find e-Stat records for this JSOC major group."""
    mapping = {
        "管理":       ["管理"],
        "専門":       ["専門", "技術"],
        "事務":       ["事務"],
        "販売":       ["販売"],
        "サービス":   ["サービス"],
        "保安":       ["保安"],
        "農":         ["農", "林", "漁"],
        "生産":       ["生産", "工程"],
        "輸送":       ["輸送", "運転"],
        "建設":       ["建設", "採掘"],
        "運搬":       ["運搬", "清掃", "包装"],
    }
    for key, kws in mapping.items():
        if key in category_ja:
            return kws
    return []


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Load occupation list
    with open("occupations_jp.json", encoding="utf-8") as f:
        occupations = json.load(f)

    # Load Jobtag-native stats (primary source — per-occupation from scraped HTML)
    jobtag_stats = {}
    if os.path.exists("jobtag_stats.json"):
        with open("jobtag_stats.json", encoding="utf-8") as f:
            jobtag_stats = json.load(f)
        print(f"Loaded {len(jobtag_stats)} Jobtag wage/employment records from jobtag_stats.json")
    else:
        print("jobtag_stats.json not found — run extract_jobtag_stats.py first")

    # ── Load curated pay/jobs overrides (primary source) ──────────────────
    # occupations_updated.csv contains manually researched salary and employment
    # data from Jobtag v7. Values override all computed sources.
    pay_jobs_overrides: dict[str, dict] = {}
    if os.path.exists("occupations_updated.csv"):
        with open("occupations_updated.csv", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                slug = row["slug"].strip()
                pay_raw  = row.get(" pay_jpy ",  row.get("pay_jpy",  "")).strip().replace(",", "")
                jobs_raw = row.get(" num_jobs ", row.get("num_jobs", "")).strip().replace(",", "")
                pay_jobs_overrides[slug] = {
                    "pay":     int(pay_raw)  if pay_raw.isdigit()  else None,
                    "jobs":    int(jobs_raw) if jobs_raw.isdigit() else None,
                    "quality": row.get("match_quality", "").strip(),
                }
        print(f"Loaded {len(pay_jobs_overrides)} pay/jobs overrides from occupations_updated.csv")
    else:
        print("occupations_updated.csv not found — using computed values")

    # Build CSV
    fieldnames = [
        "title", "category", "category_ja", "slug", "jobtag_id",
        "pay_jpy", "num_jobs", "entry_education", "url", "match_quality",
    ]

    rows = []
    match_stats: dict[str, int] = {}
    missing_html = 0
    override_used = 0

    for occ in occupations:
        slug      = occ["slug"]
        html_path = f"html_jp/{slug}.html"

        education = ""
        if os.path.exists(html_path):
            education = extract_education(html_path)
        else:
            missing_html += 1

        # ── Resolve pay & jobs from curated overrides ────────────────────
        override = pay_jobs_overrides.get(slug)
        if override and (override["pay"] is not None or override["jobs"] is not None):
            pay     = override["pay"]
            jobs    = override["jobs"]
            quality = override["quality"] or "override"
            override_used += 1
        else:
            # Fallback: use Jobtag stats directly (only for occupations
            # not covered by the curated override file)
            jt = jobtag_stats.get(slug)
            if jt:
                pay     = jt["wage_jpy"]
                jobs    = jt.get("workers")
                quality = "jobtag"
            else:
                pay     = None
                jobs    = None
                quality = "none"

        match_stats[quality] = match_stats.get(quality, 0) + 1

        rows.append({
            "title":          occ["title"],
            "category":       occ["category"],
            "category_ja":    occ.get("category_ja", ""),
            "slug":           slug,
            "jobtag_id":      occ.get("jobtag_id", ""),
            "pay_jpy":        pay or "",
            "num_jobs":       jobs or "",
            "entry_education": education,
            "url":            occ.get("url", ""),
            "match_quality":  quality,
        })

    with open("occupations_jp.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} rows to occupations_jp.csv")
    print(f"Curated overrides applied: {override_used}")
    print(f"Missing HTML files: {missing_html}")
    print("\nMatch quality breakdown:")
    for q, count in match_stats.items():
        bar = "█" * count
        print(f"  {q:12s} {count:4d}  {bar}")

    unmatched = [r for r in rows if r["match_quality"] == "none"]
    if unmatched:
        print(f"\n{len(unmatched)} occupations with no pay/employment match.")
        print("Consider adding them to jsoc_map.json (format below):")
        print('  { "<slug>": { "pay_jpy": 5000000, "num_jobs": 50000 } }')

    # Sample output
    print("\nSample rows:")
    for r in rows[:5]:
        print(f"  {r['title']}: ¥{r['pay_jpy']:,} / {r['num_jobs']} jobs "
              f"/ {r['entry_education']} [{r['match_quality']}]"
              if r["pay_jpy"] else
              f"  {r['title']}: (no pay data) [{r['match_quality']}]")


if __name__ == "__main__":
    main()
