"""
Scrape Jobtag (shigoto.mhlw.go.jp) to build the Japan occupation list.

Uses the /User/Search/Result?keyword= endpoint (all occupations) with
click-based pagination (the site was redesigned 2026-03-17 — the old
/User/OccupationTypeList URL no longer exists).

Each search result card contains:
  data-id        — numeric Jobtag ID
  data-cate      — JSOC 中分類 name (e.g. "会社役員")
  data-codelist  — JSOC code (e.g. "001-01")
  <h4 .card-title><a .occupation-detail> — occupation title

Saves occupations_jp.json with schema:
    [{ "title": "会計士", "url": "https://shigoto.mhlw.go.jp/...",
       "category": "Professional & Technical", "category_ja": "専門的・技術的職業",
       "slug": "occ-12345", "jobtag_id": "12345" }, ...]

Usage:
    uv run python scrape_occupations_jp.py
    uv run python scrape_occupations_jp.py --force   # re-scrape even if cached
"""

import argparse
import io
import json
import os
import re
import sys
import time

# Windows cp1252 fix — Japanese characters in print() crash otherwise
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE_URL = "https://shigoto.mhlw.go.jp"
SEARCH_URL = f"{BASE_URL}/User/Search/Result?keyword="
OUTPUT_FILE = "occupations_jp.json"


# ── JSOC code prefix → (English major group, Japanese major group) ─────────
# Based on Jobtag's internal numbering (empirically verified):
#   001     → 管理的職業
#   010-029 → 専門的・技術的職業
#   030-039 → 事務的職業
#   040-049 → 販売の職業
#   050-059 → サービス職業
#   060-069 → 保安職業
#   070-079 → 農林漁業
#   080-089 → 生産工程の職業
#   090-099 → 輸送・機械運転の職業
#   100-109 → 建設・採掘の職業
#   110+    → 運搬・清掃・包装等の職業
def code_to_category(code: str) -> tuple[str, str]:
    """Map Jobtag JSOC code (e.g. '045-14') to (English, Japanese) major group.

    Ranges empirically verified from Jobtag category-sorted search (2026-03):
      001-003  管理的職業           (Management)
      004-032  専門的・技術的職業    (Professional & Technical)
      033-043  事務的職業           (Clerical & Administrative)
      044-048  販売の職業           (Sales)
      049-058  サービス職業         (Service)
      059-063  保安職業             (Security)
      064-066  農林漁業             (Agriculture, Forestry & Fishing)
      067-081  生産工程の職業       (Production & Manufacturing)
      082-089  輸送・機械運転の職業 (Transportation & Machine Operation)
      090-094  建設・採掘の職業     (Construction & Mining)
      095-099  運搬・清掃・包装等   (Logistics & Cleaning)
    """
    try:
        prefix = int(code.split("-")[0])
    except (ValueError, IndexError):
        return _keyword_fallback(code)

    if prefix <= 3:
        return "Management", "管理的職業"
    elif prefix <= 32:
        return "Professional & Technical", "専門的・技術的職業"
    elif prefix <= 43:
        return "Clerical & Administrative", "事務的職業"
    elif prefix <= 48:
        return "Sales", "販売の職業"
    elif prefix <= 58:
        return "Service", "サービス職業"
    elif prefix <= 63:
        return "Security", "保安職業"
    elif prefix <= 66:
        return "Agriculture, Forestry & Fishing", "農林漁業"
    elif prefix <= 81:
        return "Production & Manufacturing", "生産工程の職業"
    elif prefix <= 89:
        return "Transportation & Machine Operation", "輸送・機械運転の職業"
    elif prefix <= 94:
        return "Construction & Mining", "建設・採掘の職業"
    else:
        return "Logistics & Cleaning", "運搬・清掃・包装等の職業"


def _keyword_fallback(text: str) -> tuple[str, str]:
    """Keyword matching fallback when code is unavailable."""
    if "管理" in text:
        return "Management", "管理的職業"
    if "専門" in text or "技術" in text:
        return "Professional & Technical", "専門的・技術的職業"
    if "事務" in text:
        return "Clerical & Administrative", "事務的職業"
    if "販売" in text:
        return "Sales", "販売の職業"
    if "サービス" in text:
        return "Service", "サービス職業"
    if "保安" in text:
        return "Security", "保安職業"
    if "農" in text or "林" in text or "漁" in text:
        return "Agriculture, Forestry & Fishing", "農林漁業"
    if "生産" in text or "工程" in text:
        return "Production & Manufacturing", "生産工程の職業"
    if "輸送" in text or "運転" in text:
        return "Transportation & Machine Operation", "輸送・機械運転の職業"
    if "建設" in text or "採掘" in text:
        return "Construction & Mining", "建設・採掘の職業"
    if "運搬" in text or "清掃" in text or "包装" in text:
        return "Logistics & Cleaning", "運搬・清掃・包装等の職業"
    return "Other", text


def harvest_page(page) -> list[dict]:
    """Extract all occupation entries from the current search result page."""
    results = []
    seen_ids = set()

    # Each result card has a button with data-id, data-cate, data-codelist
    buttons = page.query_selector_all("button[data-id][data-cate][data-codelist]")
    for btn in buttons:
        occ_id = btn.get_attribute("data-id") or ""
        if not occ_id or occ_id in seen_ids:
            continue
        seen_ids.add(occ_id)

        data_cate = btn.get_attribute("data-cate") or ""
        data_code = btn.get_attribute("data-codelist") or ""

        # Title: find the <h4> title link for this card via data-id
        title_el = page.query_selector(
            f"h4.card-title a[data-id='{occ_id}'], "
            f"a.occupation-detail[data-id='{occ_id}']"
        )
        title = (title_el.text_content() if title_el else "").strip()
        if not title:
            # fallback: button data-name attribute
            title = btn.get_attribute("data-name") or ""
        if not title:
            continue

        url = f"{BASE_URL}/User/Occupation/Detail/{occ_id}"

        # Determine major group
        cat_en, cat_ja = code_to_category(data_code) if data_code else _keyword_fallback(data_cate)

        results.append({
            "title": title,
            "url": url,
            "category": cat_en,
            "category_ja": cat_ja,
            "slug": f"occ-{occ_id}",
            "jobtag_id": occ_id,
        })

    return results


def scrape_all_occupations(page) -> list[dict]:
    """Paginate through all search results and collect every occupation."""
    print(f"Loading {SEARCH_URL} …")
    page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
    time.sleep(3)

    # Check total count
    body_text = page.inner_text("body")
    total_match = re.search(r"全\s*([\d,]+)\s*件", body_text)
    total = int(total_match.group(1).replace(",", "")) if total_match else "?"
    print(f"Total occupations on site: {total}")

    all_occupations = {}  # id → dict, deduplicated across pages
    page_num = 1

    while True:
        # Harvest current page
        entries = harvest_page(page)
        new = 0
        for e in entries:
            if e["jobtag_id"] not in all_occupations:
                all_occupations[e["jobtag_id"]] = e
                new += 1

        range_match = re.search(r"([\d,]+)\s*件\s*〜\s*([\d,]+)\s*件", page.inner_text("body"))
        range_str = range_match.group(0) if range_match else f"page {page_num}"
        print(f"  Page {page_num} ({range_str}): {new} new — total so far: {len(all_occupations)}")

        # Find next page button
        next_page = page_num + 1
        next_btn = page.query_selector(f".pageNumber[value='{next_page}']")

        # Also look for the "next" arrow button
        if not next_btn:
            # Try the arrow/next button (has an img with alt containing 次)
            arrow = page.query_selector("a.pageNumber img[alt*='次']")
            if arrow:
                next_btn = arrow.evaluate_handle("el => el.closest('a')")

        if not next_btn:
            print(f"  No page {next_page} button found — done.")
            break

        try:
            next_btn.click()
            page.wait_for_load_state("networkidle", timeout=15000)
            time.sleep(1.5)
            page_num += 1
        except Exception as e:
            print(f"  Pagination error on page {next_page}: {e}")
            break

    return list(all_occupations.values())


def main():
    parser = argparse.ArgumentParser(description="Scrape Jobtag occupation list")
    parser.add_argument("--force", action="store_true",
                        help="Re-scrape even if occupations_jp.json already exists")
    args = parser.parse_args()

    if not args.force and os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            existing = json.load(f)
        print(f"Already have {len(existing)} occupations in {OUTPUT_FILE}. "
              f"Use --force to re-scrape.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8"})

        occupations = scrape_all_occupations(page)
        browser.close()

    if not occupations:
        print("\n⚠  No occupations found.")
        print("   The Jobtag site may have been redesigned again.")
        print("   Run diag_jobtag.py to inspect the current DOM structure.")
        return

    # Sort by category then title
    occupations.sort(key=lambda o: (o["category"], o["title"]))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(occupations, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(occupations)} occupations to {OUTPUT_FILE}")

    # Summary by category
    by_cat: dict[str, int] = {}
    for o in occupations:
        by_cat[o["category"]] = by_cat.get(o["category"], 0) + 1
    print("\nBreakdown by category:")
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {count:3d}  {cat}")


if __name__ == "__main__":
    main()
