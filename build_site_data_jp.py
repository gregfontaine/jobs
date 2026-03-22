"""
Build site/data_jp.json by merging occupations_jp.csv with scores_jp.json.

No outlook field — that feature is intentionally omitted for the Japan
dataset because no occupation-level 10-year projection source exists.

Output schema per occupation:
  {
    "title":              "会計士",            # Japanese title
    "slug":               "occ-12345",
    "category":           "Professional & Technical",  # English display name
    "category_ja":        "専門的・技術的職業",          # Japanese (tooltip)
    "pay":                6000000,            # median annual pay in JPY (int)
    "jobs":               120000,             # employment count (int or null)
    "education":          "大学卒",           # Japanese education tier
    "exposure":           7,                  # AI exposure score 0-10
    "exposure_rationale":    "...",            # AI rationale in English
    "exposure_rationale_ja": "...",            # AI rationale in Japanese
    "description_ja":        "...",            # Japanese job description (from Jobtag)
    "description_en":        "...",            # English job description (translated)
    "url":                   "https://shigoto.mhlw.go.jp/..."
  }

Usage:
    uv run python build_site_data_jp.py
"""

import csv
import io
import json
import os
import re
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def extract_description_ja(slug: str) -> str:
    """Extract the 'どんな仕事？' section from pages_jp/{slug}.md."""
    md_path = f"pages_jp/{slug}.md"
    if not os.path.exists(md_path):
        return ""
    with open(md_path, encoding="utf-8") as f:
        text = f.read()
    # Find the どんな仕事？ section
    m = re.search(r"##\s*どんな仕事？\s*\n(.*?)(?:\n##|\Z)", text, re.DOTALL)
    if not m:
        return ""
    # Take the first sentence or up to ~200 chars, stripping whitespace
    content = re.sub(r"\s+", " ", m.group(1)).strip()
    # Trim to a reasonable length at a sentence boundary
    if len(content) > 200:
        # Try to cut at a Japanese sentence-ending punctuation
        cut = re.search(r".{80,200}[。！？]", content)
        if cut:
            content = cut.group(0)
        else:
            content = content[:200] + "…"
    return content


def main():
    # ── Load scores ───────────────────────────────────────────────────────
    if not os.path.exists("scores_jp.json"):
        print("ERROR: scores_jp.json not found. Run score_jp.py first.")
        return
    with open("scores_jp.json", encoding="utf-8") as f:
        scores_list = json.load(f)
    scores = {s["slug"]: s for s in scores_list}
    print(f"Loaded {len(scores)} AI exposure scores")

    # ── Load CSV ──────────────────────────────────────────────────────────
    if not os.path.exists("occupations_jp.csv"):
        print("ERROR: occupations_jp.csv not found. Run make_csv_jp.py first.")
        return
    with open("occupations_jp.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"Loaded {len(rows)} occupation rows from occupations_jp.csv")

    # ── Load translations (optional — run translate_jp.py first) ────────
    translations: dict[str, dict] = {}
    if os.path.exists("translations_jp.json"):
        with open("translations_jp.json", encoding="utf-8") as f:
            for entry in json.load(f):
                translations[entry["slug"]] = entry
        print(f"Loaded {len(translations)} translations from translations_jp.json")
    else:
        print("translations_jp.json not found — description_en / exposure_rationale_ja will be empty")

    # ── Merge ─────────────────────────────────────────────────────────────
    data = []
    missing_scores = 0

    for row in rows:
        slug  = row["slug"]
        score = scores.get(slug, {})

        if not score:
            missing_scores += 1

        pay_raw  = row.get("pay_jpy", "").strip()
        jobs_raw = row.get("num_jobs", "").strip()

        pay  = int(pay_raw)  if pay_raw.isdigit()  else None
        jobs = int(jobs_raw) if jobs_raw.isdigit() else None

        tr = translations.get(slug, {})

        data.append({
            "title":                 row["title"],
            "slug":                  slug,
            "category":              row["category"],
            "category_ja":           row.get("category_ja", ""),
            "pay":                   pay,
            "jobs":                  jobs,
            "education":             row.get("entry_education", ""),
            "exposure":              score.get("exposure"),
            "exposure_rationale":    score.get("rationale"),
            "exposure_rationale_ja": tr.get("exposure_rationale_ja", ""),
            "description_ja":        extract_description_ja(slug),
            "description_en":        tr.get("description_en", ""),
            "url":                   row.get("url", ""),
        })

    os.makedirs("site", exist_ok=True)
    with open("site/data_jp.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    print(f"\nWrote {len(data)} occupations to site/data_jp.json")
    if missing_scores:
        print(f"⚠  {missing_scores} occupations have no AI exposure score yet")

    # ── Summary stats ─────────────────────────────────────────────────────
    total_jobs = sum(d["jobs"] for d in data if d["jobs"])
    print(f"Total employment represented: {total_jobs:,}")

    scored = [d for d in data if d["exposure"] is not None and d["jobs"]]
    if scored:
        weighted_sum   = sum(d["exposure"] * d["jobs"] for d in scored)
        weighted_count = sum(d["jobs"] for d in scored)
        avg = weighted_sum / weighted_count if weighted_count else 0
        print(f"Job-weighted average AI exposure: {avg:.2f} / 10")

    # Wages in high-exposure jobs (7+)
    high_exp = [d for d in data if d["exposure"] is not None
                and d["exposure"] >= 7 and d["jobs"] and d["pay"]]
    if high_exp:
        total_wages = sum(d["jobs"] * d["pay"] for d in high_exp)
        print(f"Total annual wages in high-exposure jobs (7+): "
              f"¥{total_wages / 1e12:.1f}兆 (trillion yen)")


if __name__ == "__main__":
    main()
