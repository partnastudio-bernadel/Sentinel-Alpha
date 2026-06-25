import os
import pandas as pd
from openbb import obb
from dotenv import load_dotenv

# Auto-load environment variables from .env.local
load_dotenv(".env.local")

# Import modular helper submodules from their new locations
from functions.utils.common.standardizer import standardize_df
from functions.providers.alpha_vantage import fetch_alpha_vantage
from functions.providers.news_api import fetch_news_api
from functions.providers.seeking_alpha import fetch_seeking_alpha_rapidapi
from functions.providers.nasdaq import fetch_nasdaq_api
from functions.providers.finviz import fetch_finviz_scrape

def fetch_aggregate_all_news(symbol: str = "AAPL", limit: int = 100) -> pd.DataFrame:
    """
    Aggregates, standardizes, and consolidates stock news articles from all 11 providers (OpenBB & custom APIs/scrapers).
    
    Use this tool ONLY when you need to retrieve a comprehensive, deduplicated feed of stock news from multiple sources.
    Do not use this for checking stock prices, charting, or extracting text from a single webpage.
    
    Args:
        symbol (str): The stock ticker symbol to fetch news for (e.g., 'AAPL'). Defaults to 'AAPL'.
        limit (int): The maximum number of news articles to retrieve from each provider. Defaults to 100.
        
    Returns:
        pd.DataFrame: A consolidated pandas DataFrame containing standardized news articles from all working sources, sorted by date in descending order.
        
    Example:
        fetch_aggregate_all_news(symbol="AAPL", limit=50)
    """
    aggregated_dfs = []
    
    # 1. OpenBB Platform Providers
    obb_providers = [
        # (provider_name, endpoint_type, credential_name)
        ("yfinance", "company", None),
        ("tmx", "company", None),
        ("fmp", "company", "fmp_api_key"),
        ("tiingo", "company", "tiingo_token"),
        ("biztoc", "world_query", "biztoc_api_key"),
        ("benzinga", "company", "benzinga_api_key")
    ]
    
    for provider, endpoint_type, credential_attr in obb_providers:
        if credential_attr:
            env_val = os.getenv(credential_attr.upper())
            if env_val:
                setattr(obb.user.credentials, credential_attr, env_val)
            if not getattr(obb.user.credentials, credential_attr, None):
                print(f"[-] Skipping OpenBB {provider.upper()}: Key not set")
                continue
                
        print(f"[+] Fetching OpenBB {provider.upper()}...")
        try:
            if endpoint_type == "company":
                res = obb.news.company(symbol=symbol, provider=provider, limit=limit)
                df = res.to_dataframe()
            elif endpoint_type == "world_query":
                res = obb.news.world(query=symbol, provider=provider, limit=limit)
                df = res.to_dataframe()
            
            standard_df = standardize_df(df, provider)
            if not standard_df.empty:
                aggregated_dfs.append(standard_df)
        except Exception as e:
            print(f"    -> OpenBB {provider.upper()} Error: {e}")
            
            
    # 2. Custom Web/Official API Providers
    custom_fetchers = [
        ("alpha-vantage", fetch_alpha_vantage),
        ("news_api", fetch_news_api),
        ("seeking-alpha", fetch_seeking_alpha_rapidapi),
        ("nasdaq", fetch_nasdaq_api),
        ("finviz", fetch_finviz_scrape)
    ]
    
    for name, fetcher_fn in custom_fetchers:
        print(f"[+] Fetching Custom {name.upper()}...")
        try:
            df = fetcher_fn(symbol=symbol, limit=limit)
            if df is not None and not df.empty:
                aggregated_dfs.append(standardize_df(df, name))
        except (RuntimeError, ValueError, AttributeError) as e:
            print(f"    -> Custom {name.upper()} Error: {e}")
            
    if aggregated_dfs:
        final_df = pd.concat(aggregated_dfs, ignore_index=True)
        final_df = final_df.drop_duplicates(subset=['url'], keep='first')
        final_df = final_df.drop_duplicates(subset=['title'], keep='first')
        return final_df.sort_values(by='date', ascending=False)
    return pd.DataFrame()
