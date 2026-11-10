import os
import pandas as pd

def generate_source_log(raw_path="data/raw/raw.csv", output_path="source_log.csv", project_id="T-14"):
    """
    Reads data/raw/raw.csv and constructs source_log.csv adhering to the 
    required project schema.
    """
    if not os.path.exists(raw_path):
        raise FileNotFoundError(f"Raw data file not found at '{raw_path}'. Run scrape.py first.")

    raw_df = pd.read_csv(raw_path)
    
    # Construct source log matching mandatory fields
    source_log_df = pd.DataFrame()
    source_log_df["project_id"] = [project_id] * len(raw_df)
    source_log_df["url"] = raw_df["repo_url"]
    source_log_df["access_method"] = "GitHub REST API v3"
    source_log_df["collected_at"] = raw_df.get("fetched_at", pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M:%S UTC"))
    source_log_df["permission_notes"] = "Public GitHub REST API; complies with GitHub Terms of Service and rate limits"
    source_log_df["records"] = 1  # 1 record per repository row
    source_log_df["data_origin_type"] = "Public Web API"
    
    source_log_df.to_csv(output_path, index=False)
    print(f"Successfully generated '{output_path}' with {len(source_log_df)} records.")

if __name__ == "__main__":
    generate_source_log()