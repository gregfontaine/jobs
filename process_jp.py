"""
Batch-convert scraped Jobtag HTML files to Markdown.

Reads from html_jp/<slug>.html, writes to pages_jp/<slug>.md.
Caches: skips any .md that already exists (use --force to re-process).

Usage:
    uv run python process_jp.py
    uv run python process_jp.py --force
    uv run python process_jp.py --diagnostic   # run DOM diagnostic on first file
"""

import argparse
import json
import os
from parse_detail_jp import parse_jobtag_page, dom_diagnostic


def main():
    parser = argparse.ArgumentParser(description="Convert Jobtag HTML to Markdown")
    parser.add_argument("--force", action="store_true",
                        help="Re-process even if .md already exists")
    parser.add_argument("--diagnostic", action="store_true",
                        help="Print DOM diagnostic for the first HTML file processed")
    args = parser.parse_args()

    os.makedirs("pages_jp", exist_ok=True)

    with open("occupations_jp.json", encoding="utf-8") as f:
        occupations = json.load(f)

    processed = 0
    skipped   = 0
    missing   = 0
    diag_done = False

    for occ in occupations:
        slug      = occ["slug"]
        html_path = f"html_jp/{slug}.html"
        md_path   = f"pages_jp/{slug}.md"

        if not os.path.exists(html_path):
            missing += 1
            continue

        if not args.force and os.path.exists(md_path):
            skipped += 1
            continue

        if args.diagnostic and not diag_done:
            dom_diagnostic(html_path)
            diag_done = True

        md = parse_jobtag_page(html_path, source_url=occ.get("url", ""))
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        processed += 1

    total_html = len([f for f in os.listdir("html_jp") if f.endswith(".html")])
    total_md   = len([f for f in os.listdir("pages_jp") if f.endswith(".md")])
    print(f"Processed: {processed}, Skipped (cached): {skipped}, Missing HTML: {missing}")
    print(f"Total: {total_html} HTML files, {total_md} Markdown files in pages_jp/")


if __name__ == "__main__":
    main()
