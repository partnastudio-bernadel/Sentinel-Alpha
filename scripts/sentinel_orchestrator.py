import os
import sys
import asyncio
import argparse
import logging
from dotenv import load_dotenv

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(script_dir)
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

# Load environment variables before any other imports that may need them
_env_path = os.path.join(sentiment_dir, ".env.local")
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path)
else:
    load_dotenv()

from functions.utils.db.connect import get_db_client
from functions.utils.db.db_handler import process_sentiment_state
from functions.graphs.sentiment_graph import build_sentiment_graph

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Strict API rate limit defense (Max 3 concurrent graphs to avoid 429 Too Many Requests)
MAX_CONCURRENT_TASKS = 2

async def run_pipeline_for_ticker(ticker: str, semaphore: asyncio.Semaphore):
    """Executes the LangGraph sentiment pipeline for a single ticker."""
    async with semaphore:
        logger.info(f"Starting pipeline for {ticker}...")
        try:
            # Fetch the ticker's beta from beta_matrix collection
            client, db = get_db_client()
            beta_doc = db["beta_matrix"].find_one({"ticker": ticker})
            etf_macro_beta = beta_doc.get("inflation_rate_beta", 1.0) if beta_doc else 1.0
            
            # Fetch the current Macro Shock St from macro_calendar collection
            # We sort by last_updated to get the most recent macro event shock
            macro_doc = db["macro_calendar"].find_one({}, sort=[("last_updated", -1)])
            macro_shock = macro_doc.get("shock_index", 0.0) if macro_doc else 0.0
            
            initial_state = {
                "ticker": ticker,
                "articles": [],
                "cio_analysis": {},
                "holdings": "all",
                "macro_shock": macro_shock,
                "etf_macro_beta": etf_macro_beta
            }
            
            app = build_sentiment_graph()
            
            # Execute graph asynchronously using run_in_executor to not block the event loop
            final_state = await asyncio.to_thread(app.invoke, initial_state)
            
            process_sentiment_state(ticker, final_state)
            logger.info(f"Pipeline completed successfully for {ticker}.")
            
        except Exception as e:
            logger.error(f"Pipeline failed for {ticker}: {e}")

async def run_background_loop():
    """Runs the 12 Core ETFs from MongoDB in a managed concurrency queue."""
    logger.info("Initializing Background Loop Orchestrator...")
    client, db = get_db_client()
    core_entities = list(db["core_entities"].find({}))
    
    if not core_entities:
        logger.warning("No core entities found in MongoDB. Please run seed_etf_collection.py.")
        return
        
    tickers = [doc.get("ticker") for doc in core_entities if doc.get("ticker")]
    logger.info(f"Loaded {len(tickers)} core entities. Starting batch processing...")
    
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
    tasks = [run_pipeline_for_ticker(t, semaphore) for t in tickers]
    
    await asyncio.gather(*tasks)
    logger.info("Background loop batch processing complete.")

def main():
    parser = argparse.ArgumentParser(description="Sentinel Orchestrator: Unifies Macro and Sentiment Agents.")
    parser.add_argument("--ticker", type=str, help="Run on-demand for a specific ticker.")
    parser.add_argument("--background", action="store_true", help="Run the hourly loop for all Core ETFs.")
    args = parser.parse_args()
    
    if args.ticker:
        logger.info(f"Running ON-DEMAND mode for {args.ticker}...")
        semaphore = asyncio.Semaphore(1)
        asyncio.run(run_pipeline_for_ticker(args.ticker.upper(), semaphore))
        
    elif args.background:
        logger.info("Running BACKGROUND mode for all Core ETFs...")
        asyncio.run(run_background_loop())
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
