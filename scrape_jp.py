"""
Scrape Jobtag occupation detail pages (raw HTML).

Reads occupations_jp.json, downloads each occupation's detail page with
non-headless Playwright (Jobtag uses Incapsula bot protection), and caches
raw HTML to html_jp/<slug>.html.

Usage:
    uv run python scrape_jp.py                      # scrape all
    uv run python scrape_jp.py --start 0 --end 10   # first 10
    uv run python scrape_jp.py --force               # ignore cache
    uv run python scrape_jp.py --delay 2.0           # polite delay
"""

import argparse
import io
import json
import os
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description="Scrape Jobtag occupation pages")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end",   type=int, default=None)
    parser.add_argument("--force", action="store_true", help="Re-scrape even if cached")
    parser.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between requests (default 1.5)")
    args = parser.parse_args()

    with open("occupations_jp.json", encoding="utf-8") as f:
        occupations = json.load(f)

    end = args.end if args.end is not None else len(occupations)
    subset = occupations[args.start:end]

    os.makedirs("html_jp", exist_ok=True)
    os.makedirs("pages_jp", exist_ok=True)

    to_scrape = []
    for i, occ in enumerate(subset, start=args.start):
        html_path = f"html_jp/{occ['slug']}.html"
        if not args.force and os.path.exists(html_path):
            print(f"  [{i}] CACHED  {occ['title']}")
            continue
        to_scrape.append((i, occ))

    if not to_scrape:
        print("Nothing to scrape — all cached.")
        return

    print(f"\nScraping {len(to_scrape)} occupations (non-headless Chromium) …\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_extra_http_headers({"Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8"})

        for idx, (i, occ) in enumerate(to_scrape):
            slug = occ["slug"]
            url  = occ["url"]
            html_path = f"html_jp/{slug}.html"

            print(f"  [{i}] {occ['title']} …", end=" ", flush=True)

            try:
                resp = page.goto(url, wait_until="networkidle", timeout=20000)
                if resp is None or resp.status != 200:
                    status = resp.status if resp else "?"
                    print(f"HTTP {status} — SKIPPED")
                    continue

                # Wait for the main content to render (JS-heavy SPA)
                # Try to wait for a heading or content container
                try:
                    page.wait_for_selector(
                        "h1, .occupation-title, [class*='title'], main",
                        timeout=8000
                    )
                except Exception:
                    pass  # render timeout — still save whatever we have

                html = page.content()
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(html)

                print(f"OK ({len(html):,} bytes)")

            except Exception as e:
                print(f"ERROR: {e}")

            if idx < len(to_scrape) - 1:
                time.sleep(args.delay)

        browser.close()

    cached = len([f for f in os.listdir("html_jp") if f.endswith(".html")])
    print(f"\nDone. {cached}/{len(occupations)} HTML files in html_jp/")


if __name__ == "__main__":
    main()
