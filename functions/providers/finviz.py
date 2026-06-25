import datetime
import urllib.request
from bs4 import BeautifulSoup
import pandas as pd

def parse_finviz_date(date_list: list) -> pd.Timestamp:
    """
    Parses a list of date/time text components scraped from Finviz into a pandas Timestamp.
    
    Use this function internally ONLY when converting scraped Finviz datetime string lists (e.g. ['today', '04:15PM'] or ['Jun-11-26', '09:00AM']) into standardized timestamps.
    Do not use this for general purpose date parsing or other providers.
    
    Args:
        date_list (list): A list containing string elements representing the date and/or time (e.g. ['Jun-11-26', '10:00AM']).
        
    Returns:
        pd.Timestamp: A pandas Timestamp object representing the parsed date/time in naive local format, or NaT if parsing fails.
        
    Example:
        parse_finviz_date(date_list=["Jun-11-26", "10:00AM"])
    """
    now = datetime.datetime.now()
    if len(date_list) == 2:
        date_part, time_part = date_list[0], date_list[1]
        if date_part.lower() == 'today':
            date_str = now.strftime('%Y-%m-%d') + ' ' + time_part
        else:
            try:
                dt_part = datetime.datetime.strptime(date_part, '%b-%d-%y')
                date_str = dt_part.strftime('%Y-%m-%d') + ' ' + time_part
            except (ValueError, TypeError):
                date_str = now.strftime('%Y-%m-%d') + ' ' + time_part
    elif len(date_list) == 1:
        date_str = now.strftime('%Y-%m-%d') + ' ' + date_list[0]
    else:
        date_str = now.strftime('%Y-%m-%d %H:%M')
    return pd.to_datetime(date_str, errors='coerce')

def fetch_finviz_scrape(symbol: str = "AAPL", limit: int = 100) -> pd.DataFrame:
    """
    Scrapes the news table for a specific stock ticker directly from the Finviz stock page.
    
    Use this tool ONLY when you need to fetch recent stock news by scraping the Finviz stock quotation page.
    Do not use this for general market indices or when you have access to a structured JSON API.
    
    Args:
        symbol (str): The stock ticker symbol to scrape news for (e.g., 'AAPL'). Defaults to 'AAPL'.
        limit (int): The maximum number of news rows to parse from the table. Defaults to 100.
        
    Returns:
        pd.DataFrame: A pandas DataFrame containing news articles with columns: 'date', 'title', 'url', 'source', 'summary', 'text', 'provider'.
        
    Example:
        fetch_finviz_scrape(symbol="AAPL", limit=10)
    """
    import urllib.error
    url = f"https://finviz.com/quote.ashx?t={symbol}"
    req = urllib.request.Request(url=url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        html = urllib.request.urlopen(req, timeout=10).read()
        soup = BeautifulSoup(html, 'html.parser')
        news_table = soup.find(id='news-table')
        if not news_table:
            return pd.DataFrame()
        
        rows = []
        for row in news_table.find_all('tr')[:limit]:
            if not row.a:
                continue
            date_data = row.td.text.strip().split()
            rows.append({
                "date": parse_finviz_date(date_data),
                "title": row.a.get_text().strip(),
                "url": row.a['href'],
                "source": "Yahoo Finance" if "finance.yahoo.com" in row.a['href'] else "Finviz Source",
                "summary": None,
                "text": None,
                "provider": "finviz"
            })
        return pd.DataFrame(rows)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, AttributeError, KeyError) as e:
        print(f"Finviz Error: {e}")
        return pd.DataFrame()
