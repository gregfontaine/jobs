"""
Re-categorize occupations_jp.json using the correct code→category mapping
from all_codes_sorted.json (collected in category order from Jobtag).
"""
import io, sys, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def code_to_category(code: str) -> tuple[str, str]:
    try:
        prefix = int(code.split("-")[0])
    except:
        return None, None
    if prefix <= 3:   return "Management", "管理的職業"
    elif prefix <= 32: return "Professional & Technical", "専門的・技術的職業"
    elif prefix <= 43: return "Clerical & Administrative", "事務的職業"
    elif prefix <= 48: return "Sales", "販売の職業"
    elif prefix <= 58: return "Service", "サービス職業"
    elif prefix <= 63: return "Security", "保安職業"
    elif prefix <= 66: return "Agriculture, Forestry & Fishing", "農林漁業"
    elif prefix <= 81: return "Production & Manufacturing", "生産工程の職業"
    elif prefix <= 89: return "Transportation & Machine Operation", "輸送・機械運転の職業"
    elif prefix <= 94: return "Construction & Mining", "建設・採掘の職業"
    else:              return "Logistics & Cleaning", "運搬・清掃・包装等の職業"

# Load code lookup from the full sorted scrape
with open("all_codes_sorted.json", encoding="utf-8") as f:
    sorted_rows = json.load(f)

code_by_id = {r["id"]: r["code"] for r in sorted_rows}
print(f"Codes available for {len(code_by_id)} occupations")

# Load and fix occupations_jp.json
with open("occupations_jp.json", encoding="utf-8") as f:
    occupations = json.load(f)

fixed = unchanged = no_code = 0
for occ in occupations:
    oid = occ["jobtag_id"]
    code = code_by_id.get(oid)
    if not code:
        no_code += 1
        continue
    cat_en, cat_ja = code_to_category(code)
    if cat_en is None:
        no_code += 1
        continue
    if cat_en != occ["category"]:
        fixed += 1
    else:
        unchanged += 1
    occ["category"] = cat_en
    occ["category_ja"] = cat_ja

print(f"Fixed: {fixed}, Unchanged: {unchanged}, No code: {no_code}")

# Sort by category then title
occupations.sort(key=lambda o: (o["category"], o["title"]))

with open("occupations_jp.json", "w", encoding="utf-8") as f:
    json.dump(occupations, f, ensure_ascii=False, indent=2)

# Summary
by_cat = {}
for o in occupations:
    by_cat[o["category"]] = by_cat.get(o["category"], 0) + 1
print("\nBreakdown by category:")
for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
    print(f"  {count:3d}  {cat}")
