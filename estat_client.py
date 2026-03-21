"""
e-Stat API client for Japan job market data.

Fetches two datasets from the Japanese government statistics portal
(https://www.e-stat.go.jp/api/) and saves them locally for use by
make_csv_jp.py.

Datasets downloaded:
  1. 賃金構造基本統計調査 (Basic Survey on Wage Structure) — ID 0003426315
     → 所定内給与額 × 12 (scheduled annual wage in JPY) by occupation (145 codes)
     → Saved to: estat_wages.json

  2. 労働力調査 従業上の地位，職業別就業者数 — ID 0003022759
     → Employment count by occupation (37 JSOC groups, monthly, unit=万人)
     → Saved to: estat_employment.json

Setup:
  1. Register for a free e-Stat API key at https://api.e-stat.go.jp/
  2. Add to your .env file:
       ESTAT_API_KEY=your_key_here

Usage:
    uv run python estat_client.py                  # fetch both datasets
    uv run python estat_client.py --wages-only
    uv run python estat_client.py --employment-only
    uv run python estat_client.py --force          # re-fetch even if cached
"""

import argparse
import io
import json
import os
import sys

import httpx
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

load_dotenv()

API_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"

# ── Dataset IDs ──────────────────────────────────────────────────────────────
# 賃金構造基本統計調査 一般_職種（小分類）DB 2023
# → tab=10 (所定内給与額, scheduled wage in 千円), cat03=occupation (145 codes)
WAGE_STATS_DATA_ID = "0003426315"

# 労働力調査 従業上の地位，職業別就業者数 (monthly)
# → cat01=occupation (37 JSOC group codes), unit=万人
EMPLOYMENT_STATS_DATA_ID = "0003022759"

WAGES_FILE      = "estat_wages.json"
EMPLOYMENT_FILE = "estat_employment.json"


# ── API fetch helpers ─────────────────────────────────────────────────────────

def fetch_wage_data(client: httpx.Client, app_id: str) -> dict:
    """Fetch wage data filtered to: tab=10 (所定内給与額), cat01=01 (all company
    sizes), cat02=01 (all genders), time=2023000000.  Returns one record per
    occupation code (cat03, 145 codes), value in 千円/month."""
    params = {
        "appId":        app_id,
        "statsDataId":  WAGE_STATS_DATA_ID,
        "metaGetFlg":   "Y",
        "cntGetFlg":    "N",
        "cdTab":        "42",           # 所定内給与額 (codes 33-45 = 2022-2023 data)
        "cdCat01":      "01",           # 企業規模計（10人以上）
        "cdCat02":      "01",           # 男女計
        "cdTime":       "2023000000",   # 2023年
    }
    resp = client.get(f"{API_BASE}/getStatsData", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def fetch_employment_data(client: httpx.Client, app_id: str) -> dict:
    """Fetch employment data filtered to totals (cat02=0, cat03=00, cat04=00).
    Returns all occupation codes (cat01, 37 codes) across all available months.
    We pick the latest month during parsing."""
    params = {
        "appId":        app_id,
        "statsDataId":  EMPLOYMENT_STATS_DATA_ID,
        "metaGetFlg":   "Y",
        "cntGetFlg":    "N",
        "cdCat02":      "0",    # 従業上の地位=総数
        "cdCat03":      "00",   # =総数
        "cdCat04":      "00",   # 年齢=15歳以上
    }
    resp = client.get(f"{API_BASE}/getStatsData", params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


# ── Response parsers ──────────────────────────────────────────────────────────

def parse_wage_response(raw: dict) -> list[dict]:
    """
    Extract occupation → annual wage from the wage survey response.

    The API call was filtered to tab=10 (所定内給与額) in 千円/month,
    so each value_num × 1000 × 12 gives annual JPY.

    Returns list of:
        { "occupation_code": str, "occupation_name": str, "median_pay_jpy": int }
    """
    try:
        stats      = raw["GET_STATS_DATA"]["STATISTICAL_DATA"]
        class_objs = stats["CLASS_INF"]["CLASS_OBJ"]
        data_vals  = stats["DATA_INF"]["VALUE"]
    except (KeyError, TypeError) as e:
        print(f"  Could not parse wage response structure: {e}")
        return []

    if isinstance(class_objs, dict):
        class_objs = [class_objs]

    # Build occupation code → name lookup from cat03 dimension
    occ_map: dict[str, str] = {}
    for obj in class_objs:
        if obj.get("@id") == "cat03":
            classes = obj.get("CLASS", [])
            if isinstance(classes, dict):
                classes = [classes]
            occ_map = {c["@code"]: c.get("@name", "") for c in classes}
            break

    if isinstance(data_vals, dict):
        data_vals = [data_vals]

    results: list[dict] = []
    for val in data_vals:
        if not isinstance(val, dict):
            continue
        raw_v = val.get("$", "").replace(",", "").strip()
        if not raw_v or raw_v in ("-", "…", "x", "X", "**", "***"):
            continue
        try:
            v = float(raw_v)
        except ValueError:
            continue

        occ_code = val.get("@cat03", "")
        if not occ_code:
            continue
        occ_name = occ_map.get(occ_code, occ_code)

        # 所定内給与額 is monthly in 千円 → annual JPY
        annual_jpy = int(v * 1000 * 12)
        results.append({
            "occupation_code": occ_code,
            "occupation_name": occ_name,
            "median_pay_jpy":  annual_jpy,
        })

    return results


def parse_employment_response(raw: dict) -> list[dict]:
    """
    Extract occupation → employment count from the Labour Force Survey response.

    The API call was filtered to totals (cat02=0, cat03=00, cat04=00).
    We pick the latest available time period for each occupation code.
    Unit is 万人 → multiply × 10000 for persons.

    Occupation code 000 (全職業=grand total) is excluded.

    Returns list of:
        { "occupation_code": str, "occupation_name": str, "employment": int }
    """
    try:
        stats      = raw["GET_STATS_DATA"]["STATISTICAL_DATA"]
        class_objs = stats["CLASS_INF"]["CLASS_OBJ"]
        data_vals  = stats["DATA_INF"]["VALUE"]
    except (KeyError, TypeError) as e:
        print(f"  Could not parse employment response structure: {e}")
        return []

    if isinstance(class_objs, dict):
        class_objs = [class_objs]

    occ_map:    dict[str, str] = {}
    time_codes: list[str]      = []

    for obj in class_objs:
        oid     = obj.get("@id", "")
        classes = obj.get("CLASS", [])
        if isinstance(classes, dict):
            classes = [classes]
        if oid == "cat01":
            occ_map = {c["@code"]: c.get("@name", "") for c in classes}
        elif oid == "time":
            time_codes = [c["@code"] for c in classes]

    # Latest time = lexicographically largest time code
    latest_time = max(time_codes) if time_codes else None
    if latest_time:
        print(f"  Employment: using latest time period {latest_time}")

    if isinstance(data_vals, dict):
        data_vals = [data_vals]

    # Accumulate per occupation, keeping only the latest time
    best: dict[str, dict] = {}
    for val in data_vals:
        if not isinstance(val, dict):
            continue

        t = val.get("@time", "")
        if latest_time and t != latest_time:
            continue

        raw_v = val.get("$", "").replace(",", "").strip()
        if not raw_v or raw_v in ("-", "…", "x", "X", "**", "***"):
            continue
        try:
            v = float(raw_v)
        except ValueError:
            continue

        occ_code = val.get("@cat01", "")
        if not occ_code or occ_code == "000":   # skip grand total
            continue

        occ_name   = occ_map.get(occ_code, occ_code)
        employment = int(v * 10000)              # 万人 → persons

        best[occ_code] = {
            "occupation_code": occ_code,
            "occupation_name": occ_name,
            "employment":      employment,
        }

    return list(best.values())


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch e-Stat data")
    parser.add_argument("--wages-only",      action="store_true")
    parser.add_argument("--employment-only", action="store_true")
    parser.add_argument("--force",           action="store_true",
                        help="Re-fetch even if cached files exist")
    args = parser.parse_args()

    app_id = os.environ.get("ESTAT_API_KEY", "")
    if not app_id:
        print("ERROR: ESTAT_API_KEY not set in .env")
        return

    do_wages      = not args.employment_only
    do_employment = not args.wages_only

    client = httpx.Client()

    # ── Wages ──────────────────────────────────────────────────────────────
    if do_wages:
        if not args.force and os.path.exists(WAGES_FILE):
            print(f"Wages already cached in {WAGES_FILE}. Use --force to re-fetch.")
        else:
            print(f"Fetching wage data (statsDataId={WAGE_STATS_DATA_ID}) …")
            try:
                raw = fetch_wage_data(client, app_id)
                with open("estat_wages_raw.json", "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)

                wages = parse_wage_response(raw)
                with open(WAGES_FILE, "w", encoding="utf-8") as f:
                    json.dump(wages, f, ensure_ascii=False, indent=2)

                print(f"  Saved {len(wages)} occupation wage records to {WAGES_FILE}")
                for w in wages[:5]:
                    print(f"    {w['occupation_code']} {w['occupation_name']}: "
                          f"¥{w['median_pay_jpy']:,}")
                if not wages:
                    print("  ⚠  No records parsed — check estat_wages_raw.json")

            except Exception as e:
                print(f"  ERROR fetching wages: {e}")

    # ── Employment ─────────────────────────────────────────────────────────
    if do_employment:
        if not args.force and os.path.exists(EMPLOYMENT_FILE):
            print(f"Employment already cached in {EMPLOYMENT_FILE}. Use --force to re-fetch.")
        else:
            print(f"Fetching employment data (statsDataId={EMPLOYMENT_STATS_DATA_ID}) …")
            try:
                raw = fetch_employment_data(client, app_id)
                with open("estat_employment_raw.json", "w", encoding="utf-8") as f:
                    json.dump(raw, f, ensure_ascii=False, indent=2)

                employment = parse_employment_response(raw)
                with open(EMPLOYMENT_FILE, "w", encoding="utf-8") as f:
                    json.dump(employment, f, ensure_ascii=False, indent=2)

                print(f"  Saved {len(employment)} occupation employment records to {EMPLOYMENT_FILE}")
                total = sum(e["employment"] for e in employment)
                print(f"  Total employment across all groups: {total:,}")
                for e in employment[:5]:
                    print(f"    {e['occupation_code']} {e['occupation_name']}: "
                          f"{e['employment']:,} workers")
                if not employment:
                    print("  ⚠  No records parsed — check estat_employment_raw.json")

            except Exception as e:
                print(f"  ERROR fetching employment: {e}")

    client.close()
    print("\nDone. Run make_csv_jp.py next.")


if __name__ == "__main__":
    main()
