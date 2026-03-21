"""
Parse a Jobtag occupation detail page into clean Markdown.

Jobtag is a JavaScript SPA (React/Vue) served by the MHLW. After Playwright
renders the page, the HTML contains a populated DOM that BeautifulSoup can
read. Because Jobtag's CSS class names are build-hash-suffixed and unstable,
this parser uses semantic heuristics rather than brittle class selectors:

  • Title  → the first <h1> on the page
  • Source → the canonical <link> or current URL
  • Sections → any <section>, <article>, or block-level element whose
    immediate heading contains a known Japanese section keyword
  • Wage table → a <table> or structured element containing 給与/賃金/収入
  • Education field → text near 必要な資格/学歴/資格

When called standalone it also prints a DOM diagnostic summary so you can
verify the selectors are working after the first scrape batch.

Usage (standalone):
    uv run python parse_detail_jp.py html_jp/occ-12345.html
"""

import io
import re
import sys
from bs4 import BeautifulSoup, Tag

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


# ── Keyword sets ────────────────────────────────────────────────────────────

SECTION_KEYWORDS = [
    "仕事の内容",     # Job duties
    "仕事内容",
    "働く環境",       # Work environment
    "労働環境",
    "必要な資格",     # Required qualifications
    "資格・免許",
    "就職先",         # Employment sectors
    "雇用形態",       # Employment type
    "収入・給与",     # Income / wages
    "給与",
    "賃金",
    "年収",
    "労働条件",       # Working conditions
    "職業紹介",       # Occupation introduction
    "キャリア",       # Career path
    "向いている人",   # Suitable person profile
    "求人",           # Job openings
    "就業状況",       # Employment status
    "関連職業",       # Related occupations
]

WAGE_KEYWORDS = ["給与", "賃金", "収入", "年収", "月収", "時給", "所得"]
EDU_KEYWORDS  = ["学歴", "資格", "免許", "要件", "必要", "取得"]


# ── Utility ─────────────────────────────────────────────────────────────────

def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def is_section_heading(text: str) -> bool:
    return any(kw in text for kw in SECTION_KEYWORDS)


# ── Main parser ──────────────────────────────────────────────────────────────

def parse_jobtag_page(html_path: str, source_url: str = "") -> str:
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    md = []

    # ── Title ────────────────────────────────────────────────────────────
    # Jobtag pages have an empty <h1>; the occupation title appears in the
    # breadcrumb (the last item after "TOP") or in an h3 inside the page header.
    title = ""
    breadcrumb = soup.find(class_="breadcrumb")
    if breadcrumb:
        items = [clean(li.get_text()) for li in breadcrumb.find_all("li")]
        # Last non-empty item after "TOP" is the occupation name
        items = [t for t in items if t and t != "TOP"]
        if items:
            title = items[-1]
    if not title:
        # Fallback: first h3 that looks like an occupation name (not a section keyword)
        for h in soup.find_all("h3"):
            t = clean(h.get_text())
            if t and not is_section_heading(t) and len(t) < 40:
                title = t
                break
    if not title:
        title = "Unknown Occupation"

    md.append(f"# {title}")
    md.append("")

    # ── Source ───────────────────────────────────────────────────────────
    canonical = soup.find("link", rel="canonical")
    url = canonical["href"] if canonical and canonical.get("href") else source_url
    if url:
        md.append(f"**Source:** {url}")
        md.append("")

    # ── Section labels (card-step headings) ──────────────────────────────
    # Jobtag uses tab-style navigation: section titles live in .card-step__step
    # divs and content lives in separate .card-description divs.  Pair them in
    # document order so each description gets a heading.
    section_labels: list[str] = []
    for el in soup.find_all(class_=lambda c: c and "card-step__step" in c):
        t = clean(el.get_text())
        if t:
            section_labels.append(t)

    # ── Content blocks ───────────────────────────────────────────────────
    # All substantive text lives in div.card-description elements.
    # Filter out very short blocks that are just UI links/noise (< 80 chars).
    content_blocks: list[str] = []
    for div in soup.find_all("div", class_="card-description"):
        for tag in div.find_all(["script", "style", "nav", "noscript", "svg", "iframe", "a"]):
            tag.decompose()
        text = clean(div.get_text(separator="\n"))
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if len(text) >= 80:
            content_blocks.append(text)

    if content_blocks:
        for i, block in enumerate(content_blocks):
            label = section_labels[i] if i < len(section_labels) else f"セクション {i+1}"
            md.append(f"## {label}")
            md.append("")
            md.append(block)
            md.append("")
    else:
        # Fallback: dump all text from <main> (strips nav/header/footer)
        main = soup.find("main") or soup.body
        if main:
            for tag in main.find_all(["script", "style", "nav", "footer",
                                      "noscript", "svg", "iframe"]):
                tag.decompose()
            md.append("## 職業情報")
            md.append("")
            md.append(clean(main.get_text(separator="\n")))

    # ── Deduplicate consecutive blank lines ───────────────────────────────
    result = []
    prev_blank = False
    for line in md:
        is_blank = (line.strip() == "")
        if is_blank and prev_blank:
            continue
        result.append(line)
        prev_blank = is_blank

    return "\n".join(result)


# ── DOM diagnostic (helps verify selectors on first run) ────────────────────

def dom_diagnostic(html_path: str):
    """Print a structural summary of a Jobtag page to aid selector development."""
    with open(html_path, encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    print("\n=== DOM DIAGNOSTIC ===")
    print(f"File: {html_path}")

    h1 = soup.find("h1")
    print(f"h1: {clean(h1.get_text()) if h1 else 'NOT FOUND'}")

    for level in ("h2", "h3", "h4"):
        tags = soup.find_all(level)
        if tags:
            print(f"\n{level} headings ({len(tags)}):")
            for t in tags[:15]:
                print(f"  [{t.get('class', '')}] {clean(t.get_text())}")

    print("\nTop-level structural elements:")
    for tag in ["main", "article", "section"]:
        elems = soup.find_all(tag)
        print(f"  <{tag}>: {len(elems)} found")

    wage_elems = soup.find_all(
        string=lambda t: t and any(kw in t for kw in WAGE_KEYWORDS)
    )
    print(f"\nElements containing wage keywords: {len(wage_elems)}")
    for w in wage_elems[:5]:
        parent = w.parent
        print(f"  <{parent.name} class='{parent.get('class', '')}'>: {clean(str(w))[:80]}")

    print("=== END DIAGNOSTIC ===\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run python parse_detail_jp.py <html_path> [source_url]")
        sys.exit(1)

    html_path  = sys.argv[1]
    source_url = sys.argv[2] if len(sys.argv) > 2 else ""

    # Always run diagnostic on direct invocation to aid development
    dom_diagnostic(html_path)

    result = parse_jobtag_page(html_path, source_url)

    out_path = html_path.replace(".html", ".md").replace("html_jp/", "pages_jp/")
    import os
    os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)

    print(f"Written to {out_path}")
    print()
    print(result[:3000])
    if len(result) > 3000:
        print(f"\n… ({len(result) - 3000} more chars)")
