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
    url = article.get('url', article.get('link', ''))
    if url:
        return hashlib.sha256(url.encode('utf-8')).hexdigest()
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
    
    # Decompose if ETF - Query MongoDB core_entities collection as primary source of truth
    client, db = get_db_client()
    core_entity = db["core_entities"].find_one({"ticker": ticker.upper()})
    
    is_etf = False
    constituents = []
    decomp_data = {"ticker": ticker, "is_etf": False, "constituents": []}
    
    candidate = []
    if core_entity and core_entity.get("is_etf", False):
        candidate = core_entity.get("constituents", [])
    
    # Fallback to OpenBB if core_entities didn't have constituents
    if not candidate:
        try:
            from functions.tools.openbb import fetch_etf_holdings_from_openbb
            df_holdings = fetch_etf_holdings_from_openbb(ticker)
            if not df_holdings.empty:
                df_holdings = df_holdings.sort_values(by="fund_weight", ascending=False)
                candidate = df_holdings.to_dict(orient="records")
        except Exception as ex:
            logger.warning(f"OpenBB holdings fallback failed for {ticker}: {ex}")
            
    if candidate:
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
                "constituents": [{"ticker": c["ticker"], "weight": float(c.get("weight", c.get("fund_weight", 0.0)))} for c in constituents]
            }
            logger.info(f"[ingest_news_node] Decomposed ETF {ticker}: {len(constituents)} constituents resolved: {[c['ticker'] for c in constituents[:5]]}...")

    # Timeframe threshold calculation
    threshold_date = datetime.utcnow() - timedelta(days=timeframe_days)
    
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

    import concurrent.futures
    from functions.aggregator.aggregator import fetch_aggregate_all_news
    from functions.providers.google_news import fetch_google_news_rss

    fetch_tasks = []
    
    # Define fetcher helper
    def fetch_news_wrapper(symbol, is_top_level):
        try:
            if is_top_level:
                df = fetch_aggregate_all_news(symbol=symbol, limit=limit)
            else:
                df = fetch_google_news_rss(symbol=symbol, limit=limit)
                
            if df.empty:
                return symbol, []
                
            # For google news, ensure 'date' is present, use publish_date or similar
            if 'date' in df.columns:
                df['published_at'] = df['date']
                
            # Convert to articles
            prepared = prepare_articles(df, db_vector, limit=limit)
            
            # Filter by timeframe
            filtered = []
            for art in prepared:
                published_at_str = art.get("published_at", "")
                try:
                    pub_date = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        pub_date = datetime.strptime(published_at_str, "%Y-%m-%d")
                    except ValueError:
                        try:
                            pub_date = datetime.strptime(published_at_str, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            pub_date = datetime.utcnow()
                
                if pub_date.replace(tzinfo=None) >= threshold_date:
                    filtered.append(art)
                    
            filtered.sort(key=lambda x: x.get("published_at", ""), reverse=True)
            return symbol, filtered[:limit]
        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            return symbol, []

    # Submit tasks
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        # ETF top-level news
        fetch_tasks.append(executor.submit(fetch_news_wrapper, ticker, True))
        # Constituent news via Google RSS
        if is_etf:
            for c in constituents:
                fetch_tasks.append(executor.submit(fetch_news_wrapper, c["ticker"], False))
                
        for fut in concurrent.futures.as_completed(fetch_tasks):
            symbol, articles = fut.result()
            
            for art in articles:
                art_id = get_article_id(art)
                
                # Pre-Scoring Deduplication Check
                existing_doc = scored_collection.find_one({"_id": art_id})
                if existing_doc:
                    # Append ticker if not already in tickers array
                    if ticker not in existing_doc.get("tickers", []):
                        scored_collection.update_one(
                            {"_id": art_id},
                            {"$addToSet": {"tickers": ticker}}
                        )
                    # Skip adding to all_articles to avoid re-scoring
                    continue
                    
                # Setup primary_ticker and tickers array for new articles
                art["primary_ticker"] = symbol
                # Ensure ETF ticker is also included in tickers array
                art["tickers"] = list(set([symbol, ticker]))
                all_articles.append(art)

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
