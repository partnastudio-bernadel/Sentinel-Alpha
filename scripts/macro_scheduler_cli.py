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
    """Hourly sweep to process all pending events prioritizing FRED then falling back to MCP."""
    logger.info("Starting hourly sweep for realized data...")
    try:
        collection = get_db_collection()
        pending_events = list(collection.find({"status": "pending"}))
        
        if not pending_events:
            logger.info("No pending events to sweep.")
            return

        # Fetch the weekly JSON feed as a lightweight fallback
        events_json = []
        try:
            response = requests.get(FF_URL, headers=HEADERS)
            response.raise_for_status()
            events_json = response.json()
        except Exception as e:
            logger.warning(f"Could not fetch weekly JSON calendar feed: {e}")

        # Create lookup dictionary from JSON feed
        fetched_actuals = {}
        for event in events_json:
            if event.get("title") and event.get("date") and event.get("actual"):
                fetched_actuals[(event["title"], event["date"])] = event["actual"]

        # Cache reference to database connection for FRED mapping
        client, db = get_db_client()

        for p_event in pending_events:
            title = p_event["title"]
            date_str = p_event["date"]
            actual_val = None

            # 1. Prioritize FRED API for mapped events
            try:
                from functions.utils.macro.fred_helper import get_fred_actual
                actual_val = get_fred_actual(title, db)
                if actual_val:
                    logger.info(f"Successfully swept realized data (via FRED) for {title}: {actual_val}")
            except Exception as fred_err:
                logger.error(f"FRED query failed for {title}: {fred_err}")

            # 2. Fallback to weekly JSON calendar feed
            if not actual_val:
                actual_val = fetched_actuals.get((title, date_str))
                if actual_val:
                    logger.info(f"Successfully swept realized data (via JSON feed) for {title}: {actual_val}")

            # 3. Fallback to ForexFactory MCP Server
            if not actual_val:
                try:
                    import asyncio
                    from functions.utils.macro.mcp_helper import async_query_forexfactory_mcp
                    from dateutil import parser
                    
                    logger.info(f"Checking ForexFactory MCP fallback for '{title}'...")
                    scraped_events = asyncio.run(async_query_forexfactory_mcp(
                        "ffcal_get_calendar_events",
                        {"time_period": "this_week"}
                    ))
                    
                    if isinstance(scraped_events, list):
                        p_title_clean = title.strip().lower()
                        p_date = parser.isoparse(date_str)
                        for s_event in scraped_events:
                            s_title = s_event.get("title", "").strip().lower()
                            s_actual = s_event.get("actual")
                            if s_actual and str(s_actual).strip() != "" and str(s_actual).lower() != "none":
                                if p_title_clean == s_title or p_title_clean in s_title or s_title in p_title_clean:
                                    s_date_str = s_event.get("datetime_utc") or s_event.get("datetime_local")
                                    if s_date_str:
                                        s_date = parser.isoparse(s_date_str)
                                        if abs((p_date - s_date).total_seconds()) < 7200: # within 2 hours
                                            actual_val = s_actual
                                            logger.info(f"Successfully swept realized data (via ForexFactory MCP) for {title}: {actual_val}")
                                            break
                except Exception as mcp_err:
                    logger.warning(f"ForexFactory MCP fallback failed for '{title}': {mcp_err}")

            # If we found an actual value, update DB and trigger downstream processing
            if actual_val:
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
            else:
                logger.info(f"No actual value found yet for pending event: {title}")

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
