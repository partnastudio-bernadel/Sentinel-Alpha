import os
import sys
import time
import requests
import logging
from datetime import datetime, timedelta, timezone
from dateutil import parser
from pymongo import MongoClient, UpdateOne
from apscheduler.schedulers.background import BackgroundScheduler

# Setup paths
script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(script_dir)
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.db.connect import get_db_client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
HEADERS = {'User-Agent': 'Mozilla/5.0 SentinelAlpha/1.0'}

CORE_EVENTS = [
    "Non-Farm Employment Change", "CPI", "Core CPI", "Unemployment Rate", 
    "ISM Manufacturing PMI", "FOMC", "Federal Funds Rate", "New Home Sales"
]

EVENT_TO_INDICATOR_MAP = {
    "CPI m/m": "CPI",
    "CPI y/y": "CPI",
    "Core CPI m/m": "CPI",
    "Core CPI y/y": "CPI",
    "Non-Farm Employment Change": "NFP",
    "Unemployment Rate": "Unemployment",
    "ISM Manufacturing PMI": "PMI",
    "Federal Funds Rate": "Interest Rate",
    "FOMC Statement": "FOMC",
    "New Home Sales": "Housing"
}

def map_event_to_indicator(event_title: str) -> str:
    for key, indicator in EVENT_TO_INDICATOR_MAP.items():
        if key.lower() in event_title.lower():
            return indicator
    return event_title.split()[0]  # Fallback

def is_core_event(title: str) -> bool:
    for core in CORE_EVENTS:
        if core.lower() in title.lower():
            return True
    return False

def get_db_collection():
    from dotenv import load_dotenv
    env_path = os.path.join(sentiment_dir, ".env.local")
    load_dotenv(env_path)
    client, db = get_db_client()
    return db["macro_calendar"]

def fetch_and_store_weekly_calendar():
    """Runs on Sunday to fetch the entire week's schedule."""
    logger.info("Fetching weekly calendar from ForexFactory...")
    try:
        response = requests.get(FF_URL, headers=HEADERS)
        response.raise_for_status()
        events = response.json()
        
        collection = get_db_collection()
        operations = []
        
        for event in events:
            # We filter for USD events that are High, Medium, or Low impact (dropping Neutral/Holiday)
            impact = event.get("impact")
            if event.get("country") == "USD" and (impact in ["High", "Medium", "Low"] or is_core_event(event.get("title", ""))):
                date_str = event.get("date")
                if not date_str:
                    continue
                
                # Upsert to avoid duplicates
                filter_query = {"title": event["title"], "date": date_str}
                update_data = {"$set": {
                    "title": event["title"],
                    "country": event["country"],
                    "date": date_str,
                    "impact": event["impact"],
                    "forecast": event.get("forecast", ""),
                    "previous": event.get("previous", ""),
                    "status": "pending"
                }}
                operations.append(UpdateOne(filter_query, update_data, upsert=True))
                
        if operations:
            result = collection.bulk_write(operations)
            logger.info(f"Upserted {result.upserted_count} new events, modified {result.modified_count}.")
        else:
            logger.info("No USD High/Core impact events found for this week.")
            
    except Exception as e:
        logger.error(f"Failed to fetch or store weekly calendar: {e}")

def hourly_realized_data_sweep():
    """Hourly sweep to fetch the JSON once and process all pending events."""
    logger.info("Starting hourly sweep for realized data...")
    try:
        response = requests.get(FF_URL, headers=HEADERS)
        response.raise_for_status()
        events = response.json()
        
        collection = get_db_collection()
        
        # Create a fast lookup dictionary for the fetched events: (title, date) -> actual
        fetched_actuals = {}
        for event in events:
            if event.get("title") and event.get("date") and event.get("actual"):
                fetched_actuals[(event["title"], event["date"])] = event["actual"]
                
        pending_events = collection.find({"status": "pending"})
        
        for p_event in pending_events:
            title = p_event["title"]
            date_str = p_event["date"]
            
            actual_val = fetched_actuals.get((title, date_str))
            
            if actual_val:
                logger.info(f"Successfully swept realized data for {title}: {actual_val}")
                
                # Update DB
                collection.update_one(
                    {"_id": p_event["_id"]},
                    {"$set": {"actual": actual_val, "status": "completed"}}
                )
                
                logger.info(f"Triggering Math Engine for {title}...")
                mapped_indicator = map_event_to_indicator(title)
                try:
                    from scripts.macro_ingestion_cli import run_macro_ingestion_single
                    import threading
                    threading.Thread(
                        target=run_macro_ingestion_single,
                        args=(title, mapped_indicator),
                        daemon=True
                    ).start()
                except Exception as e:
                    logger.error(f"Failed to start macro ingestion thread: {e}")
                    
    except Exception as e:
        logger.error(f"Failed to execute hourly sweep: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ForexFactory Calendar & Scheduler Agent")
    parser.add_argument("--fetch", action="store_true", help="Fetch and store the weekly calendar immediately, then exit.")
    parser.add_argument("--sweep", action="store_true", help="Run the hourly realized data sweep immediately, then exit.")
    args = parser.parse_args()
    
    if args.fetch:
        fetch_and_store_weekly_calendar()
    elif args.sweep:
        hourly_realized_data_sweep()
    else:
        scheduler = BackgroundScheduler()
        
        # 1. Schedule the Sunday Scrape (17:00 EST / 21:00 UTC)
        scheduler.add_job(fetch_and_store_weekly_calendar, 'cron', day_of_week=6, hour=17, timezone='EST')
        
        # 2. Schedule the Hourly Sweep (run at 5 minutes past the hour to allow ForexFactory to update)
        scheduler.add_job(hourly_realized_data_sweep, 'cron', minute=5)
        
        # 3. On boot, fetch weekly calendar immediately
        fetch_and_store_weekly_calendar()
        
        # 4. On boot, run an initial sweep to catch up on any missed data immediately
        hourly_realized_data_sweep()
        
        scheduler.start()
        logger.info("ForexFactory Calendar Agent is running...")
        
        try:
            # Keep the main thread alive
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            scheduler.shutdown()
            logger.info("Scheduler shutdown.")
