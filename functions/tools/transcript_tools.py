import os
import requests

def fetch_and_split_transcript(ticker: str, year: int = None, quarter: int = None) -> dict:
    """Retrieves the earnings call transcript from FMP or Motley Fool scraper and splits it into Presentation and Q&A blocks.
    
    Args:
        ticker (str): Stock ticker symbol (e.g. 'AAPL').
        year (int, optional): Fiscal year of the transcript. Defaults to None (gets latest).
        quarter (int, optional): Fiscal quarter (1, 2, 3, or 4). Defaults to None (gets latest).
        
    Returns:
        dict: A dictionary containing:
            - 'presentation' (str): The corporate presentation block.
            - 'qa' (str): The analyst Q&A block.
            - 'meta' (dict): Metadata containing date, quarter, year, and symbol.
    """
    ticker = ticker.upper().strip()
    
    # 1. Attempt to fetch from MongoDB cache
    cache_col = None
    cache_key = f"{ticker}_{year or 0}_{quarter or 0}"
    try:
        from functions.utils.db.connect import get_db_client
        _, db = get_db_client()
        cache_col = db["transcripts_cache"]
        
        cached = cache_col.find_one({"_id": cache_key})
        if cached:
            print(f"[CACHE HIT] Loaded earnings call transcript for {ticker} Q{quarter or 0} {year or 0} from MongoDB.")
            return cached["data"]
    except Exception as e:
        print(f"[!] Warning: failed to check transcripts cache: {e}")

    # 2. Try fetching from FMP API (if credentials exist)
    fmp_data = None
    api_key = os.getenv("FMP_API_KEY", "").strip('"\'')
    if api_key:
        try:
            if year and quarter:
                url = f"https://financialmodelingprep.com/api/v3/earnings_call_transcript/{ticker}?quarter={quarter}&year={year}&apikey={api_key}"
                print(f"[*] Fetching transcript for {ticker} Q{quarter} {year} via FMP API...")
            else:
                url = f"https://financialmodelingprep.com/api/v3/earnings_call_transcript/{ticker}?apikey={api_key}"
                print(f"[*] Fetching latest transcripts for {ticker} via FMP API...")
                
            res = requests.get(url, timeout=10)
            res.raise_for_status()
            data = res.json()
            if data and isinstance(data, list) and len(data) > 0:
                fmp_data = data[0]
        except Exception as e:
            print(f"[!] Warning: FMP transcript fetch failed: {e}. Falling back to Motley Fool scraper...")
    else:
        print("[*] FMP_API_KEY not configured. Falling back to Motley Fool scraper...")

    # 3. Fallback to Motley Fool scraper if FMP failed or was not configured
    presentation = ""
    qa = ""
    meta = {}
    
    if fmp_data:
        content = fmp_data.get("content", "")
        presentation, qa = split_transcript(content)
        meta = {
            "symbol": fmp_data.get("symbol", ticker),
            "quarter": fmp_data.get("quarter", quarter or 0),
            "year": fmp_data.get("year", year or 0),
            "date": fmp_data.get("date", "unknown")
        }
        print(f"[*] Successfully retrieved and split transcript for {ticker} via FMP (Presentation length: {len(presentation)} chars, Q&A length: {len(qa)} chars).")
    else:
        from functions.tools.motley_fool import scrape_motley_fool_transcript
        scraped = scrape_motley_fool_transcript(ticker, year, quarter)
        if scraped:
            content = scraped.get("content", "")
            presentation, qa = split_transcript(content)
            meta = scraped.get("meta", {})
            print(f"[*] Successfully retrieved and split transcript for {ticker} via Motley Fool scraper (Presentation length: {len(presentation)} chars, Q&A length: {len(qa)} chars).")
        else:
            # Fallback payload to prevent upstream failures
            print(f"[!] Error: no transcript data could be retrieved for {ticker} from FMP or Motley Fool.")
            return {
                "presentation": "No transcript available.",
                "qa": "No Q&A section available.",
                "meta": {"symbol": ticker, "quarter": quarter or 0, "year": year or 0, "date": "unknown"}
            }

    result = {
        "presentation": presentation,
        "qa": qa,
        "meta": meta
    }

    # 4. Save to MongoDB cache
    if cache_col is not None:
        try:
            cache_col.replace_one({"_id": cache_key}, {"_id": cache_key, "data": result}, upsert=True)
            print(f"[CACHE STORE] Saved earnings call transcript for {ticker} Q{meta.get('quarter', 0)} {meta.get('year', 0)} to MongoDB.")
        except Exception as e:
            print(f"[!] Warning: failed to save transcript to cache: {e}")

    return result

def split_transcript(content: str) -> tuple[str, str]:
    """Isolates the corporate Management Presentation from the Analyst Q&A block."""
    if not content:
        return "", ""
        
    # Standard headers used in transcripts to signal transition to Q&A
    qa_headers = [
        "question-and-answer session",
        "question and answer session",
        "questions and answers",
        "q & a session",
        "q&a session",
        "q&a",
        "questions and answer"
    ]
    
    content_lower = content.lower()
    for header in qa_headers:
        idx = content_lower.find(header)
        if idx != -1:
            presentation = content[:idx].strip()
            # Retain the header in the Q&A block for context
            qa = content[idx:].strip()
            return presentation, qa
            
    # If no Q&A block separator is found, return the first half as presentation and second half as Q&A
    print("[!] Warning: Q&A transition header not found. Splitting transcript by length.")
    half_len = len(content) // 2
    return content[:half_len].strip(), content[half_len:].strip()
