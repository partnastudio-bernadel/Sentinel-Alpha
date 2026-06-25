import os
import requests
import pandas as pd

def fetch_alpha_vantage(symbol: str = "AAPL", limit: int = 100) -> pd.DataFrame:
    """
    Fetches stock market news articles and sentiment data from the Alpha Vantage News & Sentiment API.
    
    Use this tool ONLY when you need to fetch news or sentiment data for a specific stock ticker using the Alpha Vantage API provider.
    Do not use this for general web search or scraping raw HTML articles.
    
    Args:
        symbol (str): The stock ticker symbol to fetch news for (e.g., 'AAPL'). Defaults to 'AAPL'.
        limit (int): The maximum number of news articles to retrieve. Defaults to 100.
        
    Returns:
        pd.DataFrame: A pandas DataFrame containing news articles with columns: 'date', 'title', 'url', 'source', 'summary', 'text', 'provider'.
        
    Example:
        fetch_alpha_vantage(symbol="AAPL", limit=10)
    """
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return pd.DataFrame()
    
    url = f"https://www.alphavantage.co/query?function=NEWS_SENTIMENT&tickers={symbol}&limit={limit}&apikey={key}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        feed = data.get("feed", [])
        rows = [{
            "date": pd.to_datetime(item.get("time_published"), format="%Y%m%dT%H%M%S", errors='coerce'),
            "title": item.get("title"),
            "url": item.get("url"),
            "source": item.get("source"),
            "summary": item.get("summary"),
            "text": None,
            "provider": "alpha-vantage"
        } for item in feed[:limit]]
        return pd.DataFrame(rows)
    except (requests.HTTPError, requests.RequestException, KeyError, ValueError) as e:
        print(f"Alpha Vantage Error: {e}")
        return pd.DataFrame()
