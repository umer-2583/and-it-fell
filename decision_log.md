# Decision Log: And It Fell

Each entry: what was decided, why, and the trade-off. Append new rows as decisions are made  never rewrite old ones (mark them "superseded" instead).

## Design decisions

| # | Decision | Why | Trade-off |
|---|---|---|---|
| 1 | GitHub REST API only | Course source, documented API, no HTML scraping | Single-source sample |
| 2 | Row unit: one public non-fork repository | Independent rows | Forks and monorepos excluded |
| 3 | Cutoff T = 2024-01-01 UTC, features from [2023-01-01, 2024-01-01), label from [2024-01-01, 2024-06-29) | Post window is complete before collection, half-open windows avoid off-by-one | Data is about 3 years old |
| 4 | Label `maintenance_decayed` = zero human commits in 180 days | Simple, observed, does not mechanically depend on a predictor | Measures inactivity, not breakage, finished projects look decayed |
| 5 | Looser label (<5 commits), 90/365-day windows, min pre-commits 3 and 10 kept as sensitivity checks only | Shows results do not hinge on one threshold | Extra runs |
| 6 | Bots excluded (`type=Bot`, `[bot]` suffix, Dependabot/Renovate/github-actions) | Automation would inflate "maintenance" | Imperfect bot detection |
| 7 | Eligibility: at least 5 human commits in the pre-window, tutorial/course repos removed (count reported) | Top-author share is meaningless with 1–2 commits, tutorials are unrepresentative | Judgment thresholds |
| 8 | Archived repos kept, flag recorded | Archive status is only available as of today, filtering would remove decay cases | None for the label, archived flag not used as a predictor |
| 9 | Stars used only to stratify the search (bands 10–49, 50–499, 500+), never as a feature | Stars are measured today (post-T) and would leak | Floor narrows concentration variation |
| 10 | `stars_at_cutoff` dropped | API gives no historical star counts | Fewer features |
| 11 | Excluded post-T fields: stars, forks, open issues, watchers, `pushed_at`, `updated_at` | Leakage | None |
| 12 | `language`, `license`, `is_org_owned` allowed as current values | Rarely change, disclosed | Minor residual risk |
| 13 | Mixed-language sample (Dart/Flutter-only considered and rejected) | Easier collection, gives a language subgroup comparison | Less tied to the original motivation |
| 14 | Commit pages capped per repo, capped repos flagged | API budget | Truncated counts for very active repos |
| 15 | Aggregates only, author IDs hashed in memory, no emails, raw cache not shipped | Commit authorship is personal data | Cannot inspect individuals later |

## Modeling decisions

| # | Decision | Why |
|---|---|---|
| 16 | Stratified 80/20 split, seed 42 | Keeps class ratio in both sets, reproducible |
| 17 | k-NN on scaled features, k chosen by cross-validation on the training set only | Prevents test-set tuning |
| 18 | Baseline: majority class | Required reference for accuracy |
| 19 | Compare activity-only vs activity + concentration (`top_author_share`, `bus_factor_50`) | Tests whether concentration adds value |
| 20 | Report accuracy, precision, recall, F1, confusion matrix | Accuracy alone is misleading if classes are imbalanced |
| 21 | K-Means on scaled features, k = 2–5 by silhouette, seed-stability check, label not used | Clusters are descriptive only, not types or causes |

## Changes after the pilot


| Date | Change | Reason |
|---|---|---|
| | | |