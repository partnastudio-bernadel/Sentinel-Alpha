"""
Reasoning Chain Data Model

Represents the complete reasoning process before an agent action.
This is the core data structure that captures:
- Situation understanding
- Quantitative analysis
- Options considered
- Selected action
- Risk assessment
- Rationale
"""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
from datetime import datetime
from uuid import uuid4
import json


@dataclass
class ReasoningChain:
    """
    Complete reasoning chain for a high-stakes agent decision.

    This captures the FULL context needed for:
    - Human review
    - Governance validation
    - Audit trails
    - Pattern detection
    - Template generation
    """

    # Metadata
    chain_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    agent_id: str = ""
    agent_role: str = ""

    # Task Context
    task: str = ""  # Original user request
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)

    # Reasoning Components (extracted from messages)
    situation: str = ""  # What's the current state?
    quantitative_analysis: Dict[str, Any] = field(default_factory=dict)  # Numbers, metrics
    options: List[Dict[str, Any]] = field(default_factory=list)  # Alternatives considered
    selected_action: Dict[str, Any] = field(default_factory=dict)  # Chosen action
    rationale: str = ""  # Why this action?
    risks: List[str] = field(default_factory=list)  # Identified risks

    # Completeness Assessment
    completeness_score: float = 0.0  # 0-1, how complete is the reasoning?
    missing_components: List[str] = field(default_factory=list)

    # Governance
    policy_results: Dict[str, Any] = field(default_factory=dict)
    requires_review: bool = False
    governance_decision: str = "pending"  # pending, approved, rejected, modified

    # Human Review
    reviewer_id: Optional[str] = None
    review_timestamp: Optional[datetime] = None
    human_decision: Optional[str] = None  # approved, rejected, modified
    human_rationale: Optional[str] = None
    human_modification: Optional[Dict[str, Any]] = None

    # Execution
    execution_status: str = "pending"  # pending, executing, completed, failed
    execution_result: Optional[Dict[str, Any]] = None
    execution_timestamp: Optional[datetime] = None

    # Learning
    pattern_id: Optional[str] = None
    template_id: Optional[str] = None
    confidence_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        # Convert datetime objects to ISO strings
        if isinstance(data['timestamp'], datetime):
            data['timestamp'] = data['timestamp'].isoformat()
        if data.get('review_timestamp'):
            data['review_timestamp'] = data['review_timestamp'].isoformat()
        if data.get('execution_timestamp'):
            data['execution_timestamp'] = data['execution_timestamp'].isoformat()
        return data

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReasoningChain':
        """Create from dictionary."""
        # Convert ISO strings back to datetime
        if isinstance(data.get('timestamp'), str):
            data['timestamp'] = datetime.fromisoformat(data['timestamp'])
        if data.get('review_timestamp'):
            data['review_timestamp'] = datetime.fromisoformat(data['review_timestamp'])
        if data.get('execution_timestamp'):
            data['execution_timestamp'] = datetime.fromisoformat(data['execution_timestamp'])
        return cls(**data)

    def get_summary(self) -> str:
        """Get human-readable summary of the reasoning chain."""
        return f"""
Reasoning Chain Summary
=======================
ID: {self.chain_id}
Agent: {self.agent_role} ({self.agent_id})
Time: {self.timestamp}

Task: {self.task}

Situation:
{self.situation}

Analysis:
{json.dumps(self.quantitative_analysis, indent=2)}

Options Considered: {len(self.options)}
{chr(10).join([f"  - {opt.get('name', 'Option')}: {opt.get('description', '')}" for opt in self.options])}

Selected Action:
{json.dumps(self.selected_action, indent=2)}

Rationale:
{self.rationale}

Risks Identified: {len(self.risks)}
{chr(10).join([f"  - {risk}" for risk in self.risks])}

Completeness: {self.completeness_score:.1%}
Requires Review: {self.requires_review}
Status: {self.governance_decision}
""".strip()

    def is_complete(self, threshold: float = 0.8) -> bool:
        """
        Check if reasoning chain meets completeness threshold.

        For financial decisions, we want 80%+ completeness.
        """
        return self.completeness_score >= threshold

    def get_missing_components_summary(self) -> str:
        """Get summary of what's missing from the reasoning."""
        if not self.missing_components:
            return "Reasoning is complete."

        return f"Missing components ({len(self.missing_components)}):\n" + \
               "\n".join([f"  - {comp}" for comp in self.missing_components])


@dataclass
class ValidationResult:
    """Result of reasoning chain validation."""

    is_valid: bool
    completeness_score: float
    missing_components: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GovernanceResult:
    """Result of governance policy enforcement."""

    decision: str  # approved, rejected, review_required
    requires_review: bool
    policy_checks: Dict[str, Any] = field(default_factory=dict)
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
