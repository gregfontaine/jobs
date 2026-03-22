"""
Batch-translate Japanese occupation titles to English.

Sends batches of ~50 titles per API call for efficiency.
Results are merged into translations_jp.json (adds/updates title_en field).

Usage:
    uv run python translate_titles_jp.py
    uv run python translate_titles_jp.py --batch-size 30
    uv run python translate_titles_jp.py --force   # re-translate all
"""

import argparse
import io
import json
import os
import sys
import time
import httpx
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

load_dotenv()

DEFAULT_MODEL = "google/gemini-3-flash-preview"
TRANSLATIONS_FILE = "translations_jp.json"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """\
You are a professional Japanese→English translator specializing in job titles \
and occupation names in the Japanese labor market.

You will be given a JSON object mapping slugs to Japanese occupation titles.
Translate each title to natural, concise English.

Rules:
- Use standard English occupation names (e.g. 内科医 → "Internal Medicine Doctor")
- Keep translations concise — just the job title, no explanations
- Preserve parenthetical qualifiers: e.g. システムエンジニア（Webサービス開発） → "Systems Engineer (Web Services)"
- For uniquely Japanese roles, use a descriptive English equivalent
- Do NOT add words like "Specialist" or "Professional" unless the Japanese title implies it

Respond with ONLY a JSON object mapping the same slugs to their English translations.
No other text, no markdown fences.\
"""


def translate_batch(client: httpx.Client, batch: dict[str, str], model: str) -> dict[str, str]:
    """Translate a batch of {slug: ja_title} → {slug: en_title}."""
    wait = 15
    for attempt in range(6):
        response = client.post(
            API_URL,
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(batch, ensure_ascii=False)},
                ],
                "temperature": 0.1,
            },
            timeout=120,
        )
        if response.status_code == 429:
            print(f"  (429 — waiting {wait}s)", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 120)
            continue
        response.raise_for_status()
        break
    else:
        response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    return json.loads(content)


def main():
    parser = argparse.ArgumentParser(description="Batch-translate JP occupation titles to English")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--force", action="store_true",
                        help="Re-translate even if title_en already cached")
    args = parser.parse_args()

    # Load occupation data
    with open("site/data_jp.json", encoding="utf-8") as f:
        data = json.load(f)

    # Load existing translations
    cache: dict[str, dict] = {}
    if os.path.exists(TRANSLATIONS_FILE):
        with open(TRANSLATIONS_FILE, encoding="utf-8") as f:
            for entry in json.load(f):
                cache[entry["slug"]] = entry

    # Find titles that need translation
    if args.force:
        need = [(d["slug"], d["title"]) for d in data]
    else:
        need = [(d["slug"], d["title"]) for d in data
                if not cache.get(d["slug"], {}).get("title_en")]

    print(f"Total occupations: {len(data)}")
    print(f"Already translated: {len(data) - len(need)}")
    print(f"Need translation: {len(need)}")

    if not need:
        print("All titles already translated.")
        return

    # Batch translate
    client = httpx.Client()
    translated = 0
    errors = []

    for batch_start in range(0, len(need), args.batch_size):
        batch_items = need[batch_start:batch_start + args.batch_size]
        batch_dict = {slug: title for slug, title in batch_items}
        batch_num = batch_start // args.batch_size + 1
        total_batches = (len(need) + args.batch_size - 1) // args.batch_size

        print(f"\nBatch {batch_num}/{total_batches} ({len(batch_items)} titles)...", flush=True)

        try:
            results = translate_batch(client, batch_dict, args.model)

            for slug, en_title in results.items():
                if slug not in cache:
                    cache[slug] = {"slug": slug, "description_en": "", "exposure_rationale_ja": ""}
                cache[slug]["title_en"] = en_title
                translated += 1

            # Checkpoint after each batch
            with open(TRANSLATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(list(cache.values()), f, ensure_ascii=False)

            # Show some examples from this batch
            examples = list(results.items())[:3]
            for slug, en in examples:
                ja = batch_dict.get(slug, "?")
                print(f"  {ja} → {en}")
            if len(results) > 3:
                print(f"  ... and {len(results) - 3} more")

            print(f"  Translated: {translated}/{len(need)}")

        except Exception as e:
            print(f"  ERROR: {e}")
            errors.append((batch_start, str(e)))

        if batch_start + args.batch_size < len(need):
            time.sleep(args.delay)

    # Final save
    with open(TRANSLATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(cache.values()), f, ensure_ascii=False)

    print(f"\nDone! Translated {translated} titles.")
    if errors:
        print(f"Errors in {len(errors)} batches:")
        for start, err in errors:
            print(f"  Batch starting at {start}: {err}")

    # Verify
    missing = [d["title"] for d in data if not cache.get(d["slug"], {}).get("title_en")]
    if missing:
        print(f"\n{len(missing)} titles still missing translation:")
        for t in missing[:10]:
            print(f"  {t}")
    else:
        print("All titles have English translations!")


if __name__ == "__main__":
    main()
