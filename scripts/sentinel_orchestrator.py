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
from functions.utils.db.db_handler import process_sentiment_state, aggregate_leaderboard_for_ticker
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
    Assigns priority=2 to broad composite indices like SPY so they run last.
    """
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        
        from pymongo import UpdateOne
        operations = []
        for ticker in tickers:
            priority = 2 if ticker.upper() == "SPY" else 1
            operations.append(UpdateOne(
                {"_id": ticker},
                {
                    "$setOnInsert": {
                        "ticker": ticker,
                        "status": "pending",
                        "priority": priority,
                        "added_at": now_iso,
                        "started_at": None,
                        "finished_at": None,
                        "error": None
                    },
                    "$set": {
                        "priority": priority
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
    """Retrieves next batch of pending tickers from MongoDB queue sorted by priority (SPY run last)."""
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        # Sort by priority ASC (Priority 1 = Sectors/QQQ first, Priority 2 = SPY last) and added_at ASC
        docs = list(queue_col.find({"status": "pending"}).sort([("priority", 1), ("added_at", 1)]).limit(limit))
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
    """Resets any jobs stuck in 'processing' or 'failed' status to 'pending' on startup."""
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        result = queue_col.update_many(
            {"status": {"$in": ["processing", "failed"]}},
            {"$set": {
                "status": "pending",
                "error": "Resetting stale/failed job on startup for retry"
            }}
        )
        if result.modified_count > 0:
            logger.info(f"Reset {result.modified_count} stale or failed jobs back to 'pending'.")
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
                "timeframe_days": 1,
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
            logger.error(f"Pipeline LLM run failed for {ticker}: {e}. Running fallback standalone aggregation...")
            try:
                aggregate_leaderboard_for_ticker(ticker)
            except Exception as agg_err:
                logger.error(f"Fallback aggregation also failed for {ticker}: {agg_err}")
            update_queue_status(ticker, "failed", str(e))

def requeue_due_tickers(tickers: list, max_age_seconds: int = 3600):
    """Enqueues new tickers and resets completed/failed tickers whose finished_at is older than max_age_seconds back to pending."""
    try:
        client, db = get_db_client()
        queue_col = db["orchestrator_queue"]
        
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        cutoff_iso = (now - timedelta(seconds=max_age_seconds)).isoformat()
        
        # 1. Upsert missing tickers as pending
        enqueue_tickers(tickers)
        
        # 2. Reset completed/failed tickers whose finished_at is older than max_age_seconds back to pending
        result = queue_col.update_many(
            {
                "ticker": {"$in": tickers},
                "status": {"$in": ["completed", "failed"]},
                "$or": [
                    {"finished_at": {"$lt": cutoff_iso}},
                    {"finished_at": None}
                ]
            },
            {
                "$set": {
                    "status": "pending",
                    "added_at": now.isoformat(),
                    "started_at": None,
                    "finished_at": None,
                    "error": None
                }
            }
        )
        if result.modified_count > 0:
            logger.info(f"Re-enqueued {result.modified_count} tickers due for hourly sentiment run.")
    except Exception as e:
        logger.error(f"Error requeuing due tickers: {e}")

async def run_background_loop(interval: int = 60):
    """Runs the Core ETFs from MongoDB in a continuous daemon loop with managed concurrency."""
    logger.info("Initializing Continuous Background Loop Orchestrator...")
    
    # Try to acquire lock. If we can't, another instance is running, so we exit.
    if not acquire_lock():
        logger.info("Another background orchestrator worker is currently running. Exiting.")
        return
        
    try:
        # Run startup database schema migrations
        try:
            from functions.utils.db.migrations import run_startup_migrations
            run_startup_migrations()
        except ImportError as ie:
            logger.error(f"Could not import startup migrations: {ie}")
            
        # Reset any jobs that were left in 'processing' or 'failed' by previous runs
        reset_stale_jobs()
        
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        
        while True:
            client, db = get_db_client()
            core_entities = list(db["core_entities"].find({}))
            
            if core_entities:
                tickers = [doc.get("ticker") for doc in core_entities if doc.get("ticker")]
                requeue_due_tickers(tickers, max_age_seconds=3600)
            
            pending_tickers = get_next_pending_tickers(MAX_CONCURRENT_TASKS)
            
            if pending_tickers:
                logger.info(f"Worker picked up pending tickers for execution: {pending_tickers}")
                tasks = [run_pipeline_for_ticker(t, semaphore) for t in pending_tickers]
                await asyncio.gather(*tasks)
            else:
                logger.info(f"No pending tickers due. Sleeping for {interval}s before next check...")
                await asyncio.sleep(interval)
                
    except asyncio.CancelledError:
        logger.info("Orchestrator background loop cancelled.")
    except Exception as e:
        logger.error(f"Unexpected error in background loop: {e}")
    finally:
        release_lock()

def main():
    parser = argparse.ArgumentParser(description="Sentinel Orchestrator: Unifies Macro and Sentiment Agents.")
    parser.add_argument("--ticker", type=str, help="Run on-demand for a specific ticker.")
    parser.add_argument("--background", action="store_true", help="Run continuously in background daemon mode for all Core ETFs.")
    parser.add_argument("--aggregate", action="store_true", help="Run standalone sentiment leaderboard aggregation across all tickers without calling LLMs.")
    parser.add_argument("--interval", type=int, default=60, help="Sleep interval in seconds when queue is empty in background mode (default: 60).")
    args = parser.parse_args()
    
    if args.ticker:
        logger.info(f"Running ON-DEMAND mode for {args.ticker}...")
        semaphore = asyncio.Semaphore(1)
        asyncio.run(run_pipeline_for_ticker(args.ticker.upper(), semaphore))
        
    elif args.aggregate:
        logger.info("Running STANDALONE LEADERBOARD AGGREGATION for all core tickers...")
        client, db = get_db_client()
        core_entities = list(db["core_entities"].find({}))
        tickers = [doc.get("ticker") for doc in core_entities if doc.get("ticker")]
        if not tickers:
            tickers = ["XLK", "QQQ", "XLF", "XLE", "XLY", "XLP", "XLU", "XLV", "XLI", "XLB", "XLRE", "XLC", "SPY"]
        else:
            # Sort SPY to the very end
            tickers = sorted(tickers, key=lambda t: 2 if t.upper() == "SPY" else 1)
        
        for t in tickers:
            res = aggregate_leaderboard_for_ticker(t)
            logger.info(f"Aggregated {t}: {res}")
            
    elif args.background:
        logger.info("Running CONTINUOUS BACKGROUND mode for all Core ETFs...")
        asyncio.run(run_background_loop(interval=args.interval))
        
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
