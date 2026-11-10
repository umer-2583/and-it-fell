#!/usr/bin/env python3
"""
scrape.py - And It Fell: data collection from the GitHub REST API.

Design (see project_details.md and decision_log.md):
  * Row unit: one public, non-fork repository.
  * Cutoff T = 2024-01-01 UTC.
      features -> human commits in [2023-01-01, 2024-01-01)
      label    -> human commits in [2024-01-01, 2024-06-29)   (180 days, half-open)
  * Label: maintenance_decayed = 1 if there are ZERO human commits in the label window.
  * Stars are used only to stratify the search. They are saved under a name that says
    so (stars_now_sampling_only) and must never be used as a model feature.

Usage:
    export GITHUB_TOKEN=...        # personal access token
    python src/scrape.py --pilot   # ~30 eligible repos -> data/raw/raw_pilot.csv
    python src/scrape.py           # full run            -> data/raw/raw.csv

Re-running is safe: finished repos are skipped (resume) and every API response is cached
in data/cache/, so repeated runs do not spend API quota. Do NOT put data/cache/ in the
submission ZIP. Commit pages are reduced to hashed, minimal fields BEFORE being written
to disk, so no logins or e-mail addresses are stored.
"""
import requests
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path


# Threashold Vars
SEED = 42

CUTOFF = datetime(2024, 1, 1, tzinfo=timezone.utc)      # T
PRE_START = datetime(2023, 1, 1, tzinfo=timezone.utc)   # features window start
LABEL_DAYS = 180                                        # label window length
SENSITIVITY_DAYS = (90, 365)                            # alternative label windows
ONE_SECOND = timedelta(seconds=1)                       # makes windows half-open

MIN_PRE_HUMAN = 5          # primary eligibility: >= 5 human commits in the pre-window
MIN_PRE_FOR_LABEL = 3      # we still collect labels down to 3 so the "min 3" sensitivity check is possible
PAGE_CAP = 5               # max commit pages (100 each) per window; repos hitting it are flagged
PER_PAGE = 100
TARGET_ELIGIBLE = 250
PILOT_TARGET = 30

# Search: language x stars band x creation period.
# Stars are only a sampling device (today's values, not values at T).
LANGUAGES = ["Python", "JavaScript", "TypeScript", "Go", "Rust", "Java", "Dart"]
STAR_BANDS = [("10-49", "10..49"), ("50-499", "50..499"), ("500plus", ">=500")]
CREATED_PERIODS = [("pre2020", "<2020-01-01"), ("2020-2022", "2020-01-01..2022-12-31")]
SEARCH_PAGES_PER_QUERY = 1   # the Search API returns at most 1,000 results per query

# Pacing / retries (we respect rate limits; we never try to bypass them)
SEARCH_SLEEP = 2.5           # search limit is about 30 requests per minute
CORE_SLEEP = 0.1
MAX_RETRIES = 5

# Tutorial/course repos are not representative of projects people depend on.
TUTORIAL_RE = re.compile(
    r"(?<![a-z])(tutorials?|courses?|learning|learn|practice|demo|exercises?|"
    r"homework|assignment|bootcamp|workshop)(?![a-z])"
)
# Bot accounts are excluded so automation does not count as maintenance.
BOT_RE = re.compile(
    r"dependabot|renovate|github-actions|greenkeeper|snyk-bot|pre-commit-ci|"
    r"allcontributors|imgbot|\[bot\]",
    re.IGNORECASE,
)
HASH_SALT = "and-it-fell"    # pseudonymisation only; author identifiers are never stored in clear

# Paths
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "cache"
LOG_PATH = ROOT / "source_log.csv"

API = "https://api.github.com"
SESSION = requests.Session()

LOG_COLUMNS = [
    "timestamp_utc", "method", "url", "params", "repo", "http_status",
    "ratelimit_remaining", "ratelimit_resource", "api_version", "retrieval_method", "note",
]

RAW_COLUMNS = [
    "full_name", "repo_url", "collected_at_utc", "stratum", "search_query",
    "language", "license_spdx", "is_org_owned", "archived_now", "created_at",
    "repo_age_days_at_T", "stars_now_sampling_only",
    # features (strictly pre-T)
    "human_commits_12m_pre", "top_author_share", "bus_factor_50", "num_contributors_12m",
    "days_since_last_commit_pre", "pre_capped", "has_ci_config",
    # label and continuous companions (strictly post-T)
    "post_human_commits_180d", "post_capped", "days_to_first_post_human_commit",
    "maintenance_decayed", "decayed_lt5_180d", "decayed_90d", "decayed_365d",
    # bookkeeping
    "eligible", "exclusion_reason",
]

TERMS_URLS = [
    "https://docs.github.com/en/rest",
    "https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api",
    "https://docs.github.com/en/site-policy/github-terms/github-terms-of-service",
    "https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies",
]


# Small helpers
def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pseudonym(identifier):
    return hashlib.sha256(f"{HASH_SALT}:{identifier.lower()}".encode()).hexdigest()[:12]


# Provenance log (source_log.csv)
def ensure_log():
    if LOG_PATH.exists():
        return
    with open(LOG_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(LOG_COLUMNS)
        w.writerow([
            utc_now_iso(), "NOTE", " ; ".join(TERMS_URLS), "", "", "", "", "", "",
            "GitHub REST API (requests)",
            "Terms/documentation pages relied on. Student records the date each was read.",
        ])


def log_request(url, params, status, resp, repo):
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            utc_now_iso(), "GET", url, json.dumps(params, sort_keys=True), repo, status,
            resp.headers.get("x-ratelimit-remaining", ""),
            resp.headers.get("x-ratelimit-resource", ""),
            resp.headers.get("x-github-api-version-selected", ""),
            "GitHub REST API (requests)", "",
        ])


# HTTP layer: caching, pacing, rate-limit handling
def rate_limit_wait(resp):
    # Seconds to wait if this response is a rate-limit response, else None.
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        return int(retry_after) + 1
    if resp.headers.get("x-ratelimit-remaining") == "0":
        reset = int(resp.headers.get("x-ratelimit-reset", time.time() + 60))
        return max(reset - int(time.time()), 1) + 2
    if "rate limit" in resp.text.lower():
        return 60
    return None


def gh_get(path, params=None, *, repo="", pace=CORE_SLEEP, trim=None):
    # GET with disk cache. Returns (status_code, body). 'trim' shrinks a 200 body before caching.
    params = params or {}
    url = path if path.startswith("http") else API + path
    key = hashlib.sha256((url + json.dumps(params, sort_keys=True)).encode()).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return cached["status"], cached["body"]

    for attempt in range(MAX_RETRIES):
        time.sleep(pace)
        resp = SESSION.get(url, params=params, timeout=30)
        log_request(url, params, resp.status_code, resp, repo)

        if resp.status_code in (403, 429):
            wait = rate_limit_wait(resp)
            if wait is None:           # a real 403 (e.g. blocked repo): final answer
                break
            print(f"  rate limited; sleeping {wait}s", flush=True)
            time.sleep(wait)
            continue
        if resp.status_code >= 500:
            time.sleep(2 ** attempt * 2)
            continue
        break
    else:
        raise RuntimeError(f"Giving up after {MAX_RETRIES} attempts: {url}")

    status = resp.status_code
    body = resp.json() if resp.content else None
    if status == 200 and trim:
        body = trim(body)
    if status in (200, 404, 409, 451, 403):    # final answers only; never cache 5xx/429
        cache_file.write_text(json.dumps({"status": status, "body": body}), encoding="utf-8")

    remaining = resp.headers.get("x-ratelimit-remaining")
    if remaining is not None and int(remaining) <= 1:   # stay under the limit proactively
        reset = int(resp.headers.get("x-ratelimit-reset", time.time() + 60))
        wait = max(reset - int(time.time()), 1) + 2
        print(f"  rate limit almost used; sleeping {wait}s", flush=True)
        time.sleep(wait)
    return status, body


# Trimming (what is written to the cache)
def trim_commits(body):
    # Reduce commit pages to hashed, minimal fields. No logins or e-mails reach the disk.
    out = []
    for c in body:
        author = c.get("author") or {}
        git_author = (c.get("commit") or {}).get("author") or {}
        login = author.get("login")
        name = git_author.get("name") or ""
        email = git_author.get("email") or ""
        is_bot = (
            author.get("type") == "Bot"
            or bool(login and BOT_RE.search(login))
            or bool(BOT_RE.search(name))
        )
        identity = login or email or name or "unknown"
        out.append({
            "sha": c["sha"],
            "date": c["commit"]["committer"]["date"],
            "author": pseudonym(identity),
            "bot": is_bot,
        })
    return out


def trim_search(body):
    items = []
    for i in body.get("items", []):
        items.append({
            "full_name": i["full_name"],
            "name": i["name"],
            "html_url": i["html_url"],
            "description": i.get("description") or "",
            "language": i.get("language"),
            "license": (i.get("license") or {}).get("spdx_id"),
            "owner_type": (i.get("owner") or {}).get("type"),
            "archived": i.get("archived"),
            "fork": i.get("fork"),
            "is_template": i.get("is_template"),
            "created_at": i["created_at"],
            "stargazers_count": i.get("stargazers_count"),
        })
    return {"total_count": body.get("total_count"),
            "incomplete_results": body.get("incomplete_results"),
            "items": items}


def trim_listing(body):
    return {"n": len(body) if isinstance(body, list) else 0}


# Candidate pool (Search API)
def build_candidate_pool():
    pool = {}
    for lang in LANGUAGES:
        for band_name, band_q in STAR_BANDS:
            for period_name, period_q in CREATED_PERIODS:
                query = (
                    f"language:{lang} fork:false mirror:false template:false "
                    f"created:{period_q} pushed:>=2023-01-01 stars:{band_q}"
                )
                for page in range(1, SEARCH_PAGES_PER_QUERY + 1):
                    status, body = gh_get(
                        "/search/repositories",
                        {"q": query, "per_page": 100, "page": page},
                        pace=SEARCH_SLEEP, trim=trim_search,
                    )
                    if status != 200:
                        print(f"  search failed ({status}): {query}", flush=True)
                        break
                    for item in body["items"]:
                        pool.setdefault(item["full_name"], {
                            "item": item,
                            "stratum": f"{lang}|{band_name}|{period_name}",
                            "query": query,
                        })
                    if len(body["items"]) < 100:
                        break
    return pool


# Commit-based measurements
def fetch_human_commits(full_name, since, until, stop_at_first_human=False):
    # Human commits in [since, until]. Returns (commits, capped, error).
    # 'capped' is True when PAGE_CAP full pages were read and more may exist.
    humans = []
    for page in range(1, PAGE_CAP + 1):
        status, body = gh_get(
            f"/repos/{full_name}/commits",
            {"since": iso(since), "until": iso(until), "per_page": PER_PAGE, "page": page},
            repo=full_name, trim=trim_commits,
        )
        if status != 200:
            return humans, False, f"http_{status}"
        humans += [c for c in body if not c["bot"]]
        if stop_at_first_human and humans:
            return humans, False, ""
        if len(body) < PER_PAGE:
            return humans, False, ""
    return humans, True, ""


def concentration(humans):
    # top_author_share, bus_factor_50, number of distinct authors.
    counts = Counter(c["author"] for c in humans)
    total = sum(counts.values())
    ordered = [n for _, n in counts.most_common()]
    cumulative, bus_factor = 0, 0
    for n in ordered:
        cumulative += n
        bus_factor += 1
        if cumulative >= 0.5 * total:
            break
    return ordered[0] / total, bus_factor, len(counts)


def has_ci_config(full_name, ref_sha):
    # 1 if .github/workflows existed at the last pre-T commit, else 0.
    # GitHub Actions only (a narrow proxy for CI). other CI systems are not detected.
    status, body = gh_get(f"/repos/{full_name}/contents/.github/workflows",
                          {"ref": ref_sha}, repo=full_name, trim=trim_listing)
    if status == 200:
        return int(body["n"] > 0)
    if status == 404:
        return 0
    return ""


# One repository -> one row
def process_repo(full_name, info):
    it = info["item"]
    row = {c: "" for c in RAW_COLUMNS}
    created = parse_dt(it["created_at"])
    row.update({
        "full_name": full_name,
        "repo_url": it["html_url"],
        "collected_at_utc": utc_now_iso(),
        "stratum": info["stratum"],
        "search_query": info["query"],
        "language": it["language"] or "",
        "license_spdx": it["license"] or "",
        "is_org_owned": int(it["owner_type"] == "Organization"),
        "archived_now": int(bool(it["archived"])),    # kept as a flag, NOT a feature
        "created_at": it["created_at"],
        "repo_age_days_at_T": (CUTOFF - created).days,
        "stars_now_sampling_only": it["stargazers_count"],
        "eligible": 0,
    })

    if it.get("fork") or it.get("is_template"):
        row["exclusion_reason"] = "fork_or_template"
        return row
    if TUTORIAL_RE.search(f"{it['name']} {it['description']}".lower()):
        row["exclusion_reason"] = "tutorial_like"
        return row

    # features: pre-T window
    pre, pre_capped, err = fetch_human_commits(full_name, PRE_START, CUTOFF - ONE_SECOND)
    if err:
        row["exclusion_reason"] = f"api_error_pre_{err}"
        return row
    row["human_commits_12m_pre"] = len(pre)
    row["pre_capped"] = int(pre_capped)
    if len(pre) < MIN_PRE_FOR_LABEL:
        row["exclusion_reason"] = f"pre_commits_below_{MIN_PRE_FOR_LABEL}"
        return row

    top_share, bus_factor, n_authors = concentration(pre)
    newest = max(pre, key=lambda c: c["date"])
    row.update({
        "top_author_share": round(top_share, 4),
        "bus_factor_50": bus_factor,
        "num_contributors_12m": n_authors,
        "days_since_last_commit_pre": (CUTOFF - parse_dt(newest["date"])).days,
        "has_ci_config": has_ci_config(full_name, newest["sha"]),
    })

    # label: post-T window
    label_end = CUTOFF + timedelta(days=LABEL_DAYS) - ONE_SECOND
    post, post_capped, err = fetch_human_commits(full_name, CUTOFF, label_end)
    if err:
        row["exclusion_reason"] = f"api_error_post_{err}"
        return row
    n_post = len(post)
    row["post_human_commits_180d"] = n_post
    row["post_capped"] = int(post_capped)
    if n_post:
        first = min(parse_dt(c["date"]) for c in post)
        row["days_to_first_post_human_commit"] = (first - CUTOFF).days
    row["maintenance_decayed"] = int(n_post == 0)
    row["decayed_lt5_180d"] = int(n_post < 5)

    # sensitivity windows (a shorter window can reuse the 180-day data if it was not capped)
    d90_end = CUTOFF + timedelta(days=90)
    if not post_capped:
        row["decayed_90d"] = int(not any(parse_dt(c["date"]) < d90_end for c in post))
    else:
        h90, _, err90 = fetch_human_commits(full_name, CUTOFF, d90_end - ONE_SECOND,
                                            stop_at_first_human=True)
        row["decayed_90d"] = "" if err90 else int(len(h90) == 0)
    if n_post > 0:                                   # a commit inside 180 days is inside 365 days
        row["decayed_365d"] = 0
    else:
        h365, _, err365 = fetch_human_commits(
            full_name, CUTOFF, CUTOFF + timedelta(days=365) - ONE_SECOND,
            stop_at_first_human=True)
        row["decayed_365d"] = "" if err365 else int(len(h365) == 0)

    if len(pre) >= MIN_PRE_HUMAN:
        row["eligible"] = 1
    else:
        row["exclusion_reason"] = f"pre_commits_below_{MIN_PRE_HUMAN}"
    return row


# Output / resume / summary
def load_done(path):
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["full_name"]: r["eligible"] == "1" for r in csv.DictReader(f)}


def append_row(path, row):
    needs_header = (not path.exists()) or path.stat().st_size == 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RAW_COLUMNS, extrasaction="ignore")
        if needs_header:
            w.writeheader()
        w.writerow(row)


def summarize(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    eligible = [r for r in rows if r["eligible"] == "1"]
    decayed = sum(r["maintenance_decayed"] == "1" for r in eligible)
    reasons = Counter(r["exclusion_reason"] for r in rows if r["eligible"] != "1")
    print("\n=== Summary ===")
    print(f"Repos processed: {len(rows)}  |  eligible: {len(eligible)}")
    if eligible:
        print(f"Decayed (zero human commits in 180 days): {decayed} "
              f"({decayed / len(eligible):.0%} of eligible)")
    print("Exclusion reasons:", dict(reasons))


def write_run_config(path, args, target, started):
    config = {
        "seed": SEED, "cutoff": iso(CUTOFF), "pre_start": iso(PRE_START),
        "label_days": LABEL_DAYS, "sensitivity_days": list(SENSITIVITY_DAYS),
        "min_pre_human": MIN_PRE_HUMAN, "min_pre_for_label": MIN_PRE_FOR_LABEL,
        "page_cap": PAGE_CAP, "target_eligible": target, "pilot": args.pilot,
        "languages": LANGUAGES, "star_bands": STAR_BANDS, "created_periods": CREATED_PERIODS,
        "search_pages_per_query": SEARCH_PAGES_PER_QUERY,
        "started_utc": started, "finished_utc": utc_now_iso(),
        "python": sys.version.split()[0], "requests": requests.__version__,
    }
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Collect GitHub data for And It Fell.")
    parser.add_argument("--pilot", action="store_true",
                        help=f"small run ({PILOT_TARGET} eligible repos) written to raw_pilot.csv")
    parser.add_argument("--target", type=int, help="override the number of eligible repos")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set the GITHUB_TOKEN environment variable first (do not hard-code it).")
    SESSION.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "and-it-fell-course-project",
    })

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ensure_log()
    started = utc_now_iso()

    target = args.target or (PILOT_TARGET if args.pilot else TARGET_ELIGIBLE)
    out_path = RAW_DIR / ("raw_pilot.csv" if args.pilot else "raw.csv")

    print("Building candidate pool (Search API)...", flush=True)
    pool = build_candidate_pool()
    print(f"Candidate pool: {len(pool)} unique repositories", flush=True)

    names = sorted(pool)                  # sort first so the shuffle is reproducible
    random.Random(SEED).shuffle(names)

    done = load_done(out_path)
    n_eligible = sum(done.values())
    for full_name in names:
        if n_eligible >= target:
            break
        if full_name in done:
            continue
        row = process_repo(full_name, pool[full_name])
        append_row(out_path, row)
        n_eligible += row["eligible"] == 1
        status = "ok" if row["eligible"] == 1 else f"skip ({row['exclusion_reason']})"
        print(f"[{n_eligible}/{target}] {full_name}: {status}", flush=True)

    write_run_config(RAW_DIR / ("run_config_pilot.json" if args.pilot else "run_config.json"),
                     args, target, started)
    if out_path.exists():
        summarize(out_path)
    if n_eligible < target:
        print("\nCandidate pool exhausted before reaching the target; "
              "widen the strata (see decision_log.md) rather than changing the label.")


if __name__ == "__main__":
    main()