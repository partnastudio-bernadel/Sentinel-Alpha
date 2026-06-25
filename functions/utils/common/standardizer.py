import pandas as pd

def standardize_df(df: pd.DataFrame, provider_name: str) -> pd.DataFrame:
    """
    Standardizes a news article DataFrame fetched from any provider to match the central project schema.
    
    Use this utility internally ONLY when standardizing the columns and timezone-naive date format of a raw news DataFrame.
    Do not use this for general formatting of price data or database tables.
    
    Args:
        df (pd.DataFrame): The raw input DataFrame containing scraped or fetched articles from a provider.
        provider_name (str): The name identifier of the data provider (e.g. 'yfinance', 'finviz').
        
    Returns:
        pd.DataFrame: A standardized pandas DataFrame containing the specific columns: 'date', 'title', 'url', 'source', 'summary', 'text', and 'provider'.
        
    Example:
        standardize_df(df=raw_df, provider_name="yfinance")
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # Reset index to bring 'date' back as a column if it is the index
    if df.index.name == 'date' or 'date' not in df.columns:
        df = df.reset_index()
        
    cols = ['date', 'title', 'url', 'source', 'summary', 'text']
    for col in cols:
        if col not in df.columns:
            df[col] = None
            
    df = df[cols].copy()
    df['date'] = pd.to_datetime(df['date'], errors='coerce', utc=True).dt.tz_localize(None)
    df['provider'] = provider_name
    return df
