"""
Reasoning Extractor

Extracts structured reasoning chains from FinRobot agent conversations.

This is the critical component that captures:
- Situation understanding from messages
- Quantitative analysis from tool results
- Options considered from agent reasoning
- Selected actions from tool calls
- Risks and rationale from LLM responses

Works with AutoGen's message format.
"""

import re
import json
from typing import Dict, List, Any, Optional
from functions.models.reasoning_chain import ReasoningChain, ValidationResult


class ReasoningExtractor:
    """
    Extracts reasoning components from FinRobot agent conversations.

    FinRobot uses AutoGen, which has a specific message format:
    {
        "role": "assistant" | "user" | "tool",
        "content": "...",
        "tool_calls": [...],
        "tool_responses": [...]
    }
    """

    def __init__(self):
        self.patterns = self._init_patterns()

    def _init_patterns(self) -> Dict[str, Any]:
        """
        Initialize regex patterns for extracting reasoning components.

        These patterns look for:
        - Situation descriptions
        - Quantitative analysis
        - Risk mentions
        - Decision rationale
        - Alternatives
        """
        return {
            "situation": [
                r"(?:current situation|situation|context|currently)[:\s]+(.+?)(?:\n\n|\n[A-Z]|$)",
                r"(?:as of|upon)[:\s]+(.+?)(?:,|\.|\n)",
                r"portfolio.*?(?:is|has|shows)[:\s]+(.+?)(?:\.|$)",
            ],
            "analysis": [
                r"\$[\d,]+(?:\.\d{2})?[MBK]?",  # Dollar amounts
                r"\d+\.?\d*%",  # Percentages
                r"(?:price|value|amount|position|holding)[:\s]+\$?[\d,]+",
            ],
            "risks": [
                r"(?:risk|concern|caution|warning)[:\s]+(.+?)(?:\.|$)",
                r"(?:potential|possible)[:\s]+(?:downside|loss|issue)[:\s]+(.+?)(?:\.|$)",
            ],
            "rationale": [
                r"(?:because|since|as|given that)[:\s]+(.+?)(?:\.|$)",
                r"(?:reason|rationale)[:\s]+(.+?)(?:\.|$)",
                r"(?:this is|this will|to)[:\s]+(.+?)(?:to|in order to)",
            ],
            "options": [
                r"(?:alternative|option|could also|another approach)[:\s]+(.+?)(?:\.|$)",
                r"(?:instead|alternatively)[:\s]+(.+?)(?:\.|$)",
            ],
        }

    def extract(
        self,
        agent_id: str,
        agent_role: str,
        task: str,
        messages: List[Dict[str, Any]],
        tool_call: Optional[Dict[str, Any]] = None,
    ) -> ReasoningChain:
        """
        Extract complete reasoning chain from agent conversation.

        Args:
            agent_id: Unique agent identifier
            agent_role: Agent's role (e.g., "Market_Analyst")
            task: Original user task/request
            messages: AutoGen message history
            tool_call: The specific tool call we're analyzing (if any)

        Returns:
            ReasoningChain object with extracted reasoning
        """
        chain = ReasoningChain(
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
            conversation_history=messages,
        )

        # Extract from messages
        chain.situation = self._extract_situation(messages)
        chain.quantitative_analysis = self._extract_quantitative_analysis(messages)
        chain.risks = self._extract_risks(messages)
        chain.rationale = self._extract_rationale(messages)
        chain.options = self._extract_options(messages)

        # Extract action from tool call
        if tool_call:
            chain.selected_action = self._extract_action_from_tool_call(tool_call)
        else:
            chain.selected_action = self._extract_action_from_messages(messages)

        # Validate completeness
        validation = self.validate_completeness(chain)
        chain.completeness_score = validation.completeness_score
        chain.missing_components = validation.missing_components

        return chain

    def _extract_situation(self, messages: List[Dict[str, Any]]) -> str:
        """
        Extract situation understanding from messages.

        Look for:
        - Current state descriptions
        - Context setting
        - Portfolio status
        """
        situation_parts = []

        for msg in messages:
            content = msg.get("content", "")
            if not content or msg.get("role") == "tool":
                continue

            # Try each pattern
            for pattern in self.patterns["situation"]:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    text = match.group(1).strip()
                    if len(text) > 20:  # Ignore very short matches
                        situation_parts.append(text)

        # Also look for tool results that describe state
        for msg in messages:
            if msg.get("role") == "tool":
                # Tool responses often contain state information
                content = msg.get("content", "")
                if any(keyword in content.lower() for keyword in ["current", "latest", "as of"]):
                    situation_parts.append(f"Tool data: {content[:200]}")

        return "\n\n".join(situation_parts[:3])  # Top 3 most relevant

    def _extract_quantitative_analysis(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract quantitative analysis (numbers, metrics).

        Look for:
        - Dollar amounts
        - Percentages
        - Metrics from tool responses
        """
        analysis = {
            "amounts": [],
            "percentages": [],
            "metrics": {},
        }

        for msg in messages:
            content = str(msg.get("content", ""))

            # Extract dollar amounts
            dollar_matches = re.findall(r"\$[\d,]+(?:\.\d{2})?[MBK]?", content)
            analysis["amounts"].extend(dollar_matches)

            # Extract percentages
            pct_matches = re.findall(r"\d+\.?\d*%", content)
            analysis["percentages"].extend(pct_matches)

            # Extract key-value metrics from tool responses
            if msg.get("role") == "tool":
                try:
                    # Try to parse as JSON
                    tool_data = json.loads(content) if isinstance(content, str) else content
                    if isinstance(tool_data, dict):
                        analysis["metrics"].update(tool_data)
                except:
                    pass

        return analysis

    def _extract_risks(self, messages: List[Dict[str, Any]]) -> List[str]:
        """
        Extract identified risks from messages.
        """
        risks = []

        for msg in messages:
            content = msg.get("content", "")
            if not content or msg.get("role") == "tool":
                continue

            for pattern in self.patterns["risks"]:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    risk_text = match.group(1).strip() if match.lastindex else match.group(0).strip()
                    if len(risk_text) > 10:
                        risks.append(risk_text)

        return list(set(risks))  # Deduplicate

    def _extract_rationale(self, messages: List[Dict[str, Any]]) -> str:
        """
        Extract decision rationale from messages.
        """
        rationale_parts = []

        for msg in messages:
            content = msg.get("content", "")
            if not content or msg.get("role") == "tool":
                continue

            for pattern in self.patterns["rationale"]:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    text = match.group(1).strip() if match.lastindex else match.group(0).strip()
                    if len(text) > 15:
                        rationale_parts.append(text)

        return " ".join(rationale_parts[:3])  # Combine top 3

    def _extract_options(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Extract alternatives considered.
        """
        options = []

        for msg in messages:
            content = msg.get("content", "")
            if not content or msg.get("role") == "tool":
                continue

            for pattern in self.patterns["options"]:
                matches = re.finditer(pattern, content, re.IGNORECASE)
                for match in matches:
                    option_text = match.group(1).strip() if match.lastindex else match.group(0).strip()
                    if len(option_text) > 10:
                        options.append({
                            "description": option_text,
                            "considered": True,
                        })

        return options

    def _extract_action_from_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract action from AutoGen tool call.

        AutoGen tool call format:
        {
            "id": "call_xxx",
            "function": {
                "name": "function_name",
                "arguments": "json_string"
            },
            "type": "function"
        }
        """
        action = {
            "type": "tool_call",
            "tool_call_id": tool_call.get("id", ""),
        }

        function_info = tool_call.get("function", {})
        action["function"] = function_info.get("name", "")

        # Parse arguments
        args_str = function_info.get("arguments", "{}")
        try:
            action["parameters"] = json.loads(args_str) if isinstance(args_str, str) else args_str
        except:
            action["parameters"] = {"raw": args_str}

        return action

    def _extract_action_from_messages(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Extract action from message content when no explicit tool call.
        """
        # Look at the last assistant message
        for msg in reversed(messages):
            if msg.get("role") == "assistant":
                # Check if it has tool calls
                tool_calls = msg.get("tool_calls", [])
                if tool_calls:
                    return self._extract_action_from_tool_call(tool_calls[-1])

                # Otherwise, extract from content
                content = msg.get("content", "")
                return {
                    "type": "message",
                    "content": content,
                }

        return {"type": "unknown"}

    def validate_completeness(self, chain: ReasoningChain) -> ValidationResult:
        """
        Validate that reasoning chain is complete.

        For financial decisions, we want:
        - Clear situation understanding
        - Quantitative analysis
        - Identified risks
        - Clear rationale
        - Explicit action

        Returns score 0-1 and list of missing components.
        """
        components = {
            "situation": bool(chain.situation and len(chain.situation) > 50),
            "quantitative_analysis": bool(chain.quantitative_analysis.get("amounts") or
                                         chain.quantitative_analysis.get("metrics")),
            "risks": bool(chain.risks),
            "rationale": bool(chain.rationale and len(chain.rationale) > 20),
            "action": bool(chain.selected_action.get("function") or
                          chain.selected_action.get("content")),
            "options": bool(chain.options),  # Nice to have, not required
        }

        # Required components (excluding options which is nice-to-have)
        required = ["situation", "quantitative_analysis", "risks", "rationale", "action"]
        missing = [comp for comp in required if not components[comp]]

        # Calculate score
        score = sum(1 for comp in required if components[comp]) / len(required)

        # Add warnings
        warnings = []
        if not components["options"]:
            warnings.append("No alternative options documented (recommended but not required)")

        return ValidationResult(
            is_valid=score >= 0.6,  # At least 60% complete
            completeness_score=score,
            missing_components=missing,
            warnings=warnings,
        )
