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
    logger = get_pipeline_logger()
    logger.info("[forex_factory_node] Fetching ForexFactory economic calendar...")
    
    scheduler = MacroScheduler()
    
    try:
        events = scheduler.execute_with_guard(
            async_query_forexfactory_mcp,
            "ffcal_get_calendar_events",
            {"time_period": "this_month"},
            source="forexfactory"
        )
        return {"forex_events": events}
    except Exception as e:
        logger.error(f"Error fetching ForexFactory events: {e}")
        fallback = scheduler.build_fallback_payload("Economic Calendar", source="forexfactory")
        return {"forex_events": [fallback]}
