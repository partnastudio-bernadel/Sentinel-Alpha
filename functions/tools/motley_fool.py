import re
import time
import random
import requests
from bs4 import BeautifulSoup

_quote_page_cache = {}  # ticker -> HTML text
_quote_url_cache = {}   # ticker -> working URL
_missing_transcripts_cache = set()  # set of (ticker, year, quarter) known missing
_playwright_links_cache = {}  # ticker -> dict of {(year, quarter): transcript_url}


def get_all_transcript_links_playwright(ticker: str) -> dict:
    """
    Uses Playwright to navigate Motley Fool quote page, click 'Earnings Transcripts' tab,
    paginate through 'Next' buttons, and collect all historical transcript links across 5+ years.
    Returns dict: {(year, quarter): transcript_url}
    """
    global _playwright_links_cache
    ticker = ticker.upper().strip()
    if ticker in _playwright_links_cache:
        return _playwright_links_cache[ticker]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[!] Playwright not installed in environment. Install with `pip install playwright && playwright install chromium`.")
        return {}

    links_map = {}
    urls_to_try = [
        f"https://www.fool.com/quote/nasdaq/{ticker}/",
        f"https://www.fool.com/quote/nyse/{ticker}/",
        f"https://www.fool.com/quote/{ticker}/"
    ]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            loaded = False
            for url in urls_to_try:
                try:
                    print(f"[*] [Playwright] Navigating to Motley Fool quote page: {url}")
                    page.goto(url, timeout=15000, wait_until="domcontentloaded")
                    time.sleep(2)
                    if "fool.com" in page.url:
                        loaded = True
                        break
                except Exception as e:
                    print(f"[!] Playwright navigation warning: {e}")

            if not loaded:
                browser.close()
                return {}

            # Click 'Earnings Transcripts' button or tab if present
            try:
                tab = page.locator("button:has-text('Earnings Transcripts')").or_(page.locator("a:has-text('Earnings Transcripts')"))
                if tab.count() > 0:
                    print(f"[*] [Playwright] Clicking 'Earnings Transcripts' tab for {ticker}...")
                    tab.first.click()
                    time.sleep(1.5)
            except Exception as e:
                print(f"[!] Playwright tab click note: {e}")

            # Paginate through 'Next' buttons (up to 12 pages) to gather all historical years
            for p_idx in range(12):
                anchors = page.locator("a[href*='/earnings/call-transcripts/']").all()
                for a in anchors:
                    try:
                        href = a.get_attribute("href")
                        if href:
                            path = href.replace("https://www.fool.com", "").strip()
                            # Parse year & quarter e.g. /earnings/call-transcripts/2024/10/31/apple-aapl-q4-2024-earnings-call-transcript/
                            m_yr = re.search(r'/earnings/call-transcripts/(202[0-6])/', path)
                            m_q = re.search(r'-q([1-4])-(202[0-6])-', path) or re.search(r'q([1-4])', path.lower())
                            
                            if m_yr and m_q:
                                yr = int(m_yr.group(1))
                                qtr = int(m_q.group(1))
                                full_url = f"https://www.fool.com{path}" if path.startswith('/') else path
                                links_map[(yr, qtr)] = full_url
                    except Exception:
                        pass

                # Try clicking 'Next' button inside News container
                try:
                    next_btn = page.locator("div:has(h2:has-text('News')) button:has-text('Next')").or_(
                        page.locator("button:has-text('Next')")
                    )
                    if next_btn.count() > 0 and next_btn.first.is_visible():
                        print(f"[*] [Playwright] Clicking 'Next' page ({p_idx + 1}) for {ticker}...")
                        next_btn.first.click()
                        time.sleep(1.5)
                    else:
                        break
                except Exception:
                    break

            browser.close()
    except Exception as pw_err:
        print(f"[!] Playwright execution note: {pw_err}")

    print(f"[*] [Playwright] Gathered {len(links_map)} historical transcript links across years for {ticker}.")
    _playwright_links_cache[ticker] = links_map
    return links_map


def scrape_motley_fool_transcript(ticker: str, year: int = None, quarter: int = None) -> dict:
    """Scrapes Motley Fool website for the earnings call transcript of a ticker."""
    global _quote_page_cache, _quote_url_cache, _missing_transcripts_cache, _playwright_links_cache
    ticker = ticker.upper().strip()
    
    cache_key = (ticker, year or 0, quarter or 0)
    if cache_key in _missing_transcripts_cache:
        return None

    # Option A: Check if Playwright gathered a direct transcript URL match
    if year and quarter:
        pw_map = _playwright_links_cache.get(ticker)
        if pw_map is None:
            pw_map = get_all_transcript_links_playwright(ticker)
            
        matched_url = pw_map.get((year, quarter))
        if matched_url:
            print(f"[*] [Playwright MATCH] Found transcript link for {ticker} FY{year} Q{quarter}: {matched_url}")
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            }
            try:
                res_art = requests.get(matched_url, headers=headers, timeout=10)
                if res_art.status_code == 200:
                    soup_art = BeautifulSoup(res_art.text, "html.parser")
                    body = soup_art.find("div", class_="article-body") or soup_art.find("div", id="pitch-body")
                    content = body.get_text("\n").strip() if body else soup_art.get_text("\n").strip()
                    if len(content) > 500:
                        return {
                            "content": content,
                            "meta": {"symbol": ticker, "quarter": quarter, "year": year, "date": str(year)}
                        }
            except Exception as art_err:
                print(f"[!] Warning fetching matched Playwright article {matched_url}: {art_err}")

    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ]
    
    headers = {
        "User-Agent": random.choice(user_agents),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1"
    }
    
    html_text = _quote_page_cache.get(ticker)
    
    if not html_text:
        # Determine URLs to try (prioritize cached working URL if known)
        if ticker in _quote_url_cache:
            urls_to_try = [_quote_url_cache[ticker]]
        else:
            urls_to_try = [
                f"https://www.fool.com/quote/nasdaq/{ticker}/",
                f"https://www.fool.com/quote/nyse/{ticker}/",
                f"https://www.fool.com/quote/nysemkt/{ticker}/",
                f"https://www.fool.com/quote/{ticker}/"
            ]
        
        for url in urls_to_try:
            try:
                time.sleep(0.5 + random.uniform(0.1, 0.4))  # Pacing delay to prevent Cloudflare burst blocks
                print(f"[*] Trying Motley Fool quote page: {url}")
                res = requests.get(url, headers=headers, timeout=10)
                
                if "You have been blocked" in res.text or "A Foolish Haiku" in res.text:
                    print(f"[!] Warning: Motley Fool Cloudflare WAF block detected for IP. Skipping Motley Fool scraper for {ticker}.")
                    _missing_transcripts_cache.add(cache_key)
                    return None
                    
                if res.status_code == 200 and len(res.text) > 1000:
                    html_text = res.text
                    _quote_page_cache[ticker] = html_text
                    _quote_url_cache[ticker] = url
                    break
            except Exception as e:
                print(f"[!] Warning: failed to fetch quote page {url}: {e}")
                
    if not html_text:
        print(f"[!] Error: Could not find any quote page for ticker {ticker} on Motley Fool.")
        _missing_transcripts_cache.add(cache_key)
        return None
        
    # Search <a> tags and full page HTML for transcript URL patterns
    soup = BeautifulSoup(html_text, "html.parser")
    paths = []
    
    # 1. Extract from <a> tags
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/earnings/call-transcripts/" in href:
            p = href.replace("https://www.fool.com", "").strip()
            if p.startswith("/earnings/call-transcripts/"):
                paths.append(p)

    # 2. Fallback to raw HTML regex search (captures NEXT_DATA scripts and JSON blocks)
    raw_matches = re.findall(r'/earnings/call-transcripts/[a-zA-Z0-9\-_/]+', html_text)
    for m in raw_matches:
        clean_m = m.rstrip('"\'\\>;,')
        if clean_m.startswith("/earnings/call-transcripts/") and len(clean_m) > 30:
            paths.append(clean_m)

    if not paths:
        print(f"[!] Warning: no transcript links found on quote page for {ticker}.")
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
                
    # Fallback to the latest transcript ONLY if year and quarter were not specified
    if not selected_path:
        if year or quarter:
            print(f"[!] Warning: Motley Fool has no transcript link matching year={year} quarter={quarter} for {ticker}.")
            return None
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
