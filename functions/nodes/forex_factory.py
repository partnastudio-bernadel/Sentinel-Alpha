import os
import sys
from typing import Dict, Any
from langchain_core.runnables import RunnableConfig

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.types.macro_state import MacroState
from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.utils.macro.scheduler import MacroScheduler
from functions.utils.macro.mcp_helper import async_query_forexfactory_mcp

# 1. Node: Forex Factory Scraper (Llama-3 model routing)
def forex_factory_node(state: MacroState, config: RunnableConfig) -> Dict[str, Any]:
    logger = get_pipeline_logger("macro")
    logger.info("[forex_factory_node] Fetching ForexFactory economic calendar...")
    
    scheduler = MacroScheduler()
    events = []
    
    try:
        events = scheduler.execute_with_guard(
            async_query_forexfactory_mcp,
            "ffcal_get_calendar_events",
            {"time_period": "this_month"},
            source="forexfactory"
        )
    except Exception as e:
        logger.error(f"Error fetching ForexFactory events: {e}")

    # Fallback 1: Query MongoDB macro_calendar if live scraper returned empty or failed
    if not events or (isinstance(events, dict) and events.get("status") == "error"):
        logger.warning("[forex_factory_node] Live scraper failed or returned empty. Querying cached events from MongoDB 'macro_calendar' collection...")
        try:
            from functions.utils.db.connect import get_db_client
            client, db = get_db_client()
            col = db["macro_calendar"]
            # Retrieve all USD events
            docs = list(col.find({"country": "USD"}))
            db_events = []
            for doc in docs:
                db_events.append({
                    "id": str(doc.get("_id", "")),
                    "title": doc.get("title", ""),
                    "currency": doc.get("country", "USD"),
                    "impact": doc.get("impact", "High"),
                    "datetime_utc": doc.get("date", ""),
                    "forecast": doc.get("forecast"),
                    "previous": doc.get("previous"),
                    "actual": doc.get("actual")
                })
            if db_events:
                logger.info(f"[forex_factory_node] Successfully loaded {len(db_events)} cached events from MongoDB.")
                events = db_events
        except Exception as db_e:
            logger.error(f"[-] Error querying macro_calendar backup: {db_e}")

    # 2. Resolve missing actual values via FRED first (prioritizing FRED over FXFactory for mapped events)
    if events and not isinstance(events, dict):
        try:
            from functions.utils.db.connect import get_db_client
            from functions.utils.macro.fred_helper import get_fred_actual
            client, db = get_db_client()
            
            event_name = config.get("configurable", {}).get("event_name")
            
            for e in events:
                actual = e.get("actual")
                if not actual or str(actual).strip() == "" or str(actual).lower() == "none":
                    title = e.get("title")
                    
                    # If targeting a specific event, skip other events to speed up processing
                    if event_name and title.strip().lower() != event_name.strip().lower():
                        continue
                        
                    fred_val = get_fred_actual(title, db)
                    if fred_val:
                        logger.info(f"[forex_factory_node] Resolved actual value for '{title}' via FRED: {fred_val}")
                        e["actual"] = fred_val
                        
                        # Update MongoDB macro_calendar cache
                        date_str = e.get("datetime_utc") or e.get("datetime_local")
                        query = {"title": title, "country": e.get("currency") or e.get("country") or "USD"}
                        if date_str:
                            query["date"] = {"$regex": f"^{date_str[:10]}"}
                        
                        db["macro_calendar"].update_one(
                            query,
                            {"$set": {"actual": fred_val, "status": "completed"}}
                        )
        except Exception as fred_e:
            logger.error(f"[forex_factory_node] Error running FRED resolution: {fred_e}")

    # Fallback 2: General fail-safe payload
    if not events:
        logger.warning("[forex_factory_node] Cache is empty. Generating scheduler fallback payload...")
        fallback = scheduler.build_fallback_payload("Economic Calendar", source="forexfactory")
        events = [fallback]

    return {"forex_events": events}
