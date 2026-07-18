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
    Supports dual-scoring (direct vs rolled_up) and zero-article constituent decay.
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
        
        # 1. Determine constituents and initial weights
        constituents_map = {}
        core_entity = db["core_entities"].find_one({"ticker": ticker_clean})
        if core_entity and core_entity.get("is_etf", False):
            for c in core_entity.get("constituents", []):
                c_ticker = c.get("ticker", "").upper()
                if c_ticker:
                    constituents_map[c_ticker] = float(c.get("weight", 1.0))
        
        # 2. Query scored_articles matching this ticker in the 'tickers' array
        # Fallback to old 'ticker' field query for safety if migration missed any
        articles = list(scored_col.find({
            "$or": [{"tickers": ticker_clean}, {"ticker": ticker_clean}]
        }).sort("date", -1))
        
        direct_recent = []
        direct_prior = []
        
        const_recent_scores = {c: [] for c in constituents_map}
        const_prior_scores = {c: [] for c in constituents_map}
        
        for art in articles:
            score = float(art.get("sentiment_score", 0.0))
            # Determine primary ticker of the article
            primary = art.get("primary_ticker", art.get("ticker", "")).upper()
            
            pub_date_str = art.get("date", "")
            pub_dt = None
            if pub_date_str:
                try:
                    pub_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass
            
            hours_old = 0.0
            if pub_dt:
                hours_old = (now - pub_dt.replace(tzinfo=timezone.utc)).total_seconds() / 3600.0
            
            # Direct ETF News
            if primary == ticker_clean:
                if hours_old <= 24:
                    direct_recent.append(score)
                elif hours_old <= 72:
                    direct_prior.append(score)
            
            # Constituent News
            elif primary in constituents_map:
                if hours_old <= 24:
                    const_recent_scores[primary].append(score)
                elif hours_old <= 72:
                    const_prior_scores[primary].append(score)

        # 3. Compute Direct Score
        calc_direct_recent = sum(direct_recent) / len(direct_recent) if direct_recent else 0.0
        calc_direct_prior = sum(direct_prior) / len(direct_prior) if direct_prior else calc_direct_recent
        
        # 4. Compute Rolled-Up Score
        # Apply Zero-Article Decay: If a constituent has no recent articles, its weight is 0
        active_recent_weights = {}
        for c, scores in const_recent_scores.items():
            if scores: # Has articles <= 24h
                active_recent_weights[c] = constituents_map[c]
                
        # Normalize active recent weights
        total_recent_w = sum(active_recent_weights.values())
        if total_recent_w > 0:
            active_recent_weights = {k: v / total_recent_w for k, v in active_recent_weights.items()}
            
        rolled_up_recent = 0.0
        for c, scores in const_recent_scores.items():
            if c in active_recent_weights:
                avg_score = sum(scores) / len(scores)
                rolled_up_recent += avg_score * active_recent_weights[c]
                
        # Do the same for prior (<=72h)
        active_prior_weights = {}
        for c, scores in const_prior_scores.items():
            if scores:
                active_prior_weights[c] = constituents_map[c]
            elif const_recent_scores[c]: # Also include if they had recent
                active_prior_weights[c] = constituents_map[c]
                
        total_prior_w = sum(active_prior_weights.values())
        if total_prior_w > 0:
            active_prior_weights = {k: v / total_prior_w for k, v in active_prior_weights.items()}
            
        rolled_up_prior = 0.0
        for c in constituents_map:
            if c in active_prior_weights:
                # Combine prior + recent to find average for prior window
                all_prior = const_prior_scores[c] + const_recent_scores[c]
                if all_prior:
                    avg_score = sum(all_prior) / len(all_prior)
                    rolled_up_prior += avg_score * active_prior_weights[c]

        # 5. Check latest report from sentiment_reports for direct score override
        latest_report = reports_col.find_one({"ticker": ticker_clean}, sort=[("saved_at", -1)])
        final_direct = calc_direct_recent
        final_velocity = round(calc_direct_recent - calc_direct_prior, 4)
        
        if latest_report and "aggregate_score" in latest_report:
            rep_score = float(latest_report["aggregate_score"])
            if rep_score != 0.0 or latest_report.get("articles_count", 0) > 0:
                final_direct = round(rep_score, 4)
            if "velocity" in latest_report and latest_report["velocity"] != 0.0:
                final_velocity = float(latest_report["velocity"])
        else:
            final_direct = round(final_direct, 4)

        final_rolled_up = round(rolled_up_recent, 4) if constituents_map else final_direct

        # 6. Upsert into sentiment_leaderboard
        leaderboard_col.update_one(
            {"ticker": ticker_clean},
            {
                "$set": {
                    "scores": {
                        "direct": final_direct,
                        "rolled_up": final_rolled_up
                    },
                    "current_sentiment": final_rolled_up if constituents_map else final_direct,
                    "velocity": final_velocity,
                    "last_updated": now_iso
                },
                "$push": {
                    "history": {
                        "time": now_iso,
                        "scores": {
                            "direct": final_direct,
                            "rolled_up": final_rolled_up
                        }
                    }
                }
            },
            upsert=True
        )
        
        logger.info(f"Successfully aggregated leaderboard for {ticker_clean}: Direct={final_direct}, RolledUp={final_rolled_up}, Velocity={final_velocity}")
        return {
            "ticker": ticker_clean,
            "scores": {
                "direct": final_direct,
                "rolled_up": final_rolled_up
            },
            "velocity": final_velocity,
            "last_updated": now_iso,
            "status": "success"
        }
        
    except Exception as e:
        import traceback
        logger.error(f"Failed standalone leaderboard aggregation for {ticker}: {e}\n{traceback.format_exc()}")
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
