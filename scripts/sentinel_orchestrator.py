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
LOCK_FILE = os.path.join(sentiment_dir, "logs", "sentinel_orchestrator.lock")

def acquire_lock() -> bool:
    """Acquires a lock for the background loop using a PID file.
    Cleans up stale lock files if the process is no longer running.
    """
    try:
        # Ensure logs directory exists
        os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
        
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                pid_str = f.read().strip()
            if pid_str:
                try:
                    pid = int(pid_str)
                    # Check if the process is actually running
                    os.kill(pid, 0)
                    # Process is still running, lock is active
                    return False
                except (ValueError, OSError):
                    # Process is dead or invalid PID, safe to clean up stale lock
                    logger.info("Found stale lock file. Cleaning it up.")
                    pass
        
        # Write current PID to lock file
        with open(LOCK_FILE, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        logger.error(f"Error acquiring lock: {e}")
        return False

def release_lock():
    """Releases the lock by removing the lock file."""
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
            logger.info("Lock file released successfully.")
    except Exception as e:
        logger.error(f"Error releasing lock: {e}")

def enqueue_tickers(tickers: list):
    """Enqueues tickers into the MongoDB orchestrator_queue collection.
    If a ticker is already pending or processing, it keeps its state.
    """
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        
        from pymongo import UpdateOne
        operations = []
        for ticker in tickers:
            operations.append(UpdateOne(
                {"_id": ticker},
                {
                    "$setOnInsert": {
                        "ticker": ticker,
                        "status": "pending",
                        "added_at": now_iso,
                        "started_at": None,
                        "finished_at": None,
                        "error": None
                    }
                },
                upsert=True
            ))
            
        if operations:
            result = queue_col.bulk_write(operations)
            logger.info(f"Enqueued {len(tickers)} tickers. Upserted: {result.upserted_count}, Modified: {result.modified_count}")
    except Exception as e:
        logger.error(f"Error enqueuing tickers: {e}")

def get_next_pending_tickers(limit: int) -> list:
    """Retrieves next batch of pending tickers from MongoDB queue."""
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        docs = list(queue_col.find({"status": "pending"}).limit(limit))
        return [doc["ticker"] for doc in docs]
    except Exception as e:
        logger.error(f"Error fetching pending tickers: {e}")
        return []

def update_queue_status(ticker: str, status: str, error_msg: str = None):
    """Updates the status and timestamps for a ticker in the queue."""
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        
        update_doc = {"status": status}
        if status == "processing":
            update_doc["started_at"] = now_iso
            update_doc["finished_at"] = None
            update_doc["error"] = None
        elif status in ["completed", "failed"]:
            update_doc["finished_at"] = now_iso
            if error_msg:
                update_doc["error"] = error_msg
                
        queue_col.update_one({"_id": ticker}, {"$set": update_doc}, upsert=True)
    except Exception as e:
        logger.error(f"Error updating queue status for {ticker}: {e}")

def reset_stale_jobs():
    """Resets any jobs stuck in 'processing' status to 'pending' on startup."""
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        result = queue_col.update_many(
            {"status": "processing"},
            {"$set": {
                "status": "pending",
                "error": "Resetting stale job from crashed instance"
            }}
        )
        if result.modified_count > 0:
            logger.info(f"Reset {result.modified_count} stale 'processing' jobs back to 'pending'.")
    except Exception as e:
        logger.error(f"Error resetting stale jobs: {e}")

async def run_pipeline_for_ticker(ticker: str, semaphore: asyncio.Semaphore):
    """Executes the LangGraph sentiment pipeline for a single ticker."""
    async with semaphore:
        logger.info(f"Starting pipeline for {ticker}...")
        update_queue_status(ticker, "processing")
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
                "limit": 25,
                "timeframe_days": 7,
                "macro_shock": macro_shock,
                "etf_macro_beta": etf_macro_beta
            }
            
            app = build_sentiment_graph()
            
            # MongoDBSaver checkpointer requires a thread_id in configurable
            import uuid
            run_config = {"configurable": {"thread_id": str(uuid.uuid4())}}
            
            # Execute graph asynchronously using run_in_executor to not block the event loop
            final_state = await asyncio.to_thread(app.invoke, initial_state, run_config)
            
            process_sentiment_state(ticker, final_state)
            logger.info(f"Pipeline completed successfully for {ticker}.")
            update_queue_status(ticker, "completed")
            
        except Exception as e:
            logger.error(f"Pipeline failed for {ticker}: {e}")
            update_queue_status(ticker, "failed", str(e))

async def run_background_loop():
    """Runs the 12 Core ETFs from MongoDB in a managed concurrency queue."""
    logger.info("Initializing Background Loop Orchestrator...")
    client, db = get_db_client()
    core_entities = list(db["core_entities"].find({}))
    
    if not core_entities:
        logger.warning("No core entities found in MongoDB. Please run seed_etf_collection.py.")
        return
        
    tickers = [doc.get("ticker") for doc in core_entities if doc.get("ticker")]
    logger.info(f"Loaded {len(tickers)} core entities from MongoDB.")
    
    # 1. Enqueue all core tickers (if not already pending/processing)
    enqueue_tickers(tickers)
    
    # 2. Try to acquire lock. If we can't, another instance is running, so we exit.
    if not acquire_lock():
        logger.info("Another background orchestrator worker is currently running. Enqueued tickers and exiting.")
        return
        
    try:
        # Reset any jobs that were left in 'processing' by a crashed worker
        reset_stale_jobs()
        
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        
        while True:
            # Fetch next batch of pending tickers from queue
            pending_tickers = get_next_pending_tickers(MAX_CONCURRENT_TASKS)
            if not pending_tickers:
                logger.info("No more pending tickers in the queue.")
                break
                
            logger.info(f"Worker picked up pending tickers for execution: {pending_tickers}")
            
            # Process this batch concurrently
            tasks = [run_pipeline_for_ticker(t, semaphore) for t in pending_tickers]
            await asyncio.gather(*tasks)
            
        logger.info("Background loop queue processing complete.")
    finally:
        release_lock()

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
