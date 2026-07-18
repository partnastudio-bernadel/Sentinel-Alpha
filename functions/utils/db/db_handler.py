import os
import sys
import logging
from datetime import datetime, timezone
from pymongo import UpdateOne

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.dirname(os.path.dirname(os.path.dirname(script_dir)))
if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.db.connect import get_db_client

logger = logging.getLogger(__name__)

def process_sentiment_state(ticker: str, state: dict):
    """
    Intercepts the LangGraph SentimentState, parses the articles and the final leaderboard score,
    and upserts the data into MongoDB collections.
    """
    logger.info(f"Processing sentiment state for {ticker}...")
    try:
        client, db = get_db_client()
        
        # 1. Process Articles
        articles_col = db["articles"]
        articles_data = state.get("articles", [])
        if articles_data:
            operations = []
            for article in articles_data:
                # Basic schema alignment
                headline = article.get("headline", article.get("title", "Unknown"))
                url = article.get("url", article.get("link", ""))
                
                # Get nested sentiment if exists
                sentiment_dict = article.get("sentiment", {})
                score = sentiment_dict.get("raw_sentiment", article.get("sentiment_score", 0.0))
                confidence = sentiment_dict.get("confidence_score", article.get("confidence", 0.0))
                reasoning = sentiment_dict.get("reasoning", "")
                
                doc = {
                    "ticker": ticker,
                    "headline": headline,
                    "url": url,
                    "score": score,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                }
                
                # Use URL as unique identifier to avoid duplicates
                if url:
                    operations.append(UpdateOne(
                        {"url": url},
                        {"$set": doc},
                        upsert=True
                    ))
            
            if operations:
                articles_col.bulk_write(operations)
                logger.info(f"Upserted {len(operations)} articles for {ticker}.")

        # 2. Process Leaderboard Timeseries
        leaderboard_col = db["sentiment_leaderboard"]
        
        # Extract the final effective sentiment from the state (check 'results' first, then 'cio_analysis')
        cio_analysis = state.get("results") or state.get("cio_analysis") or {}
        if isinstance(cio_analysis, dict):
            final_score = cio_analysis.get("aggregate_score", cio_analysis.get("effective_sentiment", 0.0))
            velocity = cio_analysis.get("intraday_velocity", cio_analysis.get("velocity", 0.0))
        else:
            final_score = 0.0
            velocity = 0.0
            
        now_iso = datetime.now(timezone.utc).isoformat()
        
        leaderboard_col.update_one(
            {"ticker": ticker},
            {
                "$set": {
                    "current_sentiment": final_score,
                    "velocity": velocity,
                    "last_updated": now_iso
                },
                "$push": {
                    "history": {
                        "time": now_iso,
                        "score": final_score
                    }
                }
            },
            upsert=True
        )
        logger.info(f"Successfully updated leaderboard for {ticker}.")
        
    except Exception as e:
        logger.error(f"Failed to process sentiment state for {ticker} in DB Handler: {e}")
