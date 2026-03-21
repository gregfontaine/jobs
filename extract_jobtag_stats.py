"""
Extract per-occupation wage and employment data embedded in scraped Jobtag HTML files.

Each detail page contains two hidden input fields:
  - recruitment_statistics_models: national wage (万円/month) + opening ratio
  - analyst_prefecture_models: one row per prefecture with WorkHumanNumber (employment)
    and WorkSalary (annual salary in 万円)

Salary source: WorkSalary from analyst_prefecture_models (actual census salary),
  weighted average across prefectures by WorkHumanNumber.
  NOT the Wage field in recruitment_statistics_models, which is the job-posting
  base/entry wage — systematically lower than true median salary.

Employment source: sum of WorkHumanNumber across all 47 prefectures = national
  total for the JSOC occupational sub-category this occupation belongs to.
  Multiple Jobtag occupations may share the same JSOC category, so this is a
  category-level figure, not strictly occupation-specific.

Output: jobtag_stats.json
  { "occ-505": { "wage_jpy": 4970000, "opening_ratio": 1.13, "workers": 291360 }, ... }
"""

import io
import json
import os
import sys

from bs4 import BeautifulSoup

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def parse_wage(wage_str: str) -> float | None:
    """Parse '20.6' or '19.9～24.7' → lower bound as float (万円/month)."""
    if not wage_str or wage_str in ("-", "…", "x"):
        return None
    try:
        return float(str(wage_str).split("～")[0].strip())
    except (ValueError, IndexError):
        return None


def extract_stats(html_path: str) -> dict | None:
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    rec_el = soup.find("input", id="recruitment_statistics_models")
    ana_el = soup.find("input", id="analyst_prefecture_models")

    if not rec_el:
        return None

    rec = json.loads(rec_el.get("value", "[]"))
    ana = json.loads(ana_el.get("value", "[]")) if ana_el else []

    # National figure: PrefectureId == null
    national = next((r for r in rec if r.get("PrefectureId") is None), None)
    if not national:
        return None

    try:
        opening_ratio = float(national.get("OpeningRatio", 0) or 0)
    except (ValueError, TypeError):
        opening_ratio = None

    # Salary: weighted average of WorkSalary (万円/year) across prefectures,
    # weighted by WorkHumanNumber.  WorkSalary is the census-surveyed actual
    # salary — much more accurate than the job-posting Wage field.
    total_workers = 0
    weighted_salary = 0.0
    workers = 0
    category_code = None
    seen = set()
    for e in ana:
        key = (e.get("Id"), e.get("PrefectureId"))
        if key in seen:
            continue
        seen.add(key)
        w = e.get("WorkHumanNumber") or 0
        s = e.get("WorkSalary")
        workers += w
        if s is not None:
            try:
                weighted_salary += w * float(s)
                total_workers += w
            except (ValueError, TypeError):
                pass
        if category_code is None:
            category_code = e.get("WageCensusOccupationCategoryCode")

    if total_workers > 0:
        wage_jpy = int(weighted_salary / total_workers * 10000)  # 万円/year → JPY
    else:
        # Fallback to job-posting monthly wage if no salary data
        wage_man = parse_wage(national.get("Wage", ""))
        if wage_man is None:
            return None
        wage_jpy = int(wage_man * 10000 * 12)

    return {
        "wage_jpy":      wage_jpy,
        "opening_ratio": opening_ratio,
        "workers":       workers,
        "category_code": category_code,
    }


def main():
    html_dir = "html_jp"
    out_file = "jobtag_stats.json"

    results = {}
    ok = skipped = 0

    for fname in sorted(os.listdir(html_dir)):
        if not fname.endswith(".html"):
            continue
        slug = fname.replace(".html", "")
        stats = extract_stats(os.path.join(html_dir, fname))
        if stats:
            results[slug] = stats
            ok += 1
        else:
            skipped += 1

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"Extracted: {ok} occupations, skipped: {skipped}")
    print(f"Saved to {out_file}")

    # Quick sanity check
    if results:
        wages = [v["wage_jpy"] for v in results.values()]
        ratios = [v["opening_ratio"] for v in results.values() if v["opening_ratio"]]
        workers = [v["workers"] for v in results.values()]
        print(f"\nWage range:   ¥{min(wages):,} – ¥{max(wages):,}  avg ¥{sum(wages)//len(wages):,}")
        if ratios:
            print(f"Opening ratio: {min(ratios):.2f} – {max(ratios):.2f}  avg {sum(ratios)/len(ratios):.2f}")
        print(f"Workers range: {min(workers):,} – {max(workers):,}")


if __name__ == "__main__":
    main()
