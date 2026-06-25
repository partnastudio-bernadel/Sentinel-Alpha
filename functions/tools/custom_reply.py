import json

def extract_json_array(text):
    """Extracts a JSON list or dict from a string, supporting markdown wraps."""
    if not text:
        return None
    text_stripped = text.strip()
    try:
        return json.loads(text_stripped)
    except Exception:
        pass
    
    # Try finding bounding brackets
    start_list = text.find('[')
    end_list = text.rfind(']')
    start_dict = text.find('{')
    end_dict = text.rfind('}')
    
    # Pick whichever JSON bounding box is outermost
    start = -1
    end = -1
    if start_list != -1 and end_list != -1:
        start = start_list
        end = end_list
    if start_dict != -1 and end_dict != -1:
        if start == -1 or start_dict < start:
            start = start_dict
            end = end_dict
            
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start:end+1])
        except Exception:
            pass
            
    return None

def merge_scored_results(batch_results):
    """Merges multiple scored batch responses from the Scorer Agent.
    
    Supports merging both list-of-ticker-dicts and single-ticker-dict output structures.
    """
    merged_map = {}
    for result in batch_results:
        items = []
        if isinstance(result, dict):
            items = [result]
        elif isinstance(result, list):
            items = result
        else:
            continue
            
        for item in items:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if not ticker:
                continue
            
            articles = item.get("articles", [])
            if not isinstance(articles, list):
                articles = []
                
            if ticker not in merged_map:
                merged_map[ticker] = {
                    "ticker": ticker,
                    "metadata": {
                        "timestamp": item.get("metadata", {}).get("timestamp", ""),
                        "article_count": 0
                    },
                    "articles": []
                }
            
            merged_map[ticker]["articles"].extend(articles)
            
    for ticker, entry in merged_map.items():
        entry["metadata"]["article_count"] = len(entry["articles"])
        
    if len(merged_map) == 1:
        return list(merged_map.values())[0]
    return list(merged_map.values())
