import os
import sys
import argparse
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, ".."))
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.macro.baselines import init_macro_indicators, update_macro_baselines, fetch_std_dev
from functions.utils.db.connect import get_db_client
from datetime import datetime, timezone

env_path = os.path.join(sentiment_dir, ".env.local")
if os.path.exists(env_path):
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed macro baselines to MongoDB")
    parser.add_argument("--init", action="store_true", help="Push the hardcoded indicators to the MongoDB macro_indicators collection")
    parser.add_argument("--limit", type=str, default="5", help="Number of indicators to seed, or 'all'")
    parser.add_argument("--update", type=str, help="Update a specific FF_EVENT_NAME")
    args = parser.parse_args()

    if args.init:
        count = init_macro_indicators()
        print(f"Successfully pushed {count} indicators to 'macro_indicators' MongoDB collection.")
        
    elif args.update:
        client, db = get_db_client()
        ind_col = db["macro_indicators"]
        base_col = db["macro_baselines"]
        
        target = ind_col.find_one({"ff_event_name": args.update})
        if not target:
            print(f"Indicator '{args.update}' not found in 'macro_indicators' collection.")
        else:
            api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
            if not api_key:
                print("Error: ALPHA_VANTAGE_API_KEY is not set.")
                sys.exit(1)
            
            try:
                std_dev = fetch_std_dev(target["av_indicator"], target.get("window", 12), api_key)
                doc = {
                    "ff_event_name": target["ff_event_name"],
                    "full_name": target.get("full_name", ""),
                    "category": target.get("category", ""),
                    "av_indicator": target["av_indicator"],
                    "std_dev": std_dev,
                    "unit": "percentage",
                    "source": "alpha_vantage",
                    "last_updated": datetime.now(timezone.utc).isoformat()
                }
                base_col.update_one({"ff_event_name": target["ff_event_name"]}, {"$set": doc}, upsert=True)
                print(f"Successfully updated {args.update} with std_dev = {std_dev}")
            except Exception as e:
                print(f"Failed to update {args.update}: {e}")
                
    else:
        failed_path = os.path.join(script_dir, "failed_macro_results.json")
        update_macro_baselines(args.limit, failed_path)
