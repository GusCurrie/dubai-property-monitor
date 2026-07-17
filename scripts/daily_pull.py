#!/usr/bin/env python3
"""Pull DLD open-data (gateway.dubailand.gov.ae) into data/*.jsonl.gz.

Each run refreshes the current month (and the previous month during the first
5 days of a new month), and backfills any month missing since HISTORY_START.
Rents are pulled in overlapping intra-month windows to avoid deep-pagination
drift on the API side; rows are de-duplicated by full-row hash."""
import requests, json, gzip, os, time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

BASE = "https://gateway.dubailand.gov.ae/open-data/"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Content-Type": "application/json",
       "Referer": "https://dubailand.gov.ae/en/open-data/real-estate-data/"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
PAGE = 2000
HISTORY_START = (2026, 1)   # earliest month the DLD open API serves

S_FIELDS = ["TRANSACTION_NUMBER","INSTANCE_DATE","PROCEDURE_EN","IS_OFFPLAN","IS_FREE_HOLD","AREA_EN",
            "TRANS_VALUE","ACTUAL_AREA","PROCEDURE_AREA","USAGE_EN","PROP_TYPE_EN","PROP_SB_TYPE_EN",
            "ROOMS_EN","PROJECT_EN","MASTER_PROJECT_EN"]
R_FIELDS = ["CONTRACT_NUMBER","VERSION_NUMBER","VERSION_EN","REGISTRATION_DATE","START_DATE","END_DATE",
            "AREA_EN","ANNUAL_AMOUNT","CONTRACT_AMOUNT","ACTUAL_AREA","PROP_TYPE_EN","PROP_SUB_TYPE_EN",
            "USAGE_EN","IS_FREE_HOLD","PROJECT_EN","MASTER_PROJECT_EN","ROOMS"]

def post(cmd, payload, tries=6):
    for i in range(tries):
        try:
            r = requests.post(BASE + cmd, headers=HDR, json=payload, timeout=120)
            if r.status_code == 200:
                d = r.json()
                if d.get("response") is not None:
                    return d["response"]["result"]
        except Exception:
            pass
        time.sleep(4 * (i + 1))
    raise RuntimeError(f"failed {cmd} skip={payload.get('P_SKIP')}")

def base_payload(kind, f, t):
    if kind == "sales":
        return {"P_FROM_DATE": f, "P_TO_DATE": t, "P_GROUP_ID": "1", "P_IS_OFFPLAN": "", "P_IS_FREE_HOLD": "",
                "P_AREA_ID": "", "P_USAGE_ID": "", "P_PROP_TYPE_ID": "", "P_TAKE": "1", "P_SKIP": "0", "P_SORT": ""}
    return {"P_FROM_DATE": f, "P_TO_DATE": t, "P_DATE_TYPE": "1", "P_IS_FREE_HOLD": "", "P_VERSION": "",
            "P_AREA_ID": "", "P_USAGE_ID": "", "P_PROP_TYPE_ID": "", "P_TAKE": "1", "P_SKIP": "0", "P_SORT": ""}

def pull_month(kind, y, m):
    cmd = "transactions" if kind == "sales" else "rents"
    fields = S_FIELDS if kind == "sales" else R_FIELDS
    last = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1))
    if kind == "rents":
        bounds = [1, 7, 13, 19, 25]
        wins = [(f"{m:02d}/{b:02d}/{y}",
                 f"{m:02d}/{bounds[i+1]:02d}/{y}" if i + 1 < len(bounds)
                 else f"{last.month:02d}/{last.day:02d}/{last.year}")
                for i, b in enumerate(bounds)]
    else:
        wins = [(f"{m:02d}/01/{y}", f"{last.month:02d}/{last.day:02d}/{last.year}")]
    rows, total = [], 0
    for (wf, wt) in wins:
        probe = post(cmd, base_payload(kind, wf, wt))
        wtotal = probe[0]["TOTAL"] if probe else 0
        total += wtotal
        def get_page(sk, wf=wf, wt=wt):
            p = dict(base_payload(kind, wf, wt)); p["P_TAKE"] = str(PAGE); p["P_SKIP"] = str(sk)
            return post(cmd, p)
        with ThreadPoolExecutor(max_workers=4) as ex:
            for res in ex.map(get_page, range(0, wtotal, PAGE)):
                rows.extend(res)
    seen, out = set(), []
    for r in rows:
        k = r["TRANSACTION_NUMBER"] if kind == "sales" else json.dumps([r.get(fl) for fl in fields], ensure_ascii=False)
        if k in seen: continue
        seen.add(k); out.append({fl: r.get(fl) for fl in fields})
    tag = f"{kind}_{y}_{m:02d}"
    with gzip.open(os.path.join(DATA, f"{tag}.jsonl.gz"), "wt") as gf:
        for r in out:
            gf.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{tag}: total={total} rows={len(out)}", flush=True)

def month_range(start, end):
    y, m = start
    while (y, m) <= end:
        yield (y, m)
        m += 1
        if m == 13: y, m = y + 1, 1

def months_to_pull(kind):
    t = date.today()
    cur = (t.year, t.month)
    need = {cur}
    if t.day <= 5:
        need.add((t.year, t.month - 1) if t.month > 1 else (t.year - 1, 12))
    for (y, m) in month_range(HISTORY_START, cur):
        if not os.path.exists(os.path.join(DATA, f"{kind}_{y}_{m:02d}.jsonl.gz")):
            need.add((y, m))
    return sorted(need)

if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    for kind in ("sales", "rents"):
        for (y, m) in months_to_pull(kind):
            pull_month(kind, y, m)
