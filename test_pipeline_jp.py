"""
Acceptance tests for the Japan occupation data pipeline.

Tests ~20 occupations across salary (pay), workers (jobs), education, and AI exposure.
Run with:  uv run python test_pipeline_jp.py
"""

import json
import sys
import io

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def load_data(path="site/data_jp.json"):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return {o["title"]: o for o in rows}


def check(data, title, *, pay_min=None, pay_max=None,
          jobs_min=None, jobs_max=None, jobs_exact=None,
          education=None, ai_min=None, ai_max=None, ai_exact=None):
    occ = data.get(title)
    failures = []
    if occ is None:
        return [f"MISSING occupation: {title}"]

    pay  = occ.get("pay")
    jobs = occ.get("jobs")
    edu  = occ.get("education")
    ai   = occ.get("exposure")

    if pay_min is not None and (pay is None or pay < pay_min):
        failures.append(f"pay {pay:,} < expected min {pay_min:,}")
    if pay_max is not None and (pay is None or pay > pay_max):
        failures.append(f"pay {pay:,} > expected max {pay_max:,}")
    if jobs_exact is not None and jobs != jobs_exact:
        failures.append(f"jobs {jobs} != expected {jobs_exact}")
    if jobs_min is not None and (jobs is None or jobs < jobs_min):
        failures.append(f"jobs {jobs:,} < expected min {jobs_min:,}")
    if jobs_max is not None and (jobs is None or jobs > jobs_max):
        failures.append(f"jobs {jobs:,} > expected max {jobs_max:,}")
    if education is not None and edu != education:
        failures.append(f"education '{edu}' != expected '{education}'")
    if ai_exact is not None and ai != ai_exact:
        failures.append(f"AI exposure {ai} != expected {ai_exact}")
    if ai_min is not None and (ai is None or ai < ai_min):
        failures.append(f"AI exposure {ai} < expected min {ai_min}")
    if ai_max is not None and (ai is None or ai > ai_max):
        failures.append(f"AI exposure {ai} > expected max {ai_max}")

    return failures


def run():
    data = load_data()
    results = []

    # ── Manual-override occupations (exact jobs expected) ────────────────────
    results.append(("客室乗務員",      check(data, "客室乗務員",
        jobs_min=50_000, jobs_max=300_000,
        pay_min=3_500_000, pay_max=8_000_000,
        education="大学卒",             # Jobtag occ-205: 83.8% 大卒 (modal)
        ai_exact=4)))

    results.append(("税務事務官",      check(data, "税務事務官",
        jobs_min=50_000, jobs_max=600_000,
        pay_min=4_000_000, pay_max=7_000_000,
        ai_min=4, ai_max=8)))

    # ── Medical / health ─────────────────────────────────────────────────────
    results.append(("内科医",          check(data, "内科医",
        pay_min=10_000_000,             # doctors in Japan earn >10M
        jobs_min=10_000, jobs_max=200_000,
        education="大学卒",             # Jobtag: 77.8% 大卒 (6-year 医学部 = undergrad)
        ai_min=4, ai_max=8)))

    results.append(("歯科医師",        check(data, "歯科医師",
        pay_min=8_000_000,              # dentists earn >8M
        jobs_min=50_000, jobs_max=200_000,
        education="大学卒",             # Jobtag: 71.2% 大卒 (6-year 歯学部 = undergrad)
        ai_max=6)))

    results.append(("看護師",          check(data, "看護師",
        pay_min=3_500_000, pay_max=7_000_000,
        jobs_min=300_000,               # ~1.2M nurses; wage-census category subset
        ai_exact=4)))

    results.append(("診療放射線技師",   check(data, "診療放射線技師",
        pay_min=4_000_000, pay_max=8_000_000,
        jobs_min=20_000, jobs_max=200_000,
        ai_min=4, ai_max=8)))

    # ── Tech / IT ────────────────────────────────────────────────────────────
    results.append(("プログラマー",    check(data, "プログラマー",
        pay_min=4_000_000, pay_max=9_000_000,
        ai_exact=9)))

    results.append(("データサイエンティスト", check(data, "データサイエンティスト",
        pay_min=3_500_000, pay_max=12_000_000,  # e-Stat median for 他に分類されない技術者
        ai_exact=9)))

    results.append(("システムエンジニア（Webサービス開発）", check(data, "システムエンジニア（Webサービス開発）",
        pay_min=4_000_000, pay_max=9_000_000,
        ai_min=8)))

    results.append(("AIエンジニア",    check(data, "AIエンジニア",
        pay_min=3_500_000,  # e-Stat median for その他の情報処理・通信技術者
        ai_min=8)))

    # ── Legal / finance ──────────────────────────────────────────────────────
    results.append(("弁護士",          check(data, "弁護士",
        pay_min=7_000_000,
        jobs_min=5_000, jobs_max=200_000,
        education="大学卒",             # Jobtag: 83.3% 大卒 (法科大学院 is post-grad but modal is 大卒)
        ai_min=5, ai_max=9)))

    results.append(("税理士",          check(data, "税理士",
        pay_min=5_000_000,  # e-Stat median for 公認会計士，税理士
        jobs_min=20_000, jobs_max=200_000,
        ai_min=6)))

    # ── Education ────────────────────────────────────────────────────────────
    results.append(("小学校教員",      check(data, "小学校教員",
        pay_min=5_000_000, pay_max=9_000_000,
        jobs_min=100_000,
        ai_min=4, ai_max=8)))

    results.append(("保育士",          check(data, "保育士",
        pay_min=3_000_000, pay_max=6_000_000,
        jobs_min=200_000,               # ~700K nursery teachers in Japan
        ai_max=5)))

    # ── Trades / manual ──────────────────────────────────────────────────────
    results.append(("トラックドライバー", check(data, "トラックドライバー",
        pay_min=3_500_000, pay_max=7_000_000,
        jobs_min=50_000,
        ai_exact=3)))

    results.append(("自動車整備士",    check(data, "自動車整備士",
        pay_min=3_500_000, pay_max=7_000_000,
        jobs_min=50_000,
        ai_exact=3)))

    # ── Creative / service ───────────────────────────────────────────────────
    results.append(("翻訳者",          check(data, "翻訳者",
        jobs_min=5_000, jobs_max=100_000,
        ai_exact=9)))

    results.append(("グラフィックデザイナー", check(data, "グラフィックデザイナー",
        pay_min=3_500_000, pay_max=8_000_000,
        ai_exact=9)))

    results.append(("美容師",          check(data, "美容師",
        pay_min=2_500_000, pay_max=6_000_000,
        jobs_min=50_000,
        ai_max=4)))

    results.append(("秘書",            check(data, "秘書",
        pay_min=3_500_000, pay_max=8_000_000,
        jobs_min=50_000, jobs_max=500_000,   # after division fix
        ai_min=5)))

    # ── Additional workers-accuracy tests ────────────────────────────────────
    results.append(("銀行等窓口事務",  check(data, "銀行等窓口事務",
        jobs_min=50_000, jobs_max=600_000,
        pay_min=4_000_000, pay_max=7_000_000,
        ai_min=5, ai_max=9)))

    results.append(("検疫官（看護師）", check(data, "検疫官（看護師）",
        jobs_min=100, jobs_max=800_000,
        ai_min=3, ai_max=7)))

    results.append(("一般事務",        check(data, "一般事務",
        jobs_min=500_000, jobs_max=5_000_000,  # wage-census measure of 総合事務員
        pay_min=3_000_000, pay_max=7_000_000,
        ai_min=6)))

    # ── Print results ────────────────────────────────────────────────────────
    passed = 0
    failed = 0
    for title, failures in results:
        if failures:
            print(f"  FAIL  {title}")
            for f in failures:
                print(f"         → {f}")
            failed += 1
        else:
            occ = data[title]
            print(f"  PASS  {title}  "
                  f"pay=¥{occ['pay']:,}  "
                  f"jobs={occ.get('jobs','?'):,}  "
                  f"edu={occ.get('education','?')}  "
                  f"ai={occ.get('exposure','?')}")
            passed += 1

    print()
    print(f"{'='*60}")
    print(f"  {passed}/{passed+failed} tests passed")
    if failed:
        print(f"  {failed} FAILED")
        sys.exit(1)
    else:
        print("  All tests passed.")


if __name__ == "__main__":
    run()
