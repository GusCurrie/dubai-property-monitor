# Dubai Property Monitor

Interactive dashboard of Dubai real estate **sales transactions** and **Ejari rental contracts**,
built from Dubai Land Department open data and refreshed automatically every morning (Dubai time).

**Live dashboard:** https://guscurrie.github.io/dubai-property-monitor/

## How it works

- `scripts/daily_pull.py` — pulls the latest records from the DLD open-data API
  (`gateway.dubailand.gov.ae/open-data/`), re-fetching the current month (and the previous
  month early in a new month) into `data/*.jsonl.gz`.
- `scripts/aggregate.py` — filters, categorises (apartments, villas, offices, retail, land, …)
  and aggregates everything into a compact compressed payload (`docs/payload.b64`):
  monthly medians by area, category, bedrooms and off-plan/ready split, plus row-level
  detail for the recent window.
- `scripts/build.py` — splices the payload into `docs/template.html` → `docs/index.html`,
  a fully self-contained interactive dashboard (no external dependencies).
- `.github/workflows/refresh.yml` — GitHub Actions cron (05:45 Dubai, daily) that runs the
  three scripts and commits the result. GitHub Pages serves `docs/`.

## Notes

- Data source: Dubai Land Department open data. The public API serves transactions from
  January 2026 onward; history accumulates in `data/` from there.
- Sales = DLD "Sales" group registrations. Rents = Ejari contracts by registration date.
- Sizes are converted at 1 sqm = 10.7639 sqft. All values AED.
