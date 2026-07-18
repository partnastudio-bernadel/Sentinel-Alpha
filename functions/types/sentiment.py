from pydantic import BaseModel, Field
from typing import List, Optional

class ArticleSentiment(BaseModel):
    title: str = Field(..., description="Headline of the article")
    source: str = Field(..., description="Source of the article")
    published_at: Optional[str] = Field(None, description="ISO 8601 publication date string")
    sentiment_label: str = Field(..., description="Positive, Neutral, or Negative")
    sentiment_score: float = Field(..., description="Sentiment score from -1.0 to +1.0")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    risk_factors: List[str] = Field(default_factory=list, description="Extracted risk factors")
    reasoning_summary: str = Field(..., description="1-2 sentences explanation of the score")
    flagged: bool = Field(False, description="Whether the sentiment is mixed or data is insufficient")
    flag_reason: Optional[str] = Field(None, description="Reason for flagging, or null")

class SentimentAnalysisReport(BaseModel):
    ticker: str = Field(..., description="The stock ticker symbol")
    articles: List[ArticleSentiment] = Field(..., description="List of analyzed articles")

class SentimentMetadata(BaseModel):
    timestamp: str = Field(..., description="ISO 8601 UTC string")
    article_count: int = Field(..., description="Number of articles processed")

class SentimentReport(BaseModel):
    ticker: str = Field(..., description="The stock ticker symbol")
    metadata: SentimentMetadata = Field(..., description="Metadata for the sentiment run")
    articles: List[ArticleSentiment] = Field(..., description="List of analyzed articles with detailed scores")
    aggregate_score: float = Field(..., description="Consolidated aggregate sentiment score")
    aggregate_label: str = Field(..., description="Consolidated sentiment label (Positive, Neutral, or Negative)")
    velocity: float = Field(0.0, description="Intraday sentiment velocity / rate of change")
    reasoning: str = Field(..., description="Detailed thesis overview justifying the score and portfolio drift")
    warnings: List[str] = Field(default_factory=list, description="Compliance alerts or warnings raised during analysis")
