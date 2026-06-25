import os
import json
import time
import numpy as np
import requests
from datetime import datetime, timezone
from functions.utils.db.connect import get_db_client
from functions.utils.macro.scheduler import RateLimitError
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
env_path = os.path.join(sentiment_dir, ".env.local")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

def init_macro_indicators():
    """Seeds the macro_indicators collection with the base tracking configuration."""
    indicators = [
        {"ff_event_name": "Final GDP q/q", "full_name": "Final / Flash GDP q/q", "category": "GROWTH", "av_indicator": "REAL_GDP", "window": 12},
        {"ff_event_name": "CPI m/m", "full_name": "Consumer Price Index (Month over Month)", "category": "INFLATION", "av_indicator": "CPI", "window": 12},
        {"ff_event_name": "CPI y/y", "full_name": "Consumer Price Index (Year over Year)", "category": "INFLATION", "av_indicator": "CPI", "window": 12},
        {"ff_event_name": "Core CPI m/m", "full_name": "Core Consumer Price Index (Month over Month)", "category": "INFLATION", "av_indicator": "CPI", "window": 12},
        {"ff_event_name": "Unemployment Rate", "full_name": "Unemployment Rate", "category": "EMPLOYMENT", "av_indicator": "UNEMPLOYMENT", "window": 12},
        {"ff_event_name": "Non-Farm Employment Change", "full_name": "Non-Farm Employment Change", "category": "EMPLOYMENT", "av_indicator": "NONFARM_PAYROLL", "window": 12},
        {"ff_event_name": "Retail Sales m/m", "full_name": "Retail Sales (Month over Month)", "category": "CONSUMER", "av_indicator": "RETAIL_SALES", "window": 12},
        {"ff_event_name": "Core Retail Sales m/m", "full_name": "Core Retail Sales (Month over Month)", "category": "CONSUMER", "av_indicator": "RETAIL_SALES", "window": 12},
        {"ff_event_name": "Durable Goods Orders m/m", "full_name": "Durable Goods Orders", "category": "MANUFACTURING", "av_indicator": "DURABLE_GOODS", "window": 12},
        {"ff_event_name": "Crude Oil Inventories", "full_name": "Crude Oil Inventories", "category": "ENERGY", "av_indicator": "WTI", "window": 12},
        {"ff_event_name": "Natural Gas Storage", "full_name": "Natural Gas Storage", "category": "ENERGY", "av_indicator": "NATURAL_GAS", "window": 12},
        {"ff_event_name": "Federal Funds Rate", "full_name": "Federal Funds Rate", "category": "RATES", "av_indicator": "FEDERAL_FUNDS_RATE", "window": 12},
        {"ff_event_name": "Core PCE m/m", "full_name": "Core Personal Consumption Expenditures", "category": "INFLATION", "av_indicator": "INFLATION", "window": 12},
        {"ff_event_name": "Initial Jobless Claims", "full_name": "Initial Jobless Claims", "category": "EMPLOYMENT", "av_indicator": "UNEMPLOYMENT", "window": 12},
        {"ff_event_name": "ISM Manufacturing PMI", "full_name": "ISM Manufacturing PMI", "category": "MANUFACTURING", "av_indicator": "REAL_GDP", "window": 12},
        {"ff_event_name": "ISM Services PMI", "full_name": "ISM Services PMI", "category": "SERVICES", "av_indicator": "REAL_GDP", "window": 12}
    ]
    client, db = get_db_client()
    col = db["macro_indicators"]
    for ind in indicators:
        col.update_one({"ff_event_name": ind["ff_event_name"]}, {"$set": ind}, upsert=True)
    return len(indicators)

def fetch_std_dev(av_indicator: str, window: int, api_key: str):
    url = f"https://www.alphavantage.co/query?function={av_indicator}&apikey={api_key}"
    response = requests.get(url)
    
    if response.status_code != 200:
        raise Exception(f"HTTP Error {response.status_code}: {response.text}")
        
    mcp_result = response.json()

    if isinstance(mcp_result, dict) and "Information" in mcp_result:
        raise RateLimitError(mcp_result["Information"])
        
    if isinstance(mcp_result, dict) and "Error Message" in mcp_result:
        raise Exception(f"Alpha Vantage API error: {mcp_result['Error Message']}")

    records = mcp_result.get("data", []) if isinstance(mcp_result, dict) else []
    if not records:
        raise Exception("Empty data returned")

    values = []
    for record in records[:window + 1]:
        val_str = record.get("value", "")
        if val_str and val_str != ".":
            values.append(float(val_str))

    if len(values) < 2:
        raise Exception(f"Insufficient data points ({len(values)})")

    std_val = float(np.std(np.diff(values)))
    return std_val

def update_macro_baselines(limit: str, failed_results_path: str):
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        print("Error: ALPHA_VANTAGE_API_KEY is not set.")
        return

    client, db = get_db_client()
    ind_col = db["macro_indicators"]
    base_col = db["macro_baselines"]
    
    # Read indicators from MongoDB dynamically
    cursor = ind_col.find({})
    targets = list(cursor)
    
    if not targets:
        print("No indicators found in 'macro_indicators' collection. Run --init first.")
        return
        
    if limit.lower() != "all":
        try:
            num = int(limit)
            targets = targets[:num]
        except ValueError:
            print("Invalid limit argument. Use an integer or 'all'.")
            return
            
    failed_results = []
    
    print(f"Starting seed for {len(targets)} indicators...")
    for i, target in enumerate(targets):
        print(f"[{i+1}/{len(targets)}] Processing {target['ff_event_name']}...")
        try:
            std_dev = fetch_std_dev(target["av_indicator"], target["window"], api_key)
            
            doc = {
                "ff_event_name": target["ff_event_name"],
                "full_name": target["full_name"],
                "category": target["category"],
                "av_indicator": target["av_indicator"],
                "std_dev": std_dev,
                "unit": "percentage",
                "source": "alpha_vantage",
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            base_col.update_one(
                {"ff_event_name": target["ff_event_name"]},
                {"$set": doc},
                upsert=True
            )
            print(f"  -> Success: std_dev = {std_dev}")
            
        except Exception as e:
            print(f"  -> Failed: {e}")
            failed_results.append({
                "ff_event_name": target["ff_event_name"],
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
        if i < len(targets) - 1:
            print("  Sleeping for 15 seconds to respect rate limits...")
            time.sleep(15)
            
    if failed_results:
        with open(failed_results_path, "w") as f:
            json.dump(failed_results, f, indent=4)
        print(f"Finished with errors. Failed results saved to {failed_results_path}")
    else:
        print("Finished successfully.")
