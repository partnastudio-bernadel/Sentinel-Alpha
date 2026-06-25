import os
import sys
from typing import Dict, Any

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.types.sentiment_state import SentimentState
from functions.utils.db.connect import get_db_client
from functions.nodes.ingest_news import get_article_id

# Check cache node: Checks MongoDB for pre-scored articles
def check_cache_node(state: SentimentState) -> Dict[str, Any]:
    logger = get_pipeline_logger()
    client, db = get_db_client()
    scored_collection = db["scored_articles"]
    
    articles_payload = state.get("articles_payload", [])
    
    uncached_articles = []
    scored_article_ids = []
    scored_results = []
    
    for art in articles_payload:
        art_id = get_article_id(art)
        cached_score = scored_collection.find_one({"_id": art_id})
        
        if cached_score:
            logger.info(
                f"[SCORER CACHE HIT] Article found in cache: {art.get('title')}. "
                f"Sentiment: {cached_score.get('sentiment_label', 'Neutral')} "
                f"(Score: {float(cached_score.get('sentiment_score', 0.0)):.2f})"
            )
            scored_article_ids.append(art_id)
            scored_results.append(cached_score)
        else:
            logger.info(f"[SCORER CACHE MISS] Article not found in cache: {art.get('title')}")
            uncached_articles.append(art)
            
    return {
        "articles_payload": uncached_articles, # ONLY pass uncached articles to scoring node
        "scored_article_ids": scored_article_ids,
        "results": {"cached_scores": scored_results}
    }
