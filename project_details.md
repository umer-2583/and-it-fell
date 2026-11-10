# Project Details – Phase 1
**Project Title:** And It Fell: Does a Low Bus Factor Predict Maintenance Decay in Open-Source Projects?

**Course:** DS2001 – Introduction to Data Science\
**Roll No:** 24L-2583\
**Student:** Muhammad Umer Khan\
**Repository:** https://github.com/umer-2583/and-it-fell.git 

---

## 1. Research Question

Does contributor concentration (bus factor and top-author commit share), measured before a fixed cutoff date, predict whether human maintenance activity drops significantly in the following 180 days?

---

## 2. Project Motive

While most repository metrics focus on popularity, this project examines repository *fragility* — specifically, the risk of maintenance decay. Using the GitHub API, we extract activity metrics and contributor concentration (bus factor and top-author commit share) up to a fixed cutoff date. The supervised learning objective tests whether these historical features can predict a significant drop in human maintenance activity over the subsequent 180 days. The goal is to provide a screening signal that helps developers identify dependencies at higher risk of becoming unmaintained, not to issue a definitive judgment on any individual project.

---

## 3. Data Source and Ethics

- **Source:** Official GitHub REST API (api.github.com)
- **Access Method:** Authenticated requests using a personal access token (respecting rate limits)
- **Permitted Use:** Only public repository metadata and public commit/contributor data are collected. No private data, no bypassing of access controls, and no scraping of GitHub’s web interface.
- **Evidence of Permission:** GitHub’s official API documentation explicitly allows authenticated access to public repository data for research and analysis purposes, subject to rate limits and terms of service.
- **Provenance:** Every API call is logged with timestamp, endpoint, and repository identifier in `source_log.csv`.

---

## 4. Sampling Strategy

| Criterion                    | Value                          | Justification                              |
|-----------------------------|--------------------------------|--------------------------------------------|
| Minimum stars               | >= 50                           | Avoid very small / throwaway repositories  |
| Minimum commits             | >= 30                           | Ensure enough history to measure concentration |
| Creation date               | Before cutoff date             | Must have pre-cutoff history               |
| Archive status at cutoff    | Not archived                   | Focus on projects that were still alive    |
| Forks                       | Excluded (or only non-forks)   | Reduce noise from pure copies              |
| Target sample size          | 150–300 repositories           | As required by the project brief           |

**Cutoff Date:** 1 January 2024  
- Features are calculated using data **before** this date.  
- Ground truth is measured in the **180 days after** this date (1 Jan 2024 – 29 Jun 2024).

---

## 5. Ground Truth Definition

**Target variable:** `maintenance_decayed` (binary)

A repository is labelled as decayed (`1`) if, in the 180 days after the cutoff:
- It received fewer than 5 human commits

Otherwise it is labelled `0`.

Continuous versions of post-cutoff activity (total human commits, days since last human commit) are also stored for additional analysis.

---

## 6. Features (Pre-Cutoff Only)

| Feature                      | Type     | Description                                          |
|-----------------------------|----------|------------------------------------------------------|
| `top_author_share`          | Numeric  | Proportion of commits by the single most active author |
| `bus_factor_50`             | Numeric  | Number of authors needed to reach 50% of commits     |
| `num_contributors`          | Numeric  | Number of distinct human contributors                |
| `total_commits_pre`         | Numeric  | Total commits before the cutoff                      |
| `commits_last_12m_pre`      | Numeric  | Commits in the 12 months immediately before cutoff   |
| `days_since_last_commit_pre`| Numeric  | Days between last pre-cutoff commit and the cutoff   |
| `stars_at_cutoff`           | Numeric  | Approximate number of stars near the cutoff          |
| `is_org_owned`              | Binary   | Whether the repository is owned by an organization   |

At least five of these features will be used in the final analysis.

---

## 7. Collection Method

Data is collected programmatically using the official GitHub REST API via Python (`requests` + authentication).  

The collection script (`src/scrape.py`):
1. Searches for candidate repositories using the Search API.
2. Retrieves repository metadata.
3. Retrieves commit history up to the cutoff date.
4. Computes contributor concentration metrics.
5. Retrieves post-cutoff activity for ground-truth labelling.
6. Logs every request in `source_log.csv`.

Raw responses are stored and later flattened into `data/raw/raw.csv`.

---

## 8. Current Status (Phase 1)

- Research question and operational definitions finalized
- Sampling criteria and cutoff date locked
- Project structure created
- Source logging format defined
- Data dictionary created
- Collection script under development
- Target: 120–300 cleaned repositories with ≥ 5 usable features

---

## 9. Reproducibility Notes

- All random seeds and API parameters will be recorded.
- Exact query filters and pagination logic are documented in `src/scrape.py` and `decision_log.md`.
- Raw data and source logs are preserved so the collection process can be audited.