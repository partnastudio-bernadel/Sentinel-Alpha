from typing import TypedDict, List, Dict, Any, Optional

# Define the sentiment graph state
class SentimentState(TypedDict):
    ticker: str
    timeframe_days: int
    limit: int
    holdings: int
    force_rescore: bool
    cache_buster: Optional[float]
    
    # Store references/pointers to articles and documents rather than bloating the state
    raw_article_ids: List[str]
    scored_article_ids: List[str]
    
    # Mathematical and calculation payloads
    is_etf: bool
    constituents: List[Dict[str, Any]]
    decomp_data: Dict[str, Any]
    
    # In-memory execution artifacts (kept lightweight)
    articles_payload: List[Dict[str, Any]]
    results: Dict[str, Any]
    error: Optional[str]
