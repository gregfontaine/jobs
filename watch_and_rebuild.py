"""
Wait for scores_jp.json to stop growing, then rebuild site/data_jp.json.
Polls every 30s; declares done after 3 consecutive stable reads (90s).
"""
import json
import os
import sys
import time

TARGET = 549  # number of HTML pages scraped

prev = 0
stable = 0

while True:
    time.sleep(30)
    try:
        scores = json.load(open("scores_jp.json", encoding="utf-8"))
        curr = len(scores)
    except Exception:
        curr = prev

    print(f"  {curr} scores", flush=True)

    if curr >= TARGET:
        print(f"All {curr} occupations scored. Rebuilding...")
        break

    if curr == prev:
        stable += 1
        if stable >= 3:
            print(f"Stable at {curr} for 90s — scoring done. Rebuilding...")
            break
    else:
        stable = 0

    prev = curr

ret = os.system(
    "/c/Users/grego/AppData/Local/Microsoft/WinGet/Links/uv.exe "
    "run python build_site_data_jp.py"
)
print(f"Build exit code: {ret}")
