import os
import sys
import hashlib
from datetime import datetime, timedelta
from typing import  Dict, Any
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.tools.prepare_articles import prepare_articles
from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.types.sentiment_state import SentimentState
from functions.utils.db.connect import get_db_client


# Helper to generate stable IDs for articles
def get_article_id(article: dict) -> str:
    unique_str = f"{article.get('title', '')}-{article.get('source', '')}-{article.get('published_at', '')}"
    return hashlib.sha256(unique_str.encode('utf-8')).hexdigest()


# 1. Ingestion Node: Fetches news articles, checks cache, applies timeframe & limit controls
def ingest_news_node(state: SentimentState, config: RunnableConfig, store: BaseStore) -> Dict[str, Any]:
    logger = get_pipeline_logger()
    ticker = state["ticker"]
    timeframe_days = state.get("timeframe_days", 30)
    limit = state.get("limit", 5)
    holdings = state.get("holdings", 5)
    
    logger.info(f"[ingest_news_node] Processing ticker: {ticker}, timeframe_days: {timeframe_days}, limit: {limit}")
    
    # Decompose if ETF
    from functions.tools.openbb import fetch_etf_holdings_from_openbb
    df_holdings = fetch_etf_holdings_from_openbb(ticker)
    
    is_etf = False
    constituents = []
    decomp_data = {"ticker": ticker, "is_etf": False, "constituents": []}
    
    if not df_holdings.empty:
        df_holdings = df_holdings.sort_values(by="fund_weight", ascending=False)
        candidate = df_holdings.to_dict(orient="records")
        candidate = [c for c in candidate if c.get("ticker") and str(c.get("ticker")).strip().upper() != ticker.upper()]
        if len(candidate) > 0:
            if holdings == "all":
                constituents = candidate
            else:
                try:
                    holdings_limit = int(holdings)
                    constituents = candidate[:holdings_limit]
                except (ValueError, TypeError):
                    constituents = candidate[:5]
            is_etf = True
            decomp_data = {
                "ticker": ticker,
                "is_etf": True,
                "error_flag": False,
                "constituents": [{"ticker": c["ticker"], "weight": float(c["fund_weight"])} for c in constituents]
            }

    # Timeframe threshold calculation
    threshold_date = datetime.utcnow() - timedelta(days=timeframe_days)
    
    # Query news
    from functions.aggregator.aggregator import fetch_aggregate_all_news
    tickers_to_query = [c["ticker"] for c in constituents] if is_etf else [ticker]
    
    client, db = get_db_client()
    scored_collection = db["scored_articles"]
    
    all_articles = []
    
    # We load database/calibration setup to get the embeddings database for prepare_articles few-shot semantic examples
    from functions.utils.news.ingest import setup_clients_and_embeddings
    # Use config paths or defaults
    config = config or {}
    env_path = config.get("configurable", {}).get("env_path", None)
    csv_path = config.get("configurable", {}).get("csv_path", None)
    db_vector, _, _, _, _, _, _ = setup_clients_and_embeddings(env_path=env_path, csv_path=csv_path)

    for symbol in tickers_to_query:
        try:
            df_news = fetch_aggregate_all_news(symbol=symbol, limit=100)
            if df_news.empty:
                continue
            
            # Convert to articles
            prepared = prepare_articles(df_news, db_vector, limit=100)
            for art in prepared:
                art["ticker"] = symbol
                
            # Filter by timeframe
            filtered = []
            for art in prepared:
                published_at_str = art.get("published_at", "")
                try:
                    # Try parsing standard formats
                    pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        pub_date = datetime.strptime(published_at_str, "%Y-%m-%d")
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(published_at_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pub_date = datetime.utcnow() # fallback to now if unparseable
                
                # Check timeframe threshold
                if pub_date.replace(tzinfo=None) >= threshold_date:
                    filtered.append(art)
                    
            # Sort descending by date
            filtered.sort(key=lambda x: x.get("published_at", ""), reverse=True)
            # Slice top N (limit) articles
            sliced = filtered[:limit]
            all_articles.extend(sliced)
            
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            
    if not all_articles:
        return {
            "is_etf": is_etf,
            "constituents": constituents,
            "decomp_data": decomp_data,
            "raw_article_ids": [],
            "scored_article_ids": [],
            "articles_payload": [],
            "error": "No news articles collected in timeframe."
        }

    raw_article_ids = []
    articles_payload = []
    
    for art in all_articles:
        art_id = get_article_id(art)
        raw_article_ids.append(art_id)
        
        # Save heavy raw article to the LangGraph Store
        store.put(
            namespace=("news", "raw"),
            key=art_id,
            value=art
        )
        articles_payload.append(art)
        
    return {
        "is_etf": is_etf,
        "constituents": constituents,
        "decomp_data": decomp_data,
        "raw_article_ids": raw_article_ids,
        "articles_payload": articles_payload
    }
