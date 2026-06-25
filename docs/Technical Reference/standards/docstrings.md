# Docstring Guidelines & Standards

This document establishes the python docstring specifications to follow for all custom functions and agentic tools built under the FinRobot-IntentChain codebase. Adhering to these standards ensures that our LLM agent tools are properly constructed and parsed by the FinRobot ADK.

---

## 1. Core Format Structure

Every docstring must contain the following sections in order:

1. **Summary Line:** A clear, one-sentence description of the function's action.
2. **"Use this tool when" Phrase:** Explicit context-defining instruction that guides the LLM on exactly *when* and *why* this tool should be selected over others.
3. **Args Block:** Standardized parameters definition detailing type hints and optional defaults.
4. **Returns Block:** Description of return payload schemas (e.g., standard dictionaries, DataFrames) and details on failure formats.

---

## 2. Standard Template Example

```python
from typing import Dict, Any, Optional

def fetch_economic_data(
    indicator: str,
    limit: int = 100,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Fetch monthly macroeconomic historical tables for a specified indicator.
    
    Use this tool when you need to retrieve raw historical time-series datasets 
    for major economic metrics (like CPI, inflation, or unemployment rates) 
    to calculate rolling baselines or standard deviations. Do not use this 
    for real-time daily trading signals or stock tickers.
    
    Args:
        indicator (str): The identifier of the macroeconomic index (e.g., 'CPI', 'UNEMPLOYMENT').
        limit (int, optional): The maximum number of historical records to fetch. Defaults to 100.
        api_key (str, optional): The private developer API token. If None, it defaults to the 
            environment variable check. Defaults to None.
            
    Returns:
        Dict[str, Any]: A dictionary containing raw series data matching the schema:
            {
                "status": "success",
                "indicator": str,
                "data": List[Dict[str, str]]
            }
            In case of failure (network errors, invalid keys), returns a structured error payload:
            {
                "status": "error",
                "error_msg": str,
                "data": []
            }
    """
    try:
        # Implementation details...
        pass
    except Exception as e:
        return {
            "status": "error",
            "error_msg": str(e),
            "data": []
        }
```

---

## 3. Mandatory Compliance Rules

* **Type Hints:** Always use strict typing from python's `typing` module (e.g., `List`, `Dict`, `Tuple`, `Optional`). Do not rely solely on docstring descriptions for parameter types.
* **Define Defaults:** If a parameter has a fallback default value (e.g. `limit: int = 100`), declare it explicitly in the `Args:` section so the LLM agent knows the parameter is optional.
* **Error Handling:** Graceful error handling must be built-in. Functions should catch exceptions and return a structured fallback payload (like an empty collection or a dictionary containing `"status": "error"`) instead of crashing the execution thread. Document this return output clearly.
