from pydantic import BaseModel, Field
from typing import List, Optional

class MacroReport(BaseModel):
    overall_macro_surprise: float = Field(..., description="Overall macro surprise score")
    market_sentiment: str = Field(..., description="Bullish, Bearish, or Neutral")
    key_drivers: List[str] = Field(..., description="List of key drivers")
    detailed_analysis: str = Field(..., description="Detailed textual analysis")
    warnings: Optional[List[str]] = Field(default_factory=list, description="Warnings or caveats")
