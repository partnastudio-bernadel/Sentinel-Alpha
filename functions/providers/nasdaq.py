import requests
import pandas as pd

def fetch_nasdaq_api(symbol: str = "AAPL", limit: int = 100) -> pd.DataFrame:
    """
    Fetches news articles for a specific stock ticker using Nasdaq's public website web API.
    
    Use this tool ONLY when you need to fetch public market news articles published or aggregated directly by Nasdaq.
    Do not use this for general sentiment scores, or to scrape full-text articles.
    
    Args:
        symbol (str): The stock ticker symbol to fetch news for (e.g., 'AAPL'). Defaults to 'AAPL'.
        limit (int): The maximum number of news articles to retrieve. Defaults to 100.
        
    Returns:
        pd.DataFrame: A pandas DataFrame containing news articles with columns: 'date', 'title', 'url', 'source', 'summary', 'text', 'provider'.
        
    Example:
        fetch_nasdaq_api(symbol="AAPL", limit=15)
    """
    url = f"https://api.nasdaq.com/api/news/topic/articlebysymbol?symbol={symbol}&limit={limit}"
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://www.nasdaq.com',
        'Referer': 'https://www.nasdaq.com/'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        rows_data = data.get("data", {}).get("rows", [])
        rows = []
        for item in rows_data[:limit]:
            article_url = item.get("url")
            if article_url and not article_url.startswith("http"):
                article_url = "https://www.nasdaq.com" + article_url
            rows.append({
                "date": pd.to_datetime(item.get("created"), errors='coerce'),
                "title": item.get("title"),
                "url": article_url,
                "source": item.get("publisher", "Nasdaq"),
                "summary": item.get("description"),
                "text": None,
                "provider": "nasdaq"
            })
        return pd.DataFrame(rows)
    except (requests.HTTPError, requests.RequestException, KeyError) as e:
        print(f"Nasdaq API Error: {e}")
        return pd.DataFrame()
