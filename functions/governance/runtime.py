"""
IntentCore Runtime

Main orchestrator for IntentCore system.

Coordinates:
- Reasoning extraction
- Governance enforcement
- Human review requests
- Database storage
- Audit logging
"""

from typing import Dict, List, Any, Optional
from datetime import datetime

from functions.models.reasoning_chain import ReasoningChain, GovernanceResult
from functions.governance.extractor import ReasoningExtractor
from functions.governance.policies import GovernanceEngine
from functions.utils.db.governance_manager import DatabaseManager


class IntentCoreRuntime:
    """
    Main runtime for IntentCore.

    This is the central coordinator that:
    1. Extracts reasoning from agent conversations
    2. Validates completeness
    3. Enforces governance policies
    4. Manages review queue
    5. Stores audit trails
    """

    def __init__(
        self,
        db_path: str = "intentcore.db",
        governance_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize IntentCore runtime.

        Args:
            db_path: Path to SQLite database
            governance_config: Governance policy configuration
        """
        self.extractor = ReasoningExtractor()
        self.governance = GovernanceEngine(governance_config)
        self.db = DatabaseManager(db_path)

    def capture_reasoning(
        self,
        agent_id: str,
        agent_role: str,
        task: str,
        messages: List[Dict[str, Any]],
        tool_call: Optional[Dict[str, Any]] = None,
    ) -> ReasoningChain:
        """
        Capture reasoning chain from agent conversation.

        This is the main entry point for extracting reasoning.

        Args:
            agent_id: Unique agent identifier
            agent_role: Agent's role (e.g., "Market_Analyst")
            task: Original user task
            messages: Conversation history
            tool_call: Specific tool call being analyzed

        Returns:
            Complete ReasoningChain object
        """
        # Extract reasoning
        chain = self.extractor.extract(
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
            messages=messages,
            tool_call=tool_call,
        )

        # Log extraction
        self.db.log_event(
            event_type="reasoning_extracted",
            event_data={
                "agent_id": agent_id,
                "agent_role": agent_role,
                "completeness": chain.completeness_score,
            },
            chain_id=chain.chain_id,
        )

        return chain

    def enforce_governance(self, chain: ReasoningChain) -> GovernanceResult:
        """
        Enforce governance policies on reasoning chain.

        Args:
            chain: ReasoningChain to validate

        Returns:
            GovernanceResult with decision
        """
        result = self.governance.enforce(chain)

        # Update chain with governance results
        chain.policy_results = result.to_dict()
        chain.requires_review = result.requires_review
        chain.governance_decision = result.decision

        # Log governance check
        self.db.log_event(
            event_type="governance_enforced",
            event_data={
                "decision": result.decision,
                "violations": result.violations,
                "warnings": result.warnings,
            },
            chain_id=chain.chain_id,
        )

        return result

    def process_decision(
        self,
        agent_id: str,
        agent_role: str,
        task: str,
        messages: List[Dict[str, Any]],
        tool_call: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Complete decision processing pipeline.

        This is the main method that:
        1. Captures reasoning
        2. Enforces governance
        3. Handles review if needed
        4. Returns decision

        Args:
            agent_id: Agent identifier
            agent_role: Agent role
            task: User task
            messages: Conversation history
            tool_call: Tool call to process

        Returns:
            Decision dict with:
            - chain_id
            - decision (approved/rejected/review_required)
            - requires_review
            - reasoning_chain
            - governance_result
        """
        # 1. Capture reasoning
        chain = self.capture_reasoning(
            agent_id=agent_id,
            agent_role=agent_role,
            task=task,
            messages=messages,
            tool_call=tool_call,
        )

        # 2. Enforce governance
        governance = self.enforce_governance(chain)

        # 3. Save to database
        self.db.save_reasoning_chain(chain)

        # 4. Add to review queue if needed
        if governance.requires_review:
            queue_id = self.db.add_to_review_queue(
                chain_id=chain.chain_id,
                priority=self._calculate_priority(chain, governance),
            )

            self.db.log_event(
                event_type="review_requested",
                event_data={
                    "queue_id": queue_id,
                    "priority": self._calculate_priority(chain, governance),
                    "reason": governance.reasoning,
                },
                chain_id=chain.chain_id,
            )

        return {
            "chain_id": chain.chain_id,
            "decision": governance.decision,
            "requires_review": governance.requires_review,
            "reasoning_chain": chain,
            "governance_result": governance,
        }

    def submit_human_decision(
        self,
        chain_id: str,
        reviewer_id: str,
        decision: str,
        rationale: Optional[str] = None,
        modification: Optional[Dict[str, Any]] = None,
    ) -> ReasoningChain:
        """
        Submit human review decision.

        Args:
            chain_id: Chain being reviewed
            reviewer_id: Reviewer identifier
            decision: approved/rejected/modified
            rationale: Human reasoning for decision
            modification: Modified parameters (if any)

        Returns:
            Updated ReasoningChain
        """
        # Get chain
        chain = self.db.get_reasoning_chain(chain_id)
        if not chain:
            raise ValueError(f"Chain {chain_id} not found")

        # Update with human decision
        chain.reviewer_id = reviewer_id
        chain.review_timestamp = datetime.utcnow()
        chain.human_decision = decision
        chain.human_rationale = rationale
        chain.human_modification = modification

        # Update governance decision based on human input
        if decision == "approved":
            chain.governance_decision = "approved"
        elif decision == "rejected":
            chain.governance_decision = "rejected"
        elif modification:
            chain.governance_decision = "modified"

        # Save update
        self.db.update_reasoning_chain(chain)

        # Log decision
        self.db.log_event(
            event_type="human_decision",
            event_data={
                "decision": decision,
                "rationale": rationale,
                "has_modification": modification is not None,
            },
            chain_id=chain_id,
            user_id=reviewer_id,
        )

        return chain

    def record_execution(
        self,
        chain_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ):
        """
        Record execution result.

        Args:
            chain_id: Chain that was executed
            status: completed/failed
            result: Execution result data
        """
        chain = self.db.get_reasoning_chain(chain_id)
        if not chain:
            raise ValueError(f"Chain {chain_id} not found")

        chain.execution_status = status
        chain.execution_result = result
        chain.execution_timestamp = datetime.utcnow()

        self.db.update_reasoning_chain(chain)

        self.db.log_event(
            event_type="execution_completed",
            event_data={
                "status": status,
                "result": result,
            },
            chain_id=chain_id,
        )

    def get_pending_reviews(
        self, reviewer_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get pending reviews for a reviewer.

        Args:
            reviewer_id: Optional reviewer filter

        Returns:
            List of pending reviews
        """
        return self.db.get_pending_reviews(assigned_to=reviewer_id)

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get system metrics.

        Returns:
            Metrics dict with:
            - summary_stats
            - daily_metrics
        """
        return {
            "summary": self.db.get_summary_stats(),
            "daily": self.db.get_daily_metrics(days=30),
        }

    def _calculate_priority(
        self, chain: ReasoningChain, governance: GovernanceResult
    ) -> str:
        """
        Calculate review priority based on chain and governance.

        Returns: urgent/high/normal/low
        """
        # Urgent: Policy violations
        if governance.violations:
            return "urgent"

        # High: Large trade amounts or low completeness
        action = chain.selected_action.get("parameters", {})
        if any(key in action for key in ["amount", "value"]):
            # Extract amount
            import re
            amount_str = str(action.get("amount") or action.get("value", ""))
            match = re.search(r"[\d,]+", amount_str.replace("M", "000000"))
            if match:
                amount = float(match.group().replace(",", ""))
                if amount > 50_000_000:  # > $50M
                    return "high"

        if chain.completeness_score < 0.7:
            return "high"

        # Normal: Everything else
        return "normal"
