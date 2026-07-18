import logging
from functions.utils.db.connect import get_db_client

logger = logging.getLogger(__name__)

def run_startup_migrations():
    """
    Runs schema migrations on startup.
    Currently handles migrating 'ticker' (str) to 'tickers' (list) in scored_articles,
    adding 'primary_ticker' mapping based on reverse index of core_entities.
    """
    logger.info("Running startup schema migrations...")
    try:
        client, db = get_db_client()
        scored_col = db["scored_articles"]
        core_col = db["core_entities"]
        
        # Build reverse index for tagging old articles
        # AAPL -> ["AAPL", "XLK", "QQQ"]
        reverse_index = {}
        for entity in core_col.find({}):
            etf_ticker = entity.get("ticker", "").upper()
            if not etf_ticker:
                continue
                
            if etf_ticker not in reverse_index:
                reverse_index[etf_ticker] = set([etf_ticker])
                
            if entity.get("is_etf", False):
                for const in entity.get("constituents", []):
                    c_ticker = const.get("ticker", "").upper()
                    if c_ticker:
                        if c_ticker not in reverse_index:
                            reverse_index[c_ticker] = set([c_ticker])
                        reverse_index[c_ticker].add(etf_ticker)
        
        # Find all documents that have the old 'ticker' field but no 'primary_ticker'
        old_docs = list(scored_col.find({"primary_ticker": {"$exists": False}, "ticker": {"$exists": True}}))
        
        if not old_docs:
            logger.info("No old scored_articles docs need migration.")
            return
            
        logger.info(f"Found {len(old_docs)} scored_articles docs to migrate...")
        
        from pymongo import UpdateOne
        operations = []
        for doc in old_docs:
            old_ticker = doc.get("ticker", "").upper()
            if not old_ticker:
                continue
                
            # Lookup parent ETFs
            mapped_tickers = list(reverse_index.get(old_ticker, [old_ticker]))
            
            operations.append(UpdateOne(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "primary_ticker": old_ticker,
                        "tickers": mapped_tickers
                    },
                    "$unset": {
                        "ticker": ""
                    }
                }
            ))
            
        if operations:
            # Execute in batches
            batch_size = 1000
            for i in range(0, len(operations), batch_size):
                batch = operations[i:i+batch_size]
                res = scored_col.bulk_write(batch, ordered=False)
                logger.info(f"Migrated batch of {len(batch)} scored_articles. Modified: {res.modified_count}")
                
        logger.info("Startup schema migrations completed.")
        
    except Exception as e:
        logger.error(f"Error during startup migrations: {e}")

if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    script_path = Path(__file__).resolve()
    project_root = next((p for p in script_path.parents if (p / "functions").exists()), script_path.parent.parent.parent.parent)
    sys.path.insert(0, str(project_root))

    env_path = project_root / ".env.local"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
        
    logging.basicConfig(level=logging.INFO)
    run_startup_migrations()
