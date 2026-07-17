import os
import sys
import logging
import requests

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def seed_fred_mappings_if_empty(db):
    """Seed default FRED mappings in the fred_mappings collection if it is empty."""
    col = db["fred_mappings"]
    if col.count_documents({}) == 0:
        logger.info("Seeding default FRED mappings in MongoDB...")
        default_mappings = [
            {"title": "CPI m/m", "series_id": "CPIAUCSL", "calc_type": "m/m"},
            {"title": "Core CPI m/m", "series_id": "CPILFESL", "calc_type": "m/m"},
            {"title": "CPI y/y", "series_id": "CPIAUCSL", "calc_type": "y/y"},
            {"title": "Core CPI y/y", "series_id": "CPILFESL", "calc_type": "y/y"},
            {"title": "Unemployment Rate", "series_id": "UNRATE", "calc_type": "raw"},
            {"title": "Federal Funds Rate", "series_id": "FEDFUNDS", "calc_type": "raw"},
            {"title": "Unemployment Claims", "series_id": "ICSA", "calc_type": "raw"},
            {"title": "Building Permits", "series_id": "PERMIT", "calc_type": "raw"},
            {"title": "Housing Starts", "series_id": "HOUST", "calc_type": "raw"},
            {"title": "Capacity Utilization Rate", "series_id": "TCU", "calc_type": "raw"},
            {"title": "Industrial Production m/m", "series_id": "INDPRO", "calc_type": "m/m"},
            {"title": "Retail Sales m/m", "series_id": "RSXFS", "calc_type": "m/m"},
            {"title": "Core Retail Sales m/m", "series_id": "RSXFS", "calc_type": "m/m"}
        ]
        col.insert_many(default_mappings)
        logger.info(f"Successfully seeded {len(default_mappings)} mappings.")

def get_fred_series_observations(series_id: str, api_key: str) -> list:
    """Fetch observations from the official FRED API."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": 24
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        observations = []
        for obs in data.get("observations", []):
            try:
                val = float(obs["value"])
                observations.append({
                    "date": obs["date"],
                    "value": val
                })
            except (ValueError, KeyError):
                continue  # Skip revisions or missing values (like '.')
        return observations
    except Exception as e:
        logger.error(f"FRED API fetch failed for {series_id}: {e}")
        return []

def get_fred_series_csv(series_id: str) -> list:
    """Fetch observations from the public FRED CSV export endpoint (no API key fallback)."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        lines = response.text.strip().split("\n")
        if len(lines) <= 1:
            return []
        
        observations = []
        # Header is: DATE,VALUE_ID
        for line in lines[1:]:
            parts = line.strip().split(",")
            if len(parts) != 2:
                continue
            date_str, val_str = parts[0], parts[1]
            try:
                val = float(val_str)
                observations.append({
                    "date": date_str,
                    "value": val
                })
            except ValueError:
                continue  # skip '.' or header anomalies
                
        # Sort descending (newest first)
        observations.reverse()
        return observations[:24]
    except Exception as e:
        logger.error(f"FRED CSV fallback fetch failed for {series_id}: {e}")
        return []

def format_fred_value(title: str, val: float) -> str:
    """Format numeric FRED value to match ForexFactory format conventions."""
    t_lower = title.lower()
    if "rate" in t_lower or "ratio" in t_lower or "capacity utilization" in t_lower:
        return f"{val:.1f}%"
    elif "claims" in t_lower:
        # e.g., 216000 -> 216K
        return f"{val/1000:.0f}K"
    elif "permits" in t_lower or "starts" in t_lower:
        # e.g., 1410 (thousands) -> 1.41M
        return f"{val/1000:.2f}M"
    else:
        return f"{val}"

def get_fred_actual(event_title: str, db) -> str:
    """
    Primary interface to retrieve mapped actual values from FRED.
    Returns the formatted actual value string, or None if unavailable/unmapped.
    """
    # 1. Ensure mappings are seeded
    seed_fred_mappings_if_empty(db)
    
    # 2. Lookup mapping
    mapping = db["fred_mappings"].find_one({"title": event_title})
    if not mapping:
        logger.debug(f"Event '{event_title}' is not mapped to FRED.")
        return None
        
    series_id = mapping["series_id"]
    calc_type = mapping["calc_type"]
    logger.info(f"Mapped event '{event_title}' to FRED Series '{series_id}' (calc={calc_type})")
    
    # 3. Retrieve API key
    api_key = os.getenv("FRED_API_KEY") or os.getenv("FRED_API")
    
    # 4. Fetch observations
    obs = []
    if api_key:
        obs = get_fred_series_observations(series_id, api_key)
        
    if not obs:
        logger.warning(f"FRED API key missing or request failed. Falling back to public CSV export...")
        obs = get_fred_series_csv(series_id)
        
    if not obs:
        logger.error(f"Failed to retrieve any data from FRED for series {series_id}.")
        return None
        
    # 5. Process based on calculation type
    try:
        if calc_type == "raw":
            latest_val = obs[0]["value"]
            return format_fred_value(event_title, latest_val)
            
        elif calc_type == "m/m":
            if len(obs) < 2:
                logger.error(f"Insufficient history (need 2 points) for m/m calc of {series_id}")
                return None
            val_a = obs[0]["value"]
            val_b = obs[1]["value"]
            pct = ((val_a - val_b) / val_b) * 100
            return f"{pct:+.1f}%" if pct != 0 else f"{pct:.1f}%"
            
        elif calc_type == "y/y":
            # For y/y we need monthly data going back 12 observations (since obs are monthly)
            # Or if it's weekly (like ICSA), 52 observations.
            # But the mapped y/y indicators (CPI, Core CPI) are monthly.
            target_idx = 12
            if len(obs) <= target_idx:
                logger.error(f"Insufficient history (need {target_idx + 1} points) for y/y calc of {series_id}")
                return None
            val_a = obs[0]["value"]
            val_b = obs[target_idx]["value"]
            pct = ((val_a - val_b) / val_b) * 100
            return f"{pct:+.1f}%" if pct != 0 else f"{pct:.1f}%"
            
    except Exception as e:
        logger.error(f"Error executing calculations for FRED series {series_id}: {e}")
        
    return None
