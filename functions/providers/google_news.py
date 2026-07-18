import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import pandas as pd
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

def fetch_google_news_rss(symbol: str = "AAPL", limit: int = 50) -> pd.DataFrame:
    """
    Fetches real-time stock news from Google News RSS feed for any given ticker symbol.
    Rate-limit free, keyless, and extremely lightweight.
    
    Args:
        symbol (str): The stock ticker symbol (e.g. 'AAPL', 'MSFT', 'META').
        limit (int): Maximum number of articles to retrieve.
        
    Returns:
        pd.DataFrame: Standardized DataFrame with columns ['title', 'url', 'date', 'source'].
    """
    query = f"{symbol} stock news"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    articles = []
    try:
        req = urllib.request.Request(rss_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
            
        root = ET.fromstring(xml_data)
        
        for item in root.findall('.//item')[:limit]:
            title = item.findtext('title', '').strip()
            link = item.findtext('link', '').strip()
            pub_date_raw = item.findtext('pubDate', '').strip()
            source_elem = item.find('source')
            source = source_elem.text.strip() if source_elem is not None and source_elem.text else "Google News"
            
            # Format ISO datetime from pubDate (e.g., 'Sat, 18 Jul 2026 12:00:00 GMT')
            pub_iso = pub_date_raw
            if pub_date_raw:
                try:
                    dt = datetime.strptime(pub_date_raw, "%a, %d %b %Y %H:%M:%S %Z")
                    pub_iso = dt.replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    try:
                        # Fallback for GMT variations
                        if pub_date_raw.endswith("GMT"):
                            dt = datetime.strptime(pub_date_raw[:-4], "%a, %d %b %Y %H:%M:%S")
                            pub_iso = dt.replace(tzinfo=timezone.utc).isoformat()
                    except ValueError:
                        pub_iso = datetime.now(timezone.utc).isoformat()
                        
            if title and link:
                articles.append({
                    'title': title,
                    'url': link,
                    'date': pub_iso,
                    'source': source
                })
                
    except Exception as e:
        logger.warning(f"Google News RSS fetch error for {symbol}: {e}")
        
    if articles:
        df = pd.DataFrame(articles)
        return df.drop_duplicates(subset=['url'], keep='first')
        
    return pd.DataFrame(columns=['title', 'url', 'date', 'source'])
