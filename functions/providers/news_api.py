import os
import requests
import pandas as pd

def fetch_news_api(symbol: str = "AAPL", limit: int = 100) -> pd.DataFrame:
    """
    Fetches news articles for a query or symbol from NewsAPI.org.
    
    Use this tool ONLY when you need to fetch general news articles containing a specific keyword or stock ticker using the NewsAPI search index.
    Do not use this for real-time order execution or raw webpage scraping.
    
    Args:
        symbol (str): The stock ticker or keyword to search news for (e.g., 'AAPL'). Defaults to 'AAPL'.
        limit (int): The maximum number of news articles to retrieve. Defaults to 100.
        
    Returns:
        pd.DataFrame: A pandas DataFrame containing news articles with columns: 'date', 'title', 'url', 'source', 'summary', 'text', 'provider'.
        
    Example:
        fetch_news_api(symbol="AAPL", limit=20)
    """
    key = os.getenv("NEWS_API_KEY")
    if not key:
        return pd.DataFrame()
    
    url = f"https://newsapi.org/v2/everything?q={symbol}&pageSize={limit}&apiKey={key}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        rows = [{
            "date": pd.to_datetime(item.get("publishedAt"), errors='coerce'),
            "title": item.get("title"),
            "url": item.get("url"),
            "source": item.get("source", {}).get("name"),
            "summary": item.get("description"),
            "text": item.get("content"),
            "provider": "news_api"
        } for item in data.get("articles", [])[:limit]]
        return pd.DataFrame(rows)
    except (requests.HTTPError, requests.RequestException, KeyError) as e:
        print(f"NewsAPI Error: {e}")
        return pd.DataFrame()
