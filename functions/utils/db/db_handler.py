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

def save_sentiment_report(ticker: str, report: dict) -> str:
    """
    Saves full CIO SentimentReport objects into the 'sentiment_reports' MongoDB collection.
    """
    if not report or not isinstance(report, dict):
        return None
        
    try:
        client, db = get_db_client()
        reports_col = db["sentiment_reports"]
        
        now_iso = datetime.now(timezone.utc).isoformat()
        
        doc = {
            "ticker": ticker.upper(),
            "timestamp": report.get("metadata", {}).get("timestamp", now_iso),
            "aggregate_score": float(report.get("aggregate_score", 0.0)),
            "aggregate_label": report.get("aggregate_label", "Neutral"),
            "velocity": float(report.get("velocity", 0.0)),
            "reasoning": report.get("reasoning", ""),
            "warnings": report.get("warnings", []),
            "compliance_override": report.get("compliance_override"),
            "articles_count": len(report.get("articles", [])),
            "articles": report.get("articles", []),
            "saved_at": now_iso
        }
        
        res = reports_col.insert_one(doc)
        logger.info(f"Saved full sentiment report for {ticker} to 'sentiment_reports' (ID: {res.inserted_id}).")
        return str(res.inserted_id)
    except Exception as e:
        logger.error(f"Failed to save sentiment report for {ticker}: {e}")
        return None

def aggregate_leaderboard_for_ticker(ticker: str) -> dict:
    """
    Standalone aggregation engine that computes current sentiment score and intraday velocity
    for a given ticker or ETF using 'scored_articles' and 'sentiment_reports', and updates 'sentiment_leaderboard'.
    Can be run independently of LLMs.
    """
    ticker_clean = ticker.upper()
    logger.info(f"Running standalone leaderboard aggregation for {ticker_clean}...")
    try:
        client, db = get_db_client()
        scored_col = db["scored_articles"]
        reports_col = db["sentiment_reports"]
        leaderboard_col = db["sentiment_leaderboard"]
        
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        
        # 1. Determine tickers to query (Check if ETF with constituents)
        tickers_to_query = [ticker_clean]
        constituents_map = {}
        
        core_entity = db["core_entities"].find_one({"ticker": ticker_clean})
        if core_entity and core_entity.get("is_etf", False):
            for c in core_entity.get("constituents", []):
                c_ticker = c.get("ticker", "").upper()
                if c_ticker:
                    tickers_to_query.append(c_ticker)
                    constituents_map[c_ticker] = float(c.get("weight", 1.0))
        
        # Normalize constituent weights if available
        if constituents_map:
            total_w = sum(constituents_map.values())
            if total_w > 0:
                constituents_map = {k: v / total_w for k, v in constituents_map.items()}

        # 2. Query scored_articles for matching tickers
        articles = list(scored_col.find({"ticker": {"$in": tickers_to_query}}).sort("date", -1))
        
        # Calculate time-weighted sentiment from scored_articles
        recent_scores = []
        prior_scores = []
        
        for art in articles:
            score = float(art.get("sentiment_score", 0.0))
            art_ticker = art.get("ticker", "").upper()
            w_const = constituents_map.get(art_ticker, 1.0) if constituents_map else 1.0
            
            pub_date_str = art.get("date", "")
            pub_dt = None
            if pub_date_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
                    
            if pub_dt:
                hours_old = (now - pub_dt.replace(tzinfo=timezone.utc)).total_seconds() / 3600.0
                if hours_old <= 24:
                    recent_scores.append(score * w_const)
                elif hours_old <= 72:
                    prior_scores.append(score * w_const)
            else:
                recent_scores.append(score * w_const)
                
        calc_recent_avg = sum(recent_scores) / len(recent_scores) if recent_scores else 0.0
        calc_prior_avg = sum(prior_scores) / len(prior_scores) if prior_scores else calc_recent_avg
        
        # Calculate calculated velocity
        calc_velocity = round(calc_recent_avg - calc_prior_avg, 4)
        
        # 3. Check latest report from sentiment_reports
        latest_report = reports_col.find_one({"ticker": ticker_clean}, sort=[("saved_at", -1)])
        
        final_sentiment = calc_recent_avg
        final_velocity = calc_velocity
        
        if latest_report and "aggregate_score" in latest_report:
            rep_score = float(latest_report["aggregate_score"])
            # Prefer validated CIO Analyst aggregate_score if non-zero or articles exist
            if rep_score != 0.0 or latest_report.get("articles_count", 0) > 0:
                final_sentiment = round(rep_score, 4)
            if "velocity" in latest_report and latest_report["velocity"] != 0.0:
                final_velocity = float(latest_report["velocity"])
        else:
            final_sentiment = round(final_sentiment, 4)

        # 4. Upsert into sentiment_leaderboard
        leaderboard_col.update_one(
            {"ticker": ticker_clean},
            {
                "$set": {
                    "current_sentiment": final_sentiment,
                    "velocity": final_velocity,
                    "last_updated": now_iso
                },
                "$push": {
                    "history": {
                        "time": now_iso,
                        "score": final_sentiment
                    }
                }
            },
            upsert=True
        )
        
        logger.info(f"Successfully aggregated leaderboard for {ticker_clean}: Sentiment={final_sentiment}, Velocity={final_velocity}")
        return {
            "ticker": ticker_clean,
            "current_sentiment": final_sentiment,
            "velocity": final_velocity,
            "last_updated": now_iso,
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Failed standalone leaderboard aggregation for {ticker}: {e}")
        return {"ticker": ticker, "error": str(e), "status": "failed"}

def process_sentiment_state(ticker: str, state: dict):
    """
    Intercepts the LangGraph SentimentState, parses articles and report payload,
    persists full report to 'sentiment_reports', and invokes standalone leaderboard aggregation.
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
                headline = article.get("headline", article.get("title", "Unknown"))
                url = article.get("url", article.get("link", ""))
                
                sentiment_dict = article.get("sentiment", {})
                score = sentiment_dict.get("raw_sentiment", article.get("sentiment_score", 0.0))
                confidence = sentiment_dict.get("confidence_score", article.get("confidence", 0.0))
                reasoning = sentiment_dict.get("reasoning", "")
                
                doc = {
                    "ticker": ticker.upper(),
                    "headline": headline,
                    "url": url,
                    "score": score,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "ingested_at": datetime.now(timezone.utc).isoformat()
                }
                
                if url:
                    operations.append(UpdateOne(
                        {"url": url},
                        {"$set": doc},
                        upsert=True
                    ))
            
            if operations:
                articles_col.bulk_write(operations)
                logger.info(f"Upserted {len(operations)} articles for {ticker}.")

        # 2. Save full report if CIO Analysis results exist
        cio_analysis = state.get("results") or state.get("cio_analysis") or {}
        if isinstance(cio_analysis, dict) and ("aggregate_score" in cio_analysis or "reasoning" in cio_analysis):
            save_sentiment_report(ticker, cio_analysis)

        # 3. Run Standalone Leaderboard Aggregator
        aggregate_leaderboard_for_ticker(ticker)
        
    except Exception as e:
        logger.error(f"Failed to process sentiment state for {ticker} in DB Handler: {e}")
