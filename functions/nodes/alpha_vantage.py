import os
import sys
from typing import Dict, Any
from langchain_core.runnables import RunnableConfig

script_dir = os.path.dirname(os.path.abspath(__file__))
sentiment_dir = os.path.abspath(os.path.join(script_dir, "..", ".."))

if sentiment_dir not in sys.path:
    sys.path.insert(0, sentiment_dir)

from functions.types.macro_state import MacroState
from functions.utils.logging.pipeline_logger import get_pipeline_logger
from functions.utils.macro.calibration_agent import MacroSurpriseCalibrationAgent

# 2. Node: Alpha Vantage Baseline Calibration (Llama-3 model routing)
def alpha_vantage_node(state: MacroState, config: RunnableConfig) -> Dict[str, Any]:
    logger = get_pipeline_logger("macro")
    logger.info("[alpha_vantage_node] Resolving historical baselines and rolling standard deviations...")
    
    calibration = MacroSurpriseCalibrationAgent()
    
    indicators = state.get("indicators", ["CPI", "GDP", "UNEMPLOYMENT"])
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    
    av_data = {}
    for ind in indicators:
        try:
            std_val, warning = calibration.get_historical_std(ind, window=12, api_key=api_key)
            av_data[ind] = {"historical_std": std_val, "warning_flag": warning}
        except Exception as e:
            logger.error(f"Error resolving standard deviation for {ind}: {e}")
            av_data[ind] = {"historical_std": 1.0, "warning_flag": True}
            
    return {"av_indicators": av_data}
