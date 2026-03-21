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

# Keyword → canonical tier
EDU_KEYWORD_MAP = {
    "大学院":   "大学院卒",
    "修士":     "大学院卒",
    "博士":     "大学院卒",
    "大学":     "大学卒",
    "学士":     "大学卒",
    "短期大学": "短大卒",
    "短大":     "短大卒",
    "専門学校": "専門学校卒",
    "専門":     "専門学校卒",
    "高等学校": "高卒",
    "高校":     "高卒",
    "中学":     "中学卒",
    "学歴不問": "学歴不問",
    "不問":     "学歴不問",
}


def extract_education(html_path: str) -> str:
    """Parse a Jobtag HTML file and return the minimum required education tier."""
    try:
        with open(html_path, encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")
    except Exception:
        return ""

    # Remove scripts / styles
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Find section containing education keywords
    text = soup.get_text(separator=" ")

    # Look for the education-related segment
    for kw in EDU_SECTION_KEYWORDS:
        idx = text.find(kw)
        if idx != -1:
            segment = text[idx:idx + 300]
            # Return the highest (most advanced) tier found
            for tier_kw, tier in EDU_KEYWORD_MAP.items():
                if tier_kw in segment:
                    return tier
            break

    # Fallback: scan entire text for education keywords
    for tier_kw, tier in EDU_KEYWORD_MAP.items():
        if tier_kw in text:
            return tier

    return ""


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
) -> tuple[int | None, int | None, str]:
    """
    Return (pay_jpy, num_jobs, match_quality) for one Jobtag occupation.
    match_quality: "exact" | "substring" | "category" | "none"
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
        # emp_match deliberately left None — will fall through to category fallback
        return pay, None, "substring"

    # ── 3. Category-level fallback ───────────────────────────────────────
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

    # Load e-Stat data (fallback for any occupations missing Jobtag data)
    wage_records = []
    if os.path.exists("estat_wages.json"):
        with open("estat_wages.json", encoding="utf-8") as f:
            wage_records = json.load(f)
        print(f"Loaded {len(wage_records)} e-Stat wage records (fallback)")
    else:
        print("estat_wages.json not found")

    emp_records = []
    if os.path.exists("estat_employment.json"):
        with open("estat_employment.json", encoding="utf-8") as f:
            emp_records = json.load(f)
        print(f"Loaded {len(emp_records)} e-Stat employment records (fallback)")
    else:
        print("estat_employment.json not found")

    # Load manual overrides (optional — create jsoc_map.json to add hand-matched data)
    manual_map = {}
    if os.path.exists("jsoc_map.json"):
        with open("jsoc_map.json", encoding="utf-8") as f:
            manual_map = json.load(f)
        print(f"Loaded {len(manual_map)} manual overrides from jsoc_map.json")

    wage_index = build_estat_index(wage_records, "occupation_name")
    emp_index  = build_estat_index(emp_records,  "occupation_name")

    # Count how many Jobtag occupations fall in each JSOC category (for distributing employment)
    category_occupation_counts: dict[str, int] = {}
    for occ in occupations:
        cja = occ.get("category_ja", "")
        category_occupation_counts[cja] = category_occupation_counts.get(cja, 0) + 1

    # Build CSV
    fieldnames = [
        "title", "category", "category_ja", "slug", "jobtag_id",
        "pay_jpy", "num_jobs", "entry_education", "url", "match_quality",
    ]

    rows = []
    match_stats = {"jobtag": 0, "exact": 0, "substring": 0, "category": 0, "manual": 0, "none": 0}
    missing_html = 0

    for occ in occupations:
        slug      = occ["slug"]
        html_path = f"html_jp/{slug}.html"

        education = ""
        if os.path.exists(html_path):
            education = extract_education(html_path)
        else:
            missing_html += 1

        # ── Primary: Jobtag-native stats (scraped from detail pages) ─────
        jt = jobtag_stats.get(slug)
        if jt:
            pay     = jt["wage_jpy"]
            jobs    = jt["workers"]
            quality = "jobtag"
            match_stats[quality] = match_stats.get(quality, 0) + 1
        else:
            # ── Fallback: e-Stat matching ─────────────────────────────────
            pay, jobs, quality = match_occupation(
                title=occ["title"],
                category_ja=occ.get("category_ja", ""),
                wage_index=wage_index,
                emp_index=emp_index,
                wage_records=wage_records,
                emp_records=emp_records,
                manual_map=manual_map,
                slug=slug,
                category_occupation_counts=category_occupation_counts,
            )
            match_stats[quality] += 1

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
