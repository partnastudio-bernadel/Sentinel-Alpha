import os
import requests
import pandas as pd

def fetch_seeking_alpha_rapidapi(symbol: str = "AAPL", limit: int = 100) -> pd.DataFrame:
    """
    Fetches stock news for a specific symbol using Seeking Alpha RapidAPI wrapper endpoint.
    
    Use this tool ONLY when you need to fetch Seeking Alpha news items for a specific ticker symbol.
    Do not use this for general macro news or other API providers.
    
    Args:
        symbol (str): The stock ticker symbol to fetch news for (e.g., 'AAPL'). Defaults to 'AAPL'.
        limit (int): The maximum number of news articles to retrieve. Defaults to 100.
        
    Returns:
        pd.DataFrame: A pandas DataFrame containing news articles with columns: 'date', 'title', 'url', 'source', 'summary', 'text', 'provider'.
        
    Example:
        fetch_seeking_alpha_rapidapi(symbol="AAPL", limit=10)
    """
    key = os.getenv("RAPIDAPI_KEY")
    if not key:
        return pd.DataFrame()
    
    url = "https://seeking-alpha-api.p.rapidapi.com/news/v2/list-by-symbol"
    headers = {
        "x-rapidapi-host": "seeking-alpha-api.p.rapidapi.com",
        "x-rapidapi-key": key
    }
    try:
        response = requests.get(url, headers=headers, params={"symbol": symbol, "size": str(limit)}, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        feed = data.get("data", [])
        rows = []
        for item in feed[:limit]:
            attrs = item.get("attributes", {})
            slug = attrs.get("slug")
            rows.append({
                "date": pd.to_datetime(attrs.get("publishOn"), errors='coerce'),
                "title": attrs.get("title"),
                "url": f"https://seekingalpha.com/news/{item.get('id')}-{slug}" if slug else f"https://seekingalpha.com/news/{item.get('id')}",
                "source": "Seeking Alpha",
                "summary": attrs.get("summary"),
                "text": None,
                "provider": "seeking-alpha"
            })
        return pd.DataFrame(rows)
    except (requests.HTTPError, requests.RequestException, KeyError) as e:
        print(f"Seeking Alpha Error: {e}")
        return pd.DataFrame()
