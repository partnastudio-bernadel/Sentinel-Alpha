import os
import requests
from dotenv import load_dotenv

# Load env variables automatically
script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))
env_path = os.path.join(sentiment_dir, ".env.local")
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    load_dotenv()

_fmp_disabled = False

def fetch_and_split_transcript(ticker: str, year: int = None, quarter: int = None) -> dict:
    global _fmp_disabled
    ticker = ticker.upper().strip()
    
    # 1. Attempt to fetch from Cloudflare R2 or MongoDB cache
    cache_col = None
    cache_key = f"{ticker}_{year or 0}_{quarter or 0}"
    r2_path = f"transcripts_cache/{cache_key}.json"

    try:
        from functions.utils.storage.r2_client import exists_in_r2, download_article_doc
        if exists_in_r2(r2_path):
            cached_r2 = download_article_doc(r2_path)
            if isinstance(cached_r2, dict) and isinstance(cached_r2.get("data"), dict):
                cached_data = cached_r2["data"]
                if cached_data.get("presentation") != "No transcript available.":
                    print(f"[CACHE HIT] Loaded earnings call transcript for {ticker} Q{quarter or 0} {year or 0} from Cloudflare R2.")
                    return cached_data
    except Exception as r2_err:
        print(f"[!] Warning: R2 cache check failed: {r2_err}")

    try:
        from functions.utils.db.connect import get_db_client
        _, db = get_db_client()
        cache_col = db["transcripts_cache"]
        
        cached = cache_col.find_one({"_id": cache_key})
        if cached:
            if isinstance(cached.get("data"), dict):
                cached_data = cached["data"]
                if cached_data.get("presentation") != "No transcript available.":
                    print(f"[CACHE HIT] Loaded earnings call transcript for {ticker} Q{quarter or 0} {year or 0} from MongoDB.")
                    return cached_data
            elif cached.get("r2_path"):
                try:
                    from functions.utils.storage.r2_client import download_article_doc
                    r2_doc = download_article_doc(cached["r2_path"])
                    if isinstance(r2_doc.get("data"), dict):
                        print(f"[CACHE HIT] Loaded transcript for {ticker} Q{quarter or 0} {year or 0} from R2 via Mongo Pointer.")
                        return r2_doc["data"]
                except Exception:
                    pass
    except Exception as e:
        print(f"[!] Warning: failed to check transcripts cache: {e}")

    # 2. Try fetching from FMP API (if credentials exist and FMP is active)
    fmp_data = None
    api_key = os.getenv("FMP_API_KEY", "").strip('"\'')
    if api_key and not _fmp_disabled:
        try:
            if year and quarter:
                url = f"https://financialmodelingprep.com/api/v3/earnings_call_transcript/{ticker}?quarter={quarter}&year={year}&apikey={api_key}"
                print(f"[*] Fetching transcript for {ticker} Q{quarter} {year} via FMP API...")
            else:
                url = f"https://financialmodelingprep.com/api/v3/earnings_call_transcript/{ticker}?apikey={api_key}"
                print(f"[*] Fetching latest transcripts for {ticker} via FMP API...")
                
            res = requests.get(url, timeout=10)
            if res.status_code == 403:
                print("[!] FMP API returned 403 Forbidden. Disabling FMP for remaining batch run...")
                _fmp_disabled = True
            else:
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

    # 4. Save to Cloudflare R2 and lightweight pointer in MongoDB
    payload = {
        "_id": cache_key, 
        "ticker": ticker,
        "year": year or meta.get("year", 0),
        "quarter": quarter or meta.get("quarter", 0),
        "data": result
    }
    try:
        from functions.utils.storage.r2_client import upload_json_to_r2
        upload_json_to_r2(r2_path, payload)
        print(f"[CACHE STORE] Saved earnings call transcript for {ticker} Q{meta.get('quarter', 0)} {meta.get('year', 0)} to Cloudflare R2.")

        if cache_col is not None:
            pointer_doc = {
                "_id": cache_key,
                "ticker": ticker,
                "year": year or meta.get("year", 0),
                "quarter": quarter or meta.get("quarter", 0),
                "r2_path": r2_path,
                "archived": True
            }
            cache_col.replace_one({"_id": cache_key}, pointer_doc, upsert=True)
            print(f"[CACHE STORE] Saved transcript lightweight pointer to MongoDB.")
    except Exception as e:
        print(f"[!] Warning: failed to save transcript to R2/MongoDB cache: {e}")

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
