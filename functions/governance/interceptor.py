"""
IntentCore Reasoning Interceptor

This is the CORE of IntentCore MVP: Proving we can extract real reasoning
from live agent executions.

Key Goals:
1. Intercept agent conversations at the right moment
2. Extract structured reasoning components
3. Validate completeness
4. Provide clean interface for SDK swap

This module is designed to be replaced by the real IntentCore SDK while
maintaining the same interface.
"""

import json
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from functions.models.reasoning_chain import ReasoningChain
from .extractor import ReasoningExtractor


class ReasoningInterceptor:
    """
    Core interceptor for capturing reasoning from agent executions.

    This is the MVP proof-of-concept that will be replaced by the real
    IntentCore SDK. It demonstrates:
    - Successful reasoning extraction from AutoGen agents
    - High completeness scores (80%+)
    - Minimal latency overhead (<100ms)

    SDK Swap Interface:
        The real IntentCore SDK will implement the same interface:
        - intercept_before_action(agent_id, messages, tool_call) -> ReasoningChain
        - get_extraction_quality() -> Dict[str, float]
    """

    def __init__(
        self,
        debug: bool = False,
        log_extractions: bool = True,
    ):
        """
        Initialize reasoning interceptor.

        Args:
            debug: Enable verbose debug logging
            log_extractions: Log all extractions for quality analysis
        """
        self.extractor = ReasoningExtractor()
        self.debug = debug
        self.log_extractions = log_extractions

        # Quality metrics
        self._extraction_count = 0
        self._total_completeness = 0.0
        self._extraction_times = []
        self._extraction_log = []

    def intercept_before_action(
        self,
        agent_id: str,
        agent_role: str,
        task: str,
        messages: List[Dict[str, Any]],
        tool_call: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReasoningChain:
        """
        CORE METHOD: Intercept and extract reasoning before agent action.

        This is called right before a high-stakes action executes.
        It extracts the complete reasoning chain from the conversation.

        Args:
            agent_id: Unique agent identifier
            agent_role: Agent's role (e.g., "Market_Analyst")
            task: Original task/request
            messages: Complete conversation history (AutoGen format)
            tool_call: The specific tool call being intercepted
            metadata: Additional context

        Returns:
            ReasoningChain with extracted reasoning and completeness score

        This method is the SDK interface - the real IntentCore SDK will
        implement this same signature.
        """
        start_time = datetime.utcnow()

        if self.debug:
            self._log_debug("Intercepting action", {
                "agent_id": agent_id,
                "agent_role": agent_role,
                "message_count": len(messages),
                "has_tool_call": tool_call is not None,
            })

        # Extract reasoning from conversation
        chain = self.extractor.extract(
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
            messages=messages,
            tool_call=tool_call,
        )

        # Add metadata
        if metadata:
            chain.conversation_history.append({
                "type": "metadata",
                "data": metadata,
            })

        # Track quality metrics
        extraction_time = (datetime.utcnow() - start_time).total_seconds() * 1000  # ms
        self._extraction_count += 1
        self._total_completeness += chain.completeness_score
        self._extraction_times.append(extraction_time)

        if self.log_extractions:
            self._extraction_log.append({
                "timestamp": start_time.isoformat(),
                "agent_id": agent_id,
                "completeness": chain.completeness_score,
                "extraction_time_ms": extraction_time,
                "message_count": len(messages),
                "has_situation": bool(chain.situation),
                "has_analysis": bool(chain.quantitative_analysis),
                "has_rationale": bool(chain.rationale),
                "risk_count": len(chain.risks),
                "missing_components": chain.missing_components,
            })

        if self.debug:
            self._log_debug("Reasoning extracted", {
                "chain_id": chain.chain_id,
                "completeness": f"{chain.completeness_score:.1%}",
                "extraction_time_ms": f"{extraction_time:.1f}",
                "components_found": {
                    "situation": bool(chain.situation),
                    "analysis": bool(chain.quantitative_analysis),
                    "rationale": bool(chain.rationale),
                    "risks": len(chain.risks),
                    "options": len(chain.options),
                },
            })

        return chain

    def get_extraction_quality(self) -> Dict[str, Any]:
        """
        Get quality metrics for reasoning extraction.

        This proves the MVP is working:
        - High completeness scores (target: 80%+)
        - Low latency (target: <100ms)
        - Successful extraction rate

        Returns:
            Quality metrics dict
        """
        if self._extraction_count == 0:
            return {
                "extraction_count": 0,
                "avg_completeness": 0.0,
                "avg_extraction_time_ms": 0.0,
                "status": "No extractions yet",
            }

        avg_completeness = self._total_completeness / self._extraction_count
        avg_time = sum(self._extraction_times) / len(self._extraction_times)

        return {
            "extraction_count": self._extraction_count,
            "avg_completeness": avg_completeness,
            "avg_extraction_time_ms": avg_time,
            "min_extraction_time_ms": min(self._extraction_times),
            "max_extraction_time_ms": max(self._extraction_times),
            "status": "✅ Working" if avg_completeness >= 0.8 else "⚠️ Low completeness",
            "target_met": {
                "completeness_80_percent": avg_completeness >= 0.8,
                "latency_under_100ms": avg_time < 100,
            },
        }

    def get_extraction_log(self) -> List[Dict[str, Any]]:
        """Get detailed extraction log for analysis."""
        return self._extraction_log

    def export_extraction_report(self, filepath: str = "extraction_report.json"):
        """
        Export detailed extraction report for analysis.

        This report proves the extraction quality and can be shared
        with stakeholders to demonstrate the MVP works.
        """
        report = {
            "summary": self.get_extraction_quality(),
            "detailed_log": self._extraction_log,
            "generated_at": datetime.utcnow().isoformat(),
        }

        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)

        return filepath

    def _log_debug(self, message: str, data: Dict[str, Any]):
        """Debug logging helper."""
        print(f"[IntentCore Interceptor] {message}")
        for key, value in data.items():
            print(f"  {key}: {value}")
        print()

    def reset_metrics(self):
        """Reset quality metrics (useful for testing)."""
        self._extraction_count = 0
        self._total_completeness = 0.0
        self._extraction_times = []
        self._extraction_log = []


# SDK Swap Interface
class IntentCoreSDK:
    """
    Interface specification for the real IntentCore SDK.

    This MVP interceptor will be replaced by the real SDK that implements
    this exact interface. This ensures:
    - Clean swap without code changes
    - Same data structures
    - Same method signatures

    Usage (MVP):
        interceptor = ReasoningInterceptor()
        chain = interceptor.intercept_before_action(...)

    Usage (Real SDK):
        from intentcore_sdk import IntentCoreSDK
        sdk = IntentCoreSDK(api_key="...")
        chain = sdk.intercept_before_action(...)
    """

    def intercept_before_action(
        self,
        agent_id: str,
        agent_role: str,
        task: str,
        messages: List[Dict[str, Any]],
        tool_call: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ReasoningChain:
        """
        Standard interface for reasoning interception.

        Real SDK will:
        - Extract reasoning (same as MVP)
        - Send to IntentCore cloud for governance
        - Apply enterprise policies
        - Return governance decision
        """
        raise NotImplementedError("Use real IntentCore SDK")

    def get_extraction_quality(self) -> Dict[str, Any]:
        """Get quality metrics from SDK."""
        raise NotImplementedError("Use real IntentCore SDK")
