"""
Batch-translate description and exposure rationale for Japan occupations.

Translates:
  - description_ja (Japanese) → description_en (English)
  - exposure_rationale (English) → exposure_rationale_ja (Japanese)

Results are cached to translations_jp.json so the script can be resumed.

Usage:
    uv run python translate_jp.py
    uv run python translate_jp.py --model google/gemini-3-flash-preview
    uv run python translate_jp.py --start 0 --end 20   # test first 20
    uv run python translate_jp.py --force               # re-translate all
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
OUTPUT_FILE   = "translations_jp.json"
API_URL       = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """\
You are a professional Japanese↔English translator specializing in labor \
market and occupation descriptions.

You will be given a JSON object with one or both of these fields:
- "ja": a Japanese text to translate into natural, concise English
- "en": an English text to translate into natural, concise Japanese

Respond with ONLY a JSON object containing the translations:
{
  "en": "<English translation of the 'ja' field, or null if 'ja' was absent>",
  "ja": "<Japanese translation of the 'en' field, or null if 'en' was absent>"
}

Guidelines:
- Keep translations concise — roughly the same length as the source.
- Use natural phrasing, not word-for-word translation.
- For occupation descriptions, use present tense ("performs", "manages").
- Do not add information not present in the source text.
- Respond with ONLY the JSON object, no other text.\
"""


def translate(client: httpx.Client, ja_text: str | None, en_text: str | None,
              model: str) -> dict:
    """Translate ja→en and/or en→ja in a single API call."""
    payload = {}
    if ja_text:
        payload["ja"] = ja_text
    if en_text:
        payload["en"] = en_text
    if not payload:
        return {"en": None, "ja": None}

    wait = 15
    for attempt in range(6):
        response = client.post(
            API_URL,
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.1,
            },
            timeout=60,
        )
        if response.status_code == 429:
            print(f"(429 — waiting {wait}s)", end=" ", flush=True)
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
    parser = argparse.ArgumentParser(description="Batch-translate Japan occupation texts")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end",   type=int, default=None)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--force", action="store_true",
                        help="Re-translate even if already cached")
    args = parser.parse_args()

    # Load the built site data (contains description_ja and exposure_rationale)
    with open("site/data_jp.json", encoding="utf-8") as f:
        data = json.load(f)

    subset = data[args.start:args.end]

    # Load existing translations cache
    cache: dict[str, dict] = {}
    if os.path.exists(OUTPUT_FILE) and not args.force:
        with open(OUTPUT_FILE, encoding="utf-8") as f:
            for entry in json.load(f):
                cache[entry["slug"]] = entry

    print(f"Translating {len(subset)} occupations with {args.model}")
    print(f"Already cached: {len(cache)}")

    errors = []
    client = httpx.Client()

    for i, occ in enumerate(subset):
        slug = occ["slug"]

        if slug in cache:
            continue

        desc_ja   = occ.get("description_ja") or ""
        rationale = occ.get("exposure_rationale") or ""

        if not desc_ja and not rationale:
            cache[slug] = {
                "slug": slug,
                "description_en": "",
                "exposure_rationale_ja": "",
            }
            continue

        print(f"  [{i+1}/{len(subset)}] {occ['title']} …", end=" ", flush=True)

        try:
            result = translate(client, ja_text=desc_ja, en_text=rationale,
                               model=args.model)
            cache[slug] = {
                "slug":                  slug,
                "description_en":        result.get("en") or "",
                "exposure_rationale_ja": result.get("ja") or "",
            }
            desc_preview = (cache[slug]["description_en"] or "")[:60]
            print(f"OK  {desc_preview}…")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(slug)

        # Incremental checkpoint
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(list(cache.values()), f, ensure_ascii=False, indent=2)

        if i < len(subset) - 1:
            time.sleep(args.delay)

    client.close()

    print(f"\nDone. Translated {len(cache)} occupations, {len(errors)} errors.")
    if errors:
        print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
