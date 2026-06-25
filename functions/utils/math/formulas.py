import json
import math
from typing import Dict, List, Tuple, Optional, Any

def calculate_raw_sentiment(articles: Any) -> float:
    """Calculates the confidence-weighted average sentiment score of scored articles.
    
    Formula:
        S_raw = sum(s_i * c_i) / sum(c_i)
        
    Args:
        articles: A list of dicts containing 'sentiment_score'/'raw_sentiment' and 'confidence'/'confidence_score', or a single dict.
        
    Returns:
        The raw sentiment score in range [-1.0, 1.0], defaulting to 0.0 if empty or zero confidence.
    """
    if isinstance(articles, str):
        try:
            articles = json.loads(articles)
        except Exception:
            return 0.0
            
    if not articles:
        return 0.0
        
    if isinstance(articles, dict):
        articles = [articles]
        
    weighted_sum = 0.0
    confidence_sum = 0.0
    
    for article in articles:
        if not isinstance(article, dict):
            continue
            
        # Support both nested 'sentiment' dict and flat keys
        if "sentiment" in article and isinstance(article["sentiment"], dict):
            score = article["sentiment"].get("raw_sentiment")
            confidence = article["sentiment"].get("confidence_score")
        else:
            score = article.get("sentiment_score")
            if score is None:
                score = article.get("raw_sentiment", 0.0)
                
            confidence = article.get("confidence")
            if confidence is None:
                confidence = article.get("confidence_score", 0.0)
        
        # Guard against malformed or missing values
        if score is None or confidence is None:
            continue
            
        weighted_sum += float(score) * float(confidence)
        confidence_sum += float(confidence)
        
    if confidence_sum == 0.0:
        return 0.0
        
    return weighted_sum / confidence_sum


def calculate_macro_surprise(
    actual: float, 
    consensus: float, 
    historical_std: float, 
    days_since_release: float = 0.0
) -> Tuple[float, bool]:
    """Computes macroeconomic surprise metrics using standardized z-score, 
    asymmetric volatility scaling, and exponential decay (lambda).
    
    Args:
        actual: The released economic value.
        consensus: The forecast consensus value.
        historical_std: The rolling historical standard deviation (sigma_historical).
        days_since_release: Number of days since the event (for exponential decay).
        
    Returns:
        A tuple of (surprise_index, warning_flag).
        warning_flag is True if historical_std was invalid (<= 0 or None) and standard fallback of 1.0 was used.
    """
    warning_flag = False
    
    # Handle invalid or division-by-zero cases
    if historical_std is None or historical_std <= 0.0:
        std_denominator = 1.0
        warning_flag = True
    else:
        std_denominator = historical_std
        
    # 1. Standardized Surprise (z-score)
    z_score = (actual - consensus) / std_denominator
    
    # 2. Asymmetric Volatility Scaling (Penalize negative shocks 1.5x)
    # The sign is preserved, but the magnitude is scaled if negative
    if z_score < 0:
        scaled_surprise = z_score * 1.5
    else:
        scaled_surprise = z_score
        
    # 3. Exponential Decay (Lambda ~ 90 day half-life -> ln(2)/90 = 0.0077)
    decay_lambda = 0.0077
    decay_factor = math.exp(-decay_lambda * days_since_release)
    
    surprise_index = scaled_surprise * decay_factor
    
    return surprise_index, warning_flag


def calculate_effective_sentiment(
    ticker: str, 
    raw_sentiment: float, 
    macro_shock: float, 
    etf_macro_beta: float,
    ticker_market_beta: float = 1.0
) -> float:
    """Calculates Effective Ticker Sentiment incorporating macro surprise scaled by sector sensitivity.
    
    Formula:
        Effective Sentiment = raw_sentiment * (1 + (ETF_Macro_Beta * Ticker_Market_Beta) * macro_shock)
        
    Args:
        ticker: The asset stock ticker symbol (e.g. 'AAPL').
        raw_sentiment: Confidence-weighted raw sentiment score (S_raw).
        macro_shock: The calculated macro shock index (S_t).
        etf_macro_beta: The base beta of the parent ETF against this shock vector.
        ticker_market_beta: The individual stock's market beta (defaults to 1.0 for ETFs).
        
    Returns:
        The adjusted effective sentiment score.
    """
    # Individual Ticker Inheritance Rule
    adjusted_beta = etf_macro_beta * ticker_market_beta
    
    return raw_sentiment * (1.0 + adjusted_beta * macro_shock)


def calculate_portfolio_sentiment(
    weights: Dict[str, float], 
    effective_sentiments: Dict[str, float]
) -> float:
    """Aggregates effective ticker sentiments by portfolio holding weight.
    
    Formula:
        S_portfolio = sum(w_j * Effective_Sentiment_j)
        
    Args:
        weights: Dictionary mapping tickers to portfolio weights (e.g., {'AAPL': 0.4}).
        effective_sentiments: Dictionary mapping tickers to their effective sentiments.
        
    Returns:
        The portfolio-weighted sentiment exposure value.
    """
    if isinstance(weights, str):
        try:
            weights = json.loads(weights)
        except Exception:
            pass
    if isinstance(effective_sentiments, str):
        try:
            effective_sentiments = json.loads(effective_sentiments)
        except Exception:
            pass
            
    if not weights or not effective_sentiments:
        return 0.0
        
    total_exposure = 0.0
    
    for ticker, weight in weights.items():
        sentiment = effective_sentiments.get(ticker, 0.0)
        total_exposure += weight * sentiment
        
    return total_exposure


def calculate_portfolio_drift(
    actual_weights: Dict[str, float], 
    target_weights: Dict[str, float]
) -> float:
    """Calculates active portfolio drift using the L1-norm deviation.
    
    Formula:
        Drift = sum( |w_actual_j - w_target_j| )
        
    Args:
        actual_weights: Dictionary mapping tickers to current actual portfolio weights.
        target_weights: Dictionary mapping tickers to strategic target weights.
        
    Returns:
        The drift distance value (0.0 to 2.0).
    """
    if isinstance(actual_weights, str):
        try:
            actual_weights = json.loads(actual_weights)
        except Exception:
            pass
    if isinstance(target_weights, str):
        try:
            target_weights = json.loads(target_weights)
        except Exception:
            pass
            
    if not isinstance(actual_weights, dict) or not isinstance(target_weights, dict):
        return 0.0
        
    all_tickers = set(actual_weights.keys()).union(set(target_weights.keys()))
    total_drift = 0.0
    
    for ticker in all_tickers:
        actual_w = actual_weights.get(ticker, 0.0)
        target_w = target_weights.get(ticker, 0.0)
        total_drift += abs(actual_w - target_w)
        
    return total_drift


def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    """Normalizes a dictionary of weights so that their sum equals 1.0.
    
    Args:
        weights: Dictionary mapping assets to their raw weights.
        
    Returns:
        Dictionary mapping assets to normalized weights.
    """
    if isinstance(weights, str):
        try:
            weights = json.loads(weights)
        except Exception:
            pass
            
    if not isinstance(weights, dict):
        return {}
        
    total = sum(weights.values())
    if total == 0.0:
        return weights
    return {ticker: weight / total for ticker, weight in weights.items()}

