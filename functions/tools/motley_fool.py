import re
import requests
from bs4 import BeautifulSoup

def scrape_motley_fool_transcript(ticker: str, year: int = None, quarter: int = None) -> dict:
    """Scrapes Motley Fool website for the earnings call transcript of a ticker.
    
    Args:
        ticker (str): Stock ticker symbol (e.g., 'AAPL').
        year (int, optional): Target calendar year of the transcript.
        quarter (int, optional): Target calendar quarter (1, 2, 3, or 4).
        
    Returns:
        dict: A dictionary containing:
            - 'content' (str): The full parsed transcript text.
            - 'meta' (dict): Metadata containing date, quarter, year, and symbol.
            Or None if no transcript was found or parsed successfully.
    """
    ticker = ticker.upper().strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    # Try Nasdaq quote page first, fallback to NYSE
    urls_to_try = [
        f"https://www.fool.com/quote/nasdaq/{ticker}/",
        f"https://www.fool.com/quote/nyse/{ticker}/",
        f"https://www.fool.com/quote/{ticker}/"
    ]
    
    html_text = ""
    for url in urls_to_try:
        try:
            print(f"[*] Trying Motley Fool quote page: {url}")
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                html_text = res.text
                break
        except Exception as e:
            print(f"[!] Warning: failed to fetch quote page {url}: {e}")
            
    if not html_text:
        print(f"[!] Error: Could not find any quote page for ticker {ticker} on Motley Fool.")
        return None
        
    # Search script tags for links matching the transcript URL pattern
    soup = BeautifulSoup(html_text, "html.parser")
    script_text = "".join([s.string for s in soup.find_all("script") if s.string])
    
    # Find all matching paths
    paths = re.findall(r'/earnings/call-transcripts/[\w/-]+', script_text)
    if not paths:
        print(f"[!] Warning: no transcript links found in quote page script tags for {ticker}.")
        return None
        
    # Deduplicate paths keeping order
    unique_paths = []
    for p in paths:
        if p not in unique_paths:
            unique_paths.append(p)
            
    selected_path = None
    
    # Attempt to match requested year/quarter
    if year or quarter:
        for p in unique_paths:
            match_year = True
            match_quarter = True
            
            if year:
                # Year is part of the path segment, e.g., /2026/
                match_year = f"/{year}/" in p
                
            if quarter:
                # Quarter is typically in the slug as 'q1', 'q2', etc.
                match_quarter = f"-q{quarter}-" in p or f"q{quarter}" in p
                
            if match_year and match_quarter:
                selected_path = p
                break
                
    # Fallback to the latest one (first in the list)
    if not selected_path:
        selected_path = unique_paths[0]
        print(f"[*] Selecting latest available transcript link: {selected_path}")
    else:
        print(f"[*] Selecting matched transcript link: {selected_path}")
        
    transcript_url = f"https://www.fool.com{selected_path}"
    
    # Fetch and parse the transcript article
    try:
        print(f"[*] Fetching transcript content from: {transcript_url}")
        res = requests.get(transcript_url, headers=headers, timeout=10)
        res.raise_for_status()
        
        soup_art = BeautifulSoup(res.text, "html.parser")
        body = (
            soup_art.find("div", class_="article-body") 
            or soup_art.find("div", class_="tailwind-article-body") 
            or soup_art.find("div", id="article-body")
        )
        
        if not body:
            print(f"[!] Error: Could not find article body for transcript at {transcript_url}.")
            return None
            
        content = body.get_text().strip()
        
        # Try to parse date from URL if possible
        # Path structure: /earnings/call-transcripts/YYYY/MM/DD/...
        date_str = "unknown"
        parts = selected_path.strip("/").split("/")
        if len(parts) >= 5:
            date_str = f"{parts[2]}-{parts[3]}-{parts[4]}"
            
        return {
            "content": content,
            "meta": {
                "symbol": ticker,
                "quarter": quarter or 0,
                "year": year or 0,
                "date": date_str
            }
        }
    except Exception as e:
        print(f"[!] Error fetching transcript content from {transcript_url}: {e}")
        return None
