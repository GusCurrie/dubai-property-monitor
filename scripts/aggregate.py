#!/usr/bin/env python3
"""Aggregate DLD raw monthly pulls (data/sales_*.jsonl.gz, data/rents_*.jsonl.gz)
into a compact payload for the dashboard. Outputs docs/payload.b64.
Optionally merges data/history_agg.b64 (pre-2026 aggregates from the cleaned
research dataset) for months before live API coverage."""
import gzip, json, base64, glob, os, statistics, sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")
SQM_TO_SQFT = 10.7639
MICRO_SALES_DAYS = 92
MICRO_RENTS_DAYS = 46

# ---------- category mapping ----------
def sale_cat(r):
    pt = (r.get("PROP_TYPE_EN") or "").strip()
    sb = (r.get("PROP_SB_TYPE_EN") or "").strip()
    if pt == "Land":
        if sb in ("Commercial", "Shop", "General Use", "Commercial / Residential"): return "Land - Commercial"
        if sb in ("Industrial", "Labor Camp", "Warehouse", "Workshop"): return "Land - Industrial"
        if sb.startswith("Residential") or sb in ("Villa", "Government Housing"): return "Land - Residential"
        return "Land - Other"
    if sb in ("Flat",): return "Apartment"
    if sb == "Villa" or sb == "Townhouse": return "Villa/Townhouse"
    if sb in ("Hotel Apartment", "Hotel Rooms", "Hotel"): return "Hospitality"
    if sb == "Office": return "Office"
    if sb in ("Shop", "Show Rooms", "Show Room"): return "Retail"
    if sb in ("Warehouse", "Workshop"): return "Warehouse/Industrial"
    if pt == "Building": return "Building"
    if pt == "Unit" and sb == "Residential": return "Apartment"
    return "Other"

def rent_cat(r):
    pt = (r.get("PROP_TYPE_EN") or "").strip()
    sb = (r.get("PROP_SUB_TYPE_EN") or "").strip()
    us = (r.get("USAGE_EN") or "").strip()
    if pt == "Land":
        if us == "Commercial": return "Land - Commercial"
        if us == "Industrial": return "Land - Industrial"
        if us == "Residential": return "Land - Residential"
        return "Land - Other"
    if sb in ("Flat", "Studio", "Room", "Flat Hotel", "Penthouse", "Duplex"):
        return "Hospitality" if "Hotel" in sb else "Apartment"
    if sb in ("Villa", "Townhouse", "Arabic House"): return "Villa/Townhouse"
    if sb in ("Office", "Business Center", "Clinic"): return "Office"
    if sb in ("Shop", "Show Rooms", "Show Room", "Restaurant", "Supermarket", "Kiosk", "Cafeteria", "Atm", "Pharmacy"): return "Retail"
    if sb in ("Warehouse", "Workshop", "Store", "Factory", "Labor Camp", "Staff Accommodation"): return "Warehouse/Industrial"
    if pt == "Building" or sb == "Building": return "Building"
    if us == "Residential": return "Apartment" if pt == "Unit" else "Other"
    if us == "Commercial": return "Other"
    return "Other"

CATS = ["Apartment", "Villa/Townhouse", "Hospitality", "Office", "Retail",
        "Warehouse/Industrial", "Building", "Land - Residential", "Land - Commercial",
        "Land - Industrial", "Land - Other", "Other"]
CAT_IDX = {c: i for i, c in enumerate(CATS)}

def beds_code(rooms):
    if not rooms: return -1
    r = rooms.strip()
    if r == "Studio": return 0
    if r and r[0].isdigit() and "B/R" in r:
        n = int(r.split()[0]); return min(n, 7)
    if r == "PENTHOUSE": return 7
    return -1

def med(vals):
    return round(statistics.median(vals), 1) if vals else None

def q(vals, p):
    if not vals: return None
    vs = sorted(vals); k = (len(vs) - 1) * p
    f = int(k); c = min(f + 1, len(vs) - 1)
    return round(vs[f] + (vs[c] - vs[f]) * (k - f), 1)

def load(kind):
    for fp in sorted(glob.glob(os.path.join(DATA, f"{kind}_*.jsonl.gz"))):
        with gzip.open(fp, "rt") as f:
            for line in f:
                yield json.loads(line)

def norm_area(s):
    s = (s or "Unknown").strip() or "Unknown"
    return " ".join(w if (w.isupper() and len(w) <= 3) else w.title() for w in s.split())

def main():
    sales, rents = load("sales"), load("rents")
    n_sales = n_rents = 0
    areas, projects = {}, {}
    def aidx(name):
        name = norm_area(name)
        if name not in areas: areas[name] = len(areas)
        return areas[name]
    def pidx(name):
        name = (name or "").strip()
        if not name: return -1
        if name not in projects: projects[name] = len(projects)
        return projects[name]

    today = date.today()
    micro_sales_from = today - timedelta(days=MICRO_SALES_DAYS)
    micro_rents_from = today - timedelta(days=MICRO_RENTS_DAYS)

    # ---- sales ----
    s_groups, s_micro, op_groups = {}, [], {}
    for r in sales:
        n_sales += 1
        try:
            d = datetime.fromisoformat(r["INSTANCE_DATE"][:19])
        except Exception:
            continue
        val = r.get("TRANS_VALUE") or 0
        if val <= 1000: continue
        cat = sale_cat(r)
        ai, ci = aidx(r.get("AREA_EN")), CAT_IDX[cat]
        off = 1 if r.get("IS_OFFPLAN") else 0
        bd = beds_code(r.get("ROOMS_EN"))
        area_sqm = r.get("ACTUAL_AREA") or r.get("PROCEDURE_AREA") or 0
        sqft = area_sqm * SQM_TO_SQFT if area_sqm and area_sqm > 0 else 0
        ppsf = val / sqft if sqft > 8 else None
        ym = d.strftime("%Y-%m")
        key = (ym, ai, ci, off, bd)
        g = s_groups.setdefault(key, {"n": 0, "v": [], "p": [], "tot": 0})
        g["n"] += 1; g["v"].append(val); g["tot"] += val
        if ppsf and 40 < ppsf < 40000: g["p"].append(ppsf)
        if off == 1:
            kind = 0 if "Pre registration" in (r.get("PROCEDURE_EN") or "") else 1
            og = op_groups.setdefault((ym, ai, ci, kind), {"n": 0, "p": []})
            og["n"] += 1
            if ppsf and 40 < ppsf < 40000: og["p"].append(ppsf)
        if d.date() >= micro_sales_from:
            s_micro.append([d.strftime("%Y-%m-%d"), ai, ci, off, bd, round(val),
                            round(area_sqm, 1), pidx(r.get("PROJECT_EN") or r.get("MASTER_PROJECT_EN")),
                            1 if r.get("IS_FREE_HOLD") else 0])
    sales_agg = [[k[0], k[1], k[2], k[3], k[4], g["n"], med(g["v"]), med(g["p"]),
                  round(g["tot"] / 1e6, 2), q(g["p"], 0.25), q(g["p"], 0.75)]
                 for k, g in sorted(s_groups.items())]
    op_agg = [[k[0], k[1], k[2], k[3], g["n"], med(g["p"])]
              for k, g in sorted(op_groups.items()) if g["p"]]

    # ---- rents ----
    r_groups, r_micro = {}, []
    for r in rents:
        n_rents += 1
        try:
            d = datetime.fromisoformat(r["REGISTRATION_DATE"][:19])
        except Exception:
            continue
        ann = r.get("ANNUAL_AMOUNT") or 0
        if ann <= 1000 or ann > 5e8: continue
        cat = rent_cat(r)
        ai, ci = aidx(r.get("AREA_EN")), CAT_IDX[cat]
        ver = 1 if (r.get("VERSION_EN") or "").startswith("Renew") else 0
        area_sqm = r.get("ACTUAL_AREA") or 0
        sqft = area_sqm * SQM_TO_SQFT if area_sqm and 8 < area_sqm < 1e6 else 0
        rpsf = ann / sqft if sqft else None
        ym = d.strftime("%Y-%m")
        key = (ym, ai, ci, ver)
        g = r_groups.setdefault(key, {"n": 0, "v": [], "p": []})
        g["n"] += 1; g["v"].append(ann)
        if rpsf and 2 < rpsf < 3000: g["p"].append(rpsf)
        if d.date() >= micro_rents_from:
            r_micro.append([d.strftime("%Y-%m-%d"), ai, ci, ver, round(ann),
                            round(area_sqm, 1), pidx(r.get("PROJECT_EN") or r.get("MASTER_PROJECT_EN")),
                            (r.get("START_DATE") or "")[:10]])
    rents_agg = [[k[0], k[1], k[2], k[3], g["n"], med(g["v"]), med(g["p"]),
                  q(g["p"], 0.25), q(g["p"], 0.75)] for k, g in sorted(r_groups.items())]

    # ---- pre-2026 history from cleaned research dataset (optional) ----
    hist_p = os.path.join(DATA, "history_agg.b64")
    live_from = min((r[0] for r in sales_agg), default="2026-01")
    if os.path.exists(hist_p):
        hist = json.loads(gzip.decompress(base64.b64decode(open(hist_p).read())))
        hs = hr = 0
        for row in hist.get("salesAgg", []):
            if row[0] < live_from:
                sales_agg.append([row[0], aidx(row[1])] + row[2:9] +
                                 [row[9] if len(row) > 9 else None, row[10] if len(row) > 10 else None])
                hs += 1
        live_rents_from = min((r[0] for r in rents_agg), default="2026-01")
        for row in hist.get("rentsAgg", []):
            if row[0] < live_rents_from:
                rents_agg.append([row[0], aidx(row[1])] + row[2:7] +
                                 [row[7] if len(row) > 7 else None, row[8] if len(row) > 8 else None])
                hr += 1
        for row in hist.get("opAgg", []):
            if row[0] < live_from:
                op_agg.append([row[0], aidx(row[1]), row[2], row[3], row[4], row[5]])
        op_agg.sort(key=lambda r: r[0])
        sales_agg.sort(key=lambda r: r[0]); rents_agg.sort(key=lambda r: r[0])
        print(f"history merged: sales {hs} rows, rents {hr} rows (months before {live_from})")

    area_list = [a for a, _ in sorted(areas.items(), key=lambda x: x[1])]
    proj_list = [p for p, _ in sorted(projects.items(), key=lambda x: x[1])]
    payload = {
        "updated": today.isoformat(),
        "cats": CATS,
        "areas": area_list,
        "projects": proj_list,
        "salesAgg": sales_agg,
        "rentsAgg": rents_agg,
        "opAgg": op_agg,
        "salesTx": s_micro,
        "rentsTx": r_micro,
        "microSalesDays": MICRO_SALES_DAYS,
        "microRentsDays": MICRO_RENTS_DAYS,
    }
    os.makedirs(DOCS, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    b64 = base64.b64encode(gzip.compress(raw, 9)).decode()
    with open(os.path.join(DOCS, "payload.b64"), "w") as f:
        f.write(b64)
    print(f"sales rows={n_sales} aggRows={len(sales_agg)} micro={len(s_micro)}")
    print(f"rents rows={n_rents} aggRows={len(rents_agg)} micro={len(r_micro)}")
    print(f"payload raw={len(raw)//1024}KB b64gz={len(b64)//1024}KB areas={len(area_list)}")

if __name__ == "__main__":
    main()
