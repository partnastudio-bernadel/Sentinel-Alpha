"""
Governance Engine

Enforces policies before agent actions execute.

Financial policies include:
- Trade size limits
- Blacklist checks
- High-value review requirements
- Pre-earnings restrictions
- Risk limits
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import re
from functions.models.reasoning_chain import ReasoningChain, GovernanceResult


@dataclass
class PolicyRule:
    """A single governance policy rule."""

    name: str
    description: str
    check_function: callable
    severity: str = "error"  # error, warning, info
    auto_block: bool = True  # If True, automatically blocks on violation


class GovernanceEngine:
    """
    Enforces governance policies on reasoning chains.

    Policies are checked before any high-stakes action executes.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize governance engine with policies.

        Args:
            config: Policy configuration (limits, blacklists, etc.)
        """
        self.config = config or self._get_default_config()
        self.policies = self._init_policies()

    def _get_default_config(self) -> Dict[str, Any]:
        """Default financial governance configuration."""
        return {
            "trade_limits": {
                "single_trade_max": 100_000_000,  # $100M max per trade
                "review_threshold": 50_000_000,  # Review required above $50M
                "auto_approve_max": 10_000_000,  # Auto-approve below $10M (if pattern match)
            },
            "blacklist": {
                "symbols": [],  # Restricted symbols
                "actions": [],  # Restricted action types
            },
            "timing_restrictions": {
                "pre_earnings_days": 1,  # Days before earnings to restrict
                "high_volatility_vix": 30,  # VIX threshold for extra review
            },
            "risk_limits": {
                "max_portfolio_concentration": 0.25,  # 25% max in single position
                "max_sector_concentration": 0.40,  # 40% max in single sector
            },
            "review_requirements": {
                "high_value": True,  # Require review for high-value trades
                "new_patterns": True,  # Require review for novel situations
                "low_confidence": True,  # Require review if agent confidence < threshold
            },
        }

    def _init_policies(self) -> List[PolicyRule]:
        """Initialize all governance policies."""
        return [
            PolicyRule(
                name="trade_size_limit",
                description="Enforce maximum trade size limits",
                check_function=self._check_trade_size_limit,
                severity="error",
                auto_block=True,
            ),
            PolicyRule(
                name="blacklist_check",
                description="Check for blacklisted symbols or actions",
                check_function=self._check_blacklist,
                severity="error",
                auto_block=True,
            ),
            PolicyRule(
                name="high_value_review",
                description="Require human review for high-value trades",
                check_function=self._check_high_value_review,
                severity="warning",
                auto_block=False,  # Requires review, doesn't block
            ),
            PolicyRule(
                name="pre_earnings_review",
                description="Require review for trades before earnings",
                check_function=self._check_pre_earnings,
                severity="warning",
                auto_block=False,
            ),
            PolicyRule(
                name="completeness_check",
                description="Ensure reasoning is sufficiently complete",
                check_function=self._check_completeness,
                severity="error",
                auto_block=True,
            ),
        ]

    def enforce(self, chain: ReasoningChain) -> GovernanceResult:
        """
        Enforce all governance policies on a reasoning chain.

        Returns:
            GovernanceResult with decision (approved/rejected/review_required)
        """
        violations = []
        warnings = []
        policy_checks = {}

        # Run all policy checks
        for policy in self.policies:
            try:
                result = policy.check_function(chain)
                policy_checks[policy.name] = result

                if not result["passed"]:
                    if policy.severity == "error":
                        violations.append({
                            "policy": policy.name,
                            "message": result.get("message", "Policy violation"),
                            "auto_block": policy.auto_block,
                        })
                    elif policy.severity == "warning":
                        warnings.append({
                            "policy": policy.name,
                            "message": result.get("message", "Policy warning"),
                        })
            except Exception as e:
                warnings.append({
                    "policy": policy.name,
                    "message": f"Policy check failed: {str(e)}",
                })

        # Determine decision
        decision = self._make_decision(violations, warnings)
        requires_review = self._requires_review(violations, warnings, chain)

        return GovernanceResult(
            decision=decision,
            requires_review=requires_review,
            policy_checks=policy_checks,
            violations=[v["message"] for v in violations],
            warnings=[w["message"] for w in warnings],
            reasoning=self._get_decision_reasoning(decision, violations, warnings),
        )

    def _make_decision(
        self, violations: List[Dict], warnings: List[Dict]
    ) -> str:
        """
        Make governance decision based on violations and warnings.

        Returns: "approved", "rejected", or "review_required"
        """
        # Any auto-blocking violation = rejected
        if any(v.get("auto_block", False) for v in violations):
            return "rejected"

        # Non-blocking violations or warnings = review required
        if violations or warnings:
            return "review_required"

        # No issues = approved
        return "approved"

    def _requires_review(
        self, violations: List[Dict], warnings: List[Dict], chain: ReasoningChain
    ) -> bool:
        """Determine if human review is required."""
        # Any violation or warning requires review
        if violations or warnings:
            return True

        # Low completeness requires review
        if chain.completeness_score < 0.8:
            return True

        return False

    def _get_decision_reasoning(
        self, decision: str, violations: List[Dict], warnings: List[Dict]
    ) -> str:
        """Get human-readable reasoning for the decision."""
        if decision == "rejected":
            return f"Rejected due to policy violations: {', '.join([v['message'] for v in violations])}"
        elif decision == "review_required":
            reasons = [v['message'] for v in violations] + [w['message'] for w in warnings]
            return f"Review required: {', '.join(reasons)}"
        else:
            return "All policy checks passed. Approved for execution."

    # ===== Policy Check Functions =====

    def _check_trade_size_limit(self, chain: ReasoningChain) -> Dict[str, Any]:
        """Check if trade size exceeds limits."""
        action = chain.selected_action
        parameters = action.get("parameters", {})

        # Extract trade size (could be in different parameter names)
        trade_size = None
        for key in ["quantity", "amount", "size", "value"]:
            if key in parameters:
                val = parameters[key]
                # Handle both numeric and string values
                if isinstance(val, str):
                    # Extract number from string like "$90M" or "90000000"
                    match = re.search(r"[\d,]+", val.replace("$", "").replace("M", "000000").replace("K", "000"))
                    if match:
                        trade_size = float(match.group().replace(",", ""))
                else:
                    trade_size = float(val)
                break

        if trade_size is None:
            return {
                "passed": True,
                "message": "No trade size found (non-trading action)",
            }

        max_size = self.config["trade_limits"]["single_trade_max"]

        if trade_size > max_size:
            return {
                "passed": False,
                "message": f"Trade size ${trade_size:,.0f} exceeds maximum ${max_size:,.0f}",
                "trade_size": trade_size,
                "limit": max_size,
            }

        return {
            "passed": True,
            "message": f"Trade size ${trade_size:,.0f} within limits",
            "trade_size": trade_size,
        }

    def _check_blacklist(self, chain: ReasoningChain) -> Dict[str, Any]:
        """Check for blacklisted symbols or actions."""
        action = chain.selected_action
        parameters = action.get("parameters", {})

        # Check symbol
        symbol = parameters.get("symbol", "").upper()
        if symbol in self.config["blacklist"]["symbols"]:
            return {
                "passed": False,
                "message": f"Symbol {symbol} is blacklisted",
            }

        # Check action type
        action_type = action.get("function", "")
        if action_type in self.config["blacklist"]["actions"]:
            return {
                "passed": False,
                "message": f"Action {action_type} is restricted",
            }

        return {
            "passed": True,
            "message": "No blacklist violations",
        }

    def _check_high_value_review(self, chain: ReasoningChain) -> Dict[str, Any]:
        """Check if trade requires review due to high value."""
        if not self.config["review_requirements"]["high_value"]:
            return {"passed": True, "message": "High value review not required by policy"}

        action = chain.selected_action
        parameters = action.get("parameters", {})

        # Extract trade size
        trade_size = None
        for key in ["quantity", "amount", "size", "value"]:
            if key in parameters:
                val = parameters[key]
                if isinstance(val, str):
                    match = re.search(r"[\d,]+", val.replace("$", "").replace("M", "000000").replace("K", "000"))
                    if match:
                        trade_size = float(match.group().replace(",", ""))
                else:
                    trade_size = float(val)
                break

        if trade_size is None:
            return {"passed": True, "message": "Non-trading action"}

        review_threshold = self.config["trade_limits"]["review_threshold"]

        if trade_size > review_threshold:
            return {
                "passed": False,  # False means review required
                "message": f"High-value trade ${trade_size:,.0f} requires human review (threshold: ${review_threshold:,.0f})",
                "trade_size": trade_size,
                "threshold": review_threshold,
            }

        return {
            "passed": True,
            "message": f"Trade size ${trade_size:,.0f} below review threshold",
        }

    def _check_pre_earnings(self, chain: ReasoningChain) -> Dict[str, Any]:
        """Check if trade is happening before earnings announcement."""
        # Look for earnings-related keywords in situation or task
        text = (chain.situation + " " + chain.task).lower()

        earnings_keywords = ["earnings", "earnings call", "quarterly report", "pre-earnings"]

        if any(keyword in text for keyword in earnings_keywords):
            return {
                "passed": False,
                "message": "Trade occurring before earnings announcement requires additional review",
            }

        return {
            "passed": True,
            "message": "No pre-earnings timing concerns",
        }

    def _check_completeness(self, chain: ReasoningChain) -> Dict[str, Any]:
        """Check if reasoning is sufficiently complete."""
        min_completeness = 0.6  # 60% minimum

        if chain.completeness_score < min_completeness:
            return {
                "passed": False,
                "message": f"Reasoning completeness {chain.completeness_score:.1%} below minimum {min_completeness:.1%}. Missing: {', '.join(chain.missing_components)}",
                "completeness": chain.completeness_score,
                "missing": chain.missing_components,
            }

        return {
            "passed": True,
            "message": f"Reasoning completeness {chain.completeness_score:.1%} is acceptable",
            "completeness": chain.completeness_score,
        }
