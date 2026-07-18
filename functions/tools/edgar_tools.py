import os
import re
import requests
from bs4 import BeautifulSoup

def get_sec_user_agent() -> str:
    """Load the SEC user agent from environment variables, defaulting to a standard placeholder."""
    # Ensure we strip quotes that might be parsed from dotenv files
    return os.getenv("SEC_EDGAR_USER_AGENT", "Partna Studio joshua.bernadel@partnastudio.com").strip('"\'')

def get_cik_by_ticker(ticker: str) -> str:
    """Lookup Central Index Key (CIK) for a given stock ticker using the SEC mapping."""
    ticker = ticker.upper().strip()
    user_agent = get_sec_user_agent()
    headers = {"User-Agent": user_agent}
    url = "https://www.sec.gov/files/company_tickers.json"
    
    print(f"[*] Querying SEC CIK mapping for ticker: {ticker}...")
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    data = res.json()
    
    for key, val in data.items():
        if val["ticker"] == ticker:
            # Pad CIK to 10 digits as required by SEC APIs
            cik_padded = str(val["cik_str"]).zfill(10)
            print(f"[*] Found CIK: {cik_padded} for {ticker}")
            return cik_padded
            
    raise ValueError(f"Central Index Key (CIK) not found for ticker: {ticker}")

def get_10k_metadata_by_year(cik: str, target_year: int) -> dict:
    """Finds the accession Number and primary document name of the 10-K filing for a specific year."""
    user_agent = get_sec_user_agent()
    headers = {"User-Agent": user_agent}
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    
    print(f"[*] Fetching filings metadata for CIK: {cik}...")
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    data = res.json()
    
    filings = data["filings"]["recent"]
    
    for idx, form in enumerate(filings["form"]):
        if form == "10-K":
            filed_date = filings["filingDate"][idx]
            year = int(filed_date.split("-")[0])
            
            # Since a 10-K for year Y is usually filed in Y or early Y+1,
            # we check the report date or filing date year to match the target year
            report_date = filings["reportDate"][idx]
            report_year = int(report_date.split("-")[0])
            
            if report_year == target_year or year == target_year:
                accession_number = filings["accessionNumber"][idx]
                primary_doc = filings["primaryDocument"][idx]
                acc_no_no_hyphens = accession_number.replace("-", "")
                
                print(f"[*] Found 10-K for CIK {cik} year {target_year}: {accession_number} (Filed: {filed_date})")
                return {
                    "accession_number": accession_number,
                    "primary_document": primary_doc,
                    "acc_no_no_hyphens": acc_no_no_hyphens,
                    "filed_date": filed_date,
                    "report_year": report_year
                }
                
    # Fallback to the latest if target_year filing is not found
    print(f"[!] Warning: specific 10-K for year {target_year} not found. Attempting to fall back to latest 10-K...")
    for idx, form in enumerate(filings["form"]):
        if form == "10-K":
            accession_number = filings["accessionNumber"][idx]
            primary_doc = filings["primaryDocument"][idx]
            acc_no_no_hyphens = accession_number.replace("-", "")
            filed_date = filings["filingDate"][idx]
            report_date = filings["reportDate"][idx]
            report_year = int(report_date.split("-")[0])
            print(f"[*] Falling back to latest 10-K (Year: {report_year}, Filed: {filed_date})")
            return {
                "accession_number": accession_number,
                "primary_document": primary_doc,
                "acc_no_no_hyphens": acc_no_no_hyphens,
                "filed_date": filed_date,
                "report_year": report_year
            }
            
    # Fallback for IPOs lacking a 10-K: search for S-1 or 424B4
    print(f"[!] Warning: no 10-K found. Attempting to fall back to S-1 or 424B4 (IPO Prospectus)...")
    for idx, form in enumerate(filings["form"]):
        if form in ["S-1", "S-1/A", "424B4"]:
            accession_number = filings["accessionNumber"][idx]
            primary_doc = filings["primaryDocument"][idx]
            acc_no_no_hyphens = accession_number.replace("-", "")
            filed_date = filings["filingDate"][idx]
            print(f"[*] Falling back to {form} filing (Filed: {filed_date})")
            return {
                "accession_number": accession_number,
                "primary_document": primary_doc,
                "acc_no_no_hyphens": acc_no_no_hyphens,
                "filed_date": filed_date,
                "report_year": target_year
            }
            
    raise ValueError(f"No 10-K or IPO filings found for CIK {cik}")

def extract_section_1a(full_text: str) -> str:
    """Helper to parse and extract the Item 1A (Risk Factors) section from 10-K text."""
    normalized_text = re.sub(r'\s+', ' ', full_text)
    
    # Locate all boundaries case-insensitively
    matches_1a = [m.start() for m in re.finditer(r'item\s+1a\.?\s+', normalized_text, re.IGNORECASE)]
    matches_1b = [m.start() for m in re.finditer(r'item\s+1b\.?\s+', normalized_text, re.IGNORECASE)]
    matches_2 = [m.start() for m in re.finditer(r'item\s+2\.?\s+', normalized_text, re.IGNORECASE)]
    
    # Look for the actual section (must be longer than 3000 chars to bypass Table of Contents)
    for start in matches_1a:
        ends = [e for e in (matches_1b + matches_2) if e > start]
        if not ends:
            continue
        end = min(ends)
        section_content = normalized_text[start:end].strip()
        if len(section_content) > 3000:
            return section_content
            
    # Fallback to the longest match if none exceeded the size threshold
    best_section = ""
    for start in matches_1a:
        ends = [e for e in (matches_1b + matches_2) if e > start]
        if not ends:
            continue
        end = min(ends)
        section_content = normalized_text[start:end].strip()
        if len(section_content) > len(best_section):
            best_section = section_content
            
    return best_section if len(best_section) > 500 else "Risk Factors (Item 1A) section could not be parsed."

def extract_section_7(full_text: str) -> str:
    """Helper to parse and extract the Item 7 (MD&A) section from 10-K text."""
    normalized_text = re.sub(r'\s+', ' ', full_text)
    
    matches_7 = [m.start() for m in re.finditer(r'item\s+7\.?\s+', normalized_text, re.IGNORECASE)]
    matches_7a = [m.start() for m in re.finditer(r'item\s+7a\.?\s+', normalized_text, re.IGNORECASE)]
    matches_8 = [m.start() for m in re.finditer(r'item\s+8\.?\s+', normalized_text, re.IGNORECASE)]
    
    for start in matches_7:
        ends = [e for e in (matches_7a + matches_8) if e > start]
        if not ends:
            continue
        end = min(ends)
        section_content = normalized_text[start:end].strip()
        if len(section_content) > 5000:
            return section_content
            
    best_section = ""
    for start in matches_7:
        ends = [e for e in (matches_7a + matches_8) if e > start]
        if not ends:
            continue
        end = min(ends)
        section_content = normalized_text[start:end].strip()
        if len(section_content) > len(best_section):
            best_section = section_content
            
    return best_section if len(best_section) > 500 else "Management Discussion & Analysis (Item 7) section could not be parsed."

def get_sec_10k_section(ticker: str, year: int, section: str) -> str:
    """Retrieves and parses a specific section (Item 1A or Item 7) from the latest 10-K for a ticker."""
    section = str(section).upper().strip()
    if section not in ["1A", "7"]:
        raise ValueError("This tool only supports extraction of sections '1A' (Risk Factors) or '7' (MD&A).")
        
    # Attempt to fetch from MongoDB cache
    cache_col = None
    cache_key = f"{ticker.upper()}_{year}_{section}"
    try:
        from pymongo import MongoClient
        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.getenv("MONGODB_DB", "sentinel_db")
        client = MongoClient(mongodb_uri)
        db = client[db_name]
        cache_col = db["sec_filings_cache"]
        
        cached = cache_col.find_one({"_id": cache_key})
        if cached:
            print(f"[CACHE HIT] Loaded SEC 10-K Item {section} for {ticker} ({year}) from MongoDB.")
            return cached["content"]
    except Exception as e:
        print(f"[!] Warning: failed to check SEC cache: {e}")
        
    user_agent = get_sec_user_agent()
    cik = get_cik_by_ticker(ticker)
    meta = get_10k_metadata_by_year(cik, year)
    
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{meta['acc_no_no_hyphens']}/{meta['primary_document']}"
    headers = {"User-Agent": user_agent}
    
    print(f"[*] Downloading SEC 10-K file from Archives URL: {url}")
    res = requests.get(url, headers=headers)
    res.raise_for_status()
    
    print("[*] Parsing filing HTML with BeautifulSoup...")
    soup = BeautifulSoup(res.text, "html.parser")
    full_text = soup.get_text(separator="\n")
    
    print(f"[*] Extracting Item {section} from filing text...")
    content = ""
    if section == "1A":
        content = extract_section_1a(full_text)
    else:
        content = extract_section_7(full_text)
        
    # Save to MongoDB cache
    if cache_col is not None and content and "could not be parsed" not in content:
        try:
            cache_col.replace_one(
                {"_id": cache_key}, 
                {
                    "_id": cache_key, 
                    "ticker": ticker,
                    "year": year,
                    "section": section,
                    "content": content
                }, 
                upsert=True
            )
            print(f"[CACHE STORE] Saved SEC 10-K Item {section} for {ticker} ({year}) to MongoDB.")
        except Exception as e:
            print(f"[!] Warning: failed to save SEC filing to cache: {e}")
            
    return content
