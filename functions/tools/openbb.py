from openbb import obb
import pandas as pd

def fetch_etf_holdings_from_openbb(symbol: str) -> pd.DataFrame:
    """Fetch constituent tickers and percentage weights for a specified ETF.
    
    Use this tool when you need to retrieve the underlying holdings, asset symbols,
    and allocation weights of an Exchange-Traded Fund (ETF) to analyze asset distribution
    or portfolio weights. Do not use this for individual stock news sentiment scoring
    or general macroeconomic indicators.
    
    Args:
        symbol (str): The unique ticker symbol of the ETF (e.g., 'SPY', 'QQQ').
        
    Returns:
        pd.DataFrame: A DataFrame containing the constituents and weights, with columns:
            - `ticker` (str): The ticker symbol of the constituent asset.
            - `fund_weight` (float): The percentage allocation weight of the constituent in the ETF.
            
            In case of failure (network errors, invalid symbol, or API failure), returns an empty
            DataFrame with the columns ['ticker', 'fund_weight'] to prevent upstream matrix failure.
    """
    try:
        # Calls the native OpenBB ODP endpoint
        res = obb.etf.holdings(symbol=symbol)
        df = res.to_dataframe()
        
        # Keep only required columns: constituent ticker and percentage weight
        df_cleaned = df[['asset_symbol', 'weight']].rename(
            columns={'asset_symbol': 'ticker', 'weight': 'fund_weight'}
        )
        return df_cleaned
    except Exception as e:
        # Fallback to an empty schema structure to prevent upstream matrix failure
        return pd.DataFrame(columns=['ticker', 'fund_weight'])