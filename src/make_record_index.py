#!/usr/bin/env python3
"""
make_record_index.py - build record_index.csv from data/raw/raw.csv.

Output columns (instructor format): project_id, record_id, canonical_source_key, source_url

  project_id            constant for this project
  record_id             R001, R002, ... assigned after sorting by canonical_source_key,
                        so the IDs do not depend on the order rows were collected in
  canonical_source_key  github.com/<owner>/<repo> in lower case (GitHub names are
                        case-insensitive), the stable key that identifies the source
  source_url            the repository's public URL as returned by the API

Every row in raw.csv gets an ID, including rows later excluded in cleaning, so each raw
record can be traced. Re-running after more collection regenerates the file, and the IDs
of existing records can change if new repositories sort before them: regenerate once,
after the final collection run.

Usage:
    python src/make_record_index.py
    python src/make_record_index.py --raw data/raw/raw_pilot.csv --out /tmp/record_index_pilot.csv
"""
import argparse
import csv
import sys
from pathlib import Path

PROJECT_ID = "T-14"
ROOT = Path(__file__).resolve().parent.parent
HEADER = ["project_id", "record_id", "canonical_source_key", "source_url"]


def build_index(raw_path):
    with open(raw_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        sys.exit(f"{raw_path} has no rows; run scrape.py first.")

    records = {}
    for r in rows:
        key = f"github.com/{r['full_name'].strip().lower()}"
        url = r["repo_url"].strip()
        if not r["full_name"] or not url:
            sys.exit(f"Row without full_name or repo_url: {r}")
        records.setdefault(key, url)            # one record per repository

    width = max(3, len(str(len(records))))
    return [
        [PROJECT_ID, f"R{i:0{width}d}", key, records[key]]
        for i, key in enumerate(sorted(records), start=1)
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", default=str(ROOT / "data" / "raw" / "raw.csv"))
    parser.add_argument("--out", default=str(ROOT / "record_index.csv"))
    args = parser.parse_args()

    index = build_index(args.raw)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(index)
    print(f"Wrote {len(index)} records to {args.out}")


if __name__ == "__main__":
    main()