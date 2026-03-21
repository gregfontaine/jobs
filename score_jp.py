"""
Score each Japan occupation's AI exposure using an LLM via OpenRouter.

Reads Markdown descriptions from pages_jp/, sends each to an LLM with a
Japan-calibrated scoring rubric, and caches results to scores_jp.json.

The LLM receives job descriptions in Japanese (as scraped from Jobtag) and
is instructed to respond in English so the rationale is readable alongside
the rest of the English UI.

Usage:
    uv run python score_jp.py
    uv run python score_jp.py --model google/gemini-3-flash-preview
    uv run python score_jp.py --start 0 --end 20   # test first 20
    uv run python score_jp.py --force               # re-score all
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
OUTPUT_FILE   = "scores_jp.json"
API_URL       = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """\
You are an expert analyst evaluating how exposed different occupations are to \
AI, specifically within the context of the Japanese labor market.

You will be given a description of a Japanese occupation, which may be written \
in Japanese. Read and understand it fully, then rate the occupation's overall \
**AI Exposure** on a scale from 0 to 10.

AI Exposure measures: how much will AI reshape this occupation in Japan over \
the coming decade? Consider both direct effects (AI automating tasks currently \
done by humans) and indirect effects (AI making each worker so productive that \
fewer workers are needed).

Consider Japan-specific factors where relevant:
- Japan already has very high industrial robot penetration in manufacturing, \
  meaning some physical automation has already occurred. Score these based on \
  remaining human cognitive/supervisory tasks.
- Japan's large white-collar workforce (事務職, 管理職) is highly susceptible \
  to AI-driven productivity gains.
- Japan's aging population and labor shortage may accelerate AI adoption even \
  in sectors that might otherwise resist it.
- Occupations requiring human-to-human care (介護, 看護, 保育) have cultural \
  and regulatory barriers to AI replacement beyond technical limitations.

A key signal is whether the job's work product is fundamentally digital. Jobs \
done entirely on a computer — writing, coding, analyzing, designing, \
communicating — have inherently high exposure (7+). Jobs requiring physical \
presence, manual skill, or real-time human interaction in unpredictable \
physical environments have natural barriers.

Use these anchors to calibrate your score:

- **0–1: Minimal exposure.** Almost entirely physical, hands-on, or requires \
real-time human presence in unpredictable environments. AI has essentially no \
impact on daily work. Examples: construction laborer (土木作業員), \
fisherman (漁師), roofer (屋根職人).

- **2–3: Low exposure.** Mostly physical or interpersonal work. AI might help \
with peripheral tasks (scheduling, record-keeping) but does not touch the core \
job. Examples: electrician (電気工事士), plumber (配管工), \
nursing aide (介護福祉士), firefighter (消防士).

- **4–5: Moderate exposure.** A mix of physical/interpersonal and knowledge \
work. AI can meaningfully assist with the information-processing parts, but a \
substantial share of the job still requires human presence. Examples: \
registered nurse (看護師), police officer (警察官), veterinarian (獣医師), \
chef (料理人).

- **6–7: High exposure.** Predominantly knowledge work with some need for \
human judgment, relationships, or physical presence. AI tools already make \
workers substantially more productive. Examples: teacher (教師), \
manager (管理職), accountant (公認会計士), journalist (記者), \
architect (建築士).

- **8–9: Very high exposure.** Almost entirely done on a computer. All core \
tasks — writing, coding, analyzing, designing, communicating — are in domains \
where AI is rapidly improving. Major restructuring ahead. Examples: \
software developer (ソフトウェア開発者), translator (翻訳者), \
data analyst (データアナリスト), copywriter (コピーライター), \
paralegal (パラリーガル).

- **10: Maximum exposure.** Routine information processing, fully digital, no \
physical component. AI can already do most of it today. Examples: \
data entry clerk (データ入力オペレーター), medical transcriptionist.

Respond with ONLY a JSON object in this exact format, no other text:
{
  "exposure": <integer 0-10>,
  "rationale": "<2-3 sentences in English explaining the key factors>"
}\
"""


def score_occupation(client: httpx.Client, text: str, model: str) -> dict:
    wait = 15  # initial backoff on 429 (seconds)
    for attempt in range(6):
        response = client.post(
            API_URL,
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": text},
                ],
                "temperature": 0.2,
            },
            timeout=60,
        )
        if response.status_code == 429:
            print(f"(429 — waiting {wait}s)", end=" ", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 120)  # cap at 2 min
            continue
        response.raise_for_status()
        break
    else:
        response.raise_for_status()  # re-raise after max retries

    content = response.json()["choices"][0]["message"]["content"].strip()

    # Strip markdown code fences if present
    if content.startswith("```"):
        content = content.split("\n", 1)[1]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

    return json.loads(content)


def main():
    parser = argparse.ArgumentParser(description="Score Japan occupation AI exposure")
    parser.add_argument("--model",  default=DEFAULT_MODEL)
    parser.add_argument("--start",  type=int,   default=0)
    parser.add_argument("--end",    type=int,   default=None)
    parser.add_argument("--delay",  type=float, default=0.5)
    parser.add_argument("--force",  action="store_true",
                        help="Re-score even if already cached")
    parser.add_argument("--output", default=OUTPUT_FILE,
                        help="Output file path (default: scores_jp.json)")
    args = parser.parse_args()
    output_file = args.output

    with open("occupations_jp.json", encoding="utf-8") as f:
        occupations = json.load(f)

    subset = occupations[args.start:args.end]

    # Load existing scores
    scores: dict[str, dict] = {}
    if os.path.exists(output_file) and not args.force:
        with open(output_file, encoding="utf-8") as f:
            for entry in json.load(f):
                scores[entry["slug"]] = entry

    print(f"Scoring {len(subset)} occupations with {args.model}")
    print(f"Already cached: {len(scores)}")

    errors = []
    client = httpx.Client()

    for i, occ in enumerate(subset):
        slug = occ["slug"]

        if slug in scores:
            continue

        md_path = f"pages_jp/{slug}.md"
        if not os.path.exists(md_path):
            print(f"  [{i+1}] SKIP {slug} (no markdown)")
            continue

        with open(md_path, encoding="utf-8") as f:
            text = f.read()

        print(f"  [{i+1}/{len(subset)}] {occ['title']} …", end=" ", flush=True)

        try:
            result = score_occupation(client, text, args.model)
            scores[slug] = {
                "slug":     slug,
                "title":    occ["title"],
                "category": occ["category"],
                **result,
            }
            print(f"exposure={result['exposure']}")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(slug)

        # Incremental checkpoint after each occupation
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(list(scores.values()), f, ensure_ascii=False, indent=2)

        if i < len(subset) - 1:
            time.sleep(args.delay)

    client.close()

    print(f"\nDone. Scored {len(scores)} occupations, {len(errors)} errors.")
    if errors:
        print(f"Errors: {errors}")

    # Summary stats
    vals = [s for s in scores.values() if "exposure" in s]
    if vals:
        avg = sum(s["exposure"] for s in vals) / len(vals)
        by_score: dict[int, int] = {}
        for s in vals:
            bucket = s["exposure"]
            by_score[bucket] = by_score.get(bucket, 0) + 1
        print(f"\nAverage exposure across {len(vals)} occupations: {avg:.1f}")
        print("Distribution:")
        for k in sorted(by_score):
            print(f"  {k:2d}: {'█' * by_score[k]} ({by_score[k]})")


if __name__ == "__main__":
    main()
